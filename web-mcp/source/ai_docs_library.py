"""Library store: the single read/write boundary for Markdown documents.

All library access flows through LibraryStore: it owns path validation hooks,
shared quotas, and atomic write transactions (CAS via expected_sha256). The
preview facade and the public-docs root are scoped views over the same store.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_docs_common import (
    DEFAULT_ASSETS_PREFIX, DEFAULT_PUBLIC_RENDER_TIMEOUT, MARKDOWN_SUFFIXES,
    ServiceError, markdown_bytes, renderer_fingerprint, resolve_library_path,
    safe_relative_markdown_path, safe_relative_subdirectory,
)
from ai_docs_preview import prepare_preview_html


def _sha256_text(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _timestamp(stat_mtime: float) -> str:
    return datetime.datetime.fromtimestamp(stat_mtime, datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LibraryStore:
    """Read/write boundary for the Markdown library with quotas and CAS writes."""

    def __init__(self, config) -> None:
        self.config = config
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ read

    def entries(self, root: Optional[Path] = None, with_hashes: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
        root = root if root is not None else self.config.library_directory
        if root.is_symlink() or not root.is_dir():
            return [], False
        collected: List[Tuple[str, Path]] = []
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() not in MARKDOWN_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            collected.append((relative.as_posix(), path))
            if len(collected) > self.config.library_max_files:
                raise ServiceError(409, "library_quota_exceeded", "library exceeds library_limits.max_files and must be reduced manually")
        collected.sort(key=lambda item: item[0].lower())
        result = []
        for relative, path in collected:
            try:
                stat = path.stat()
            except OSError:
                continue
            entry = {
                "path": relative,
                "size_bytes": stat.st_size,
                "modified_at": _timestamp(stat.st_mtime),
            }
            if with_hashes:
                try:
                    entry["sha256"] = _sha256_text(path.read_bytes())
                except OSError:
                    continue
            result.append(entry)
        return result, False

    def public_entries(self, with_hashes: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
        entries, truncated = self.entries(self.config.public_root, with_hashes)
        for entry in entries:
            entry["public_url"] = self.config.public_document_url(entry["path"])
        return entries, truncated

    def read(self, relative: str, root: Optional[Path] = None) -> Dict[str, Any]:
        base = root if root is not None else self.config.library_directory
        target = resolve_library_path(base, relative)
        if not target.is_file():
            raise ServiceError(404, "not_found", "Markdown document was not found")
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ServiceError(422, "invalid_document", "Markdown document must be readable UTF-8") from error
        stat = target.stat()
        return {
            "path": relative,
            "markdown": content,
            "size_bytes": stat.st_size,
            "modified_at": _timestamp(stat.st_mtime),
            "sha256": _sha256_text(content.encode("utf-8")),
        }

    def public_read(self, relative: str) -> Dict[str, Any]:
        return self.read(relative, root=self.config.public_root)

    # ---------------------------------------------------------------- listing

    def list_documents(
        self,
        prefix: Optional[str] = None,
        recursive: bool = True,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List published documents with prefix filtering and cursor pagination."""
        entries, _ = self.public_entries(with_hashes=True)
        if prefix:
            directory = safe_relative_subdirectory(prefix, "prefix").rstrip("/")
            prefix_posix = directory + "/" if directory else ""
            if recursive:
                entries = [entry for entry in entries if entry["path"].startswith(prefix_posix)]
            else:
                entries = [
                    entry for entry in entries
                    if entry["path"].startswith(prefix_posix) and "/" not in entry["path"][len(prefix_posix):]
                ]
        start = 0
        if cursor is not None:
            last = self._decode_cursor(cursor)
            for index, entry in enumerate(entries):
                if entry["path"].lower() > last.lower():
                    start = index
                    break
            else:
                start = len(entries)
        page = entries[start:start + limit]
        result: Dict[str, Any] = {"documents": page, "count": len(page)}
        if start + limit < len(entries):
            result["next_cursor"] = self._encode_cursor(page[-1]["path"])
        return result

    @staticmethod
    def _encode_cursor(path: str) -> str:
        return base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> str:
        if not cursor:
            raise ServiceError(400, "invalid_cursor", "cursor is not valid")
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
            path = decoded.decode("utf-8")
        except (ValueError, UnicodeEncodeError, UnicodeDecodeError, binascii.Error) as error:
            raise ServiceError(400, "invalid_cursor", "cursor is not valid") from error
        if not path:
            raise ServiceError(400, "invalid_cursor", "cursor is not valid")
        return path

    # ----------------------------------------------------------------- write

    def write(
        self,
        relative: str,
        markdown: Any,
        overwrite: bool = False,
        expected_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically write a library-relative Markdown path under one lock.

        - create (overwrite=False) fails with document_exists when occupied
        - overwrite=True + identical content returns unchanged (mtime untouched)
        - expected_sha256 (requires overwrite=True) implements optimistic CAS
        - library-wide quota always applies; paths under the public root also
          consume the public sub-quota
        """
        if type(overwrite) is not bool:
            raise ServiceError(400, "invalid_argument", "overwrite must be boolean")
        if expected_sha256 is not None:
            if not overwrite:
                raise ServiceError(400, "invalid_argument", "expected_sha256 requires overwrite=true")
            if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(
                character not in "0123456789abcdef" for character in expected_sha256
            ):
                raise ServiceError(400, "invalid_argument", "expected_sha256 must be a lowercase SHA-256 hex digest")
        content = markdown_bytes(markdown)
        if not content:
            raise ServiceError(400, "empty_markdown", "Markdown input must not be empty")
        if len(content) > self.config.max_upload_bytes:
            raise ServiceError(413, "upload_too_large", "Markdown input exceeds max_upload_bytes")
        relative = safe_relative_markdown_path(relative)
        if len(relative.split("/")) > self.config.library_max_path_depth:
            raise ServiceError(409, "library_quota_exceeded", "path exceeds library_limits.max_path_depth")
        target = resolve_library_path(self.config.library_directory, relative)
        parent = target.parent
        content_sha256 = _sha256_text(content)
        # 公共子配额只约束落在公开区内的路径；深度按最终库相对路径计算。
        public_prefix = self.config.public_directory + "/"
        in_public = relative.startswith(public_prefix)
        with self.lock:
            exists = target.exists() or target.is_symlink()
            if exists and (target.is_symlink() or not target.is_file()):
                raise ServiceError(409, "invalid_target", "target is not a regular Markdown file")
            current_sha256: Optional[str] = None
            existing_size = 0
            if exists:
                try:
                    existing_content = target.read_bytes()
                except OSError as error:
                    raise ServiceError(500, "io_error", "cannot read the existing document") from error
                existing_size = len(existing_content)
                current_sha256 = _sha256_text(existing_content)
            if exists and not overwrite:
                raise ServiceError(409, "document_exists", "document already exists", details={"sha256": current_sha256})
            if overwrite and expected_sha256 is not None and (
                current_sha256 is None or not hmac.compare_digest(current_sha256, expected_sha256)
            ):
                raise ServiceError(409, "version_conflict", "document changed since expected_sha256 was read")
            if current_sha256 is not None and hmac.compare_digest(current_sha256, content_sha256):
                return {"path": relative, "status": "unchanged", "sha256": content_sha256, "size_bytes": len(content)}
            self._check_quota(self.config.library_directory, self.config.library_max_files, self.config.library_max_total_bytes, existing_size, len(content))
            if in_public:
                self._check_quota(self.config.public_root, self.config.public_max_files, self.config.public_max_total_bytes, existing_size, len(content), label="public_docs")
            if parent.is_symlink():
                raise ServiceError(400, "invalid_path", "path must not contain symlinked directories")
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise ServiceError(500, "io_error", "cannot create the target directory") from error
            mode = 0o600
            if target.is_file():
                mode = target.stat().st_mode & 0o777
            descriptor, temporary = tempfile.mkstemp(prefix=".ai-docs-save-", dir=str(parent))
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, mode or 0o600)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        status = "replaced" if current_sha256 is not None else "created"
        return {"path": relative, "status": status, "sha256": content_sha256, "size_bytes": len(content)}

    def publish(
        self,
        relative: str,
        markdown: Any,
        overwrite: bool = False,
        expected_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Write a Markdown document into the public docs root."""
        relative = safe_relative_markdown_path(relative)
        result = self.write(
            self.config.public_directory + "/" + relative, markdown, overwrite, expected_sha256
        )
        result["path"] = relative
        result["public_url"] = self.config.public_document_url(relative)
        result["render_status"] = "not_checked"
        return result

    def _check_quota(self, root: Path, max_files: int, max_total_bytes: int, existing_size: int, added_size: int, label: str = "library_limits") -> None:
        files, total_bytes = self._quota_usage(root)
        files_after = files + (0 if existing_size else 1)
        if files_after > max_files:
            raise ServiceError(409, "library_quota_exceeded", "write exceeds {}.max_files".format(label))
        if total_bytes - existing_size + added_size > max_total_bytes:
            raise ServiceError(409, "library_quota_exceeded", "write exceeds {}.max_total_bytes".format(label))

    def _quota_usage(self, root: Path) -> Tuple[int, int]:
        files = 0
        total_bytes = 0
        if root.is_symlink() or not root.is_dir():
            return 0, 0
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.suffix.lower() not in MARKDOWN_SUFFIXES:
                continue
            try:
                size = path.stat().st_size
            except OSError as error:
                raise ServiceError(500, "io_error", "cannot inspect the library quota") from error
            files += 1
            total_bytes += size
        return files, total_bytes


class PreviewStore:
    """Preview-facing facade over the LibraryStore plus on-demand rendering."""

    def __init__(self, config, capacity: threading.BoundedSemaphore, library: LibraryStore) -> None:
        self.config = config
        self.capacity = capacity
        self.library = library

    def entries(self) -> Tuple[List[Dict[str, Any]], bool]:
        entries, truncated = self.library.entries()
        entries.sort(key=lambda entry: (entry["path"].lower(), entry["path"]))
        return entries, truncated

    def read(self, relative: str) -> Dict[str, Any]:
        return self.library.read(relative)

    def save(self, relative: str, markdown: str) -> Dict[str, Any]:
        if not self.config.preview_write_back:
            raise ServiceError(403, "write_back_disabled", "preview write-back is disabled by configuration")
        result = self.library.write(relative, markdown, overwrite=True)
        return {"saved": True, "path": result["path"], "size_bytes": result["size_bytes"]}

    def render(self, relative: str, markdown: str, link_target: str = "_top", editor_preview: bool = False) -> str:
        if link_target not in ("_top", "_blank"):
            raise ServiceError(500, "invalid_configuration", "preview link target must be _top or _blank")
        relative = safe_relative_markdown_path(relative)
        content = markdown_bytes(markdown)
        if not content:
            raise ServiceError(400, "empty_markdown", "Markdown input must not be empty")
        if len(content) > self.config.max_upload_bytes:
            raise ServiceError(413, "upload_too_large", "Markdown input exceeds max_upload_bytes")
        rendered = render_markdown_document(
            self.config, self.capacity, Path(relative).name, content,
            self.config.render_timeout_seconds, ".ai-docs-preview-",
        )
        return prepare_preview_html(rendered, relative, self.config.preview_prefix, link_target, editor_preview)


def _renderer_environment() -> Dict[str, str]:
    """Minimal environment for renderer subprocesses (also used for asset export)."""
    return {
        name: os.environ[name]
        for name in ("HOME", "LANG", "LC_ALL", "PATH", "TZ")
        if name in os.environ
    }


def render_markdown_document(
    config,
    capacity: threading.BoundedSemaphore,
    filename: str,
    content: bytes,
    timeout_seconds: int,
    temporary_prefix: str,
) -> str:
    """Run the bundled renderer once under the given capacity and timeout.

    Shared by the preview facade and the public docs renderer; callers own the
    capacity semaphore, timeout policy, and any post-processing of the HTML.
    """
    if not capacity.acquire(blocking=False):
        raise ServiceError(429, "render_busy", "all render workers are busy", {"Retry-After": "2"})
    try:
        with tempfile.TemporaryDirectory(prefix=temporary_prefix, dir=str(config.workspace_root)) as temporary:
            workspace = Path(temporary)
            source = workspace / filename
            output = workspace / "output.html"
            source.write_bytes(content)
            command = [
                str(config.node_executable),
                str(config.renderer_directory / "scripts" / "build.js"),
                "--input", str(source),
                "--output", str(output),
                "--output-mode", "single",
                # 服务端统一只出引用型 HTML：大资源由 /assets/<fingerprint>/ 端点托管，
                # 避免每次渲染重复内联 3.4MB 脚本阻塞首屏。
                "--resources-mode", "linked",
                "--public-path", "{}{}/".format(DEFAULT_ASSETS_PREFIX, renderer_fingerprint(config)),
            ]
            environment = _renderer_environment()
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(config.workspace_root),
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ServiceError(504, "render_timeout", "rendering exceeded the configured timeout") from error
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()[-4000:]
                for path_value, replacement in (
                    (str(source), filename),
                    (str(workspace), "<sandbox>"),
                    (str(config.renderer_directory), "<renderer>"),
                    (str(config.workspace_root), "<workspace>"),
                    (str(config.library_directory), "<library>"),
                ):
                    detail = detail.replace(path_value, replacement)
                raise ServiceError(422, "render_failed", detail or "AI Docs renderer failed")
            if not output.is_file() or output.stat().st_size == 0:
                raise ServiceError(500, "render_failed", "renderer produced no HTML output")
            return output.read_text(encoding="utf-8")
    finally:
        capacity.release()


# ---------------------------------------------------------------------------
# Renderer asset endpoint (/assets/<fingerprint>/<file>)
#
# Linked HTML only writes URLs; the bytes come from here. The conversion rules
# stay in scripts/build.js (--emit-resources), so the service never reimplements
# resourceContent() transformations (mermaid/d3/katex adjustments).

_ASSET_READY_MARKER = ".ready"
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")
_ASSET_CONTENT_TYPES = {
    "script": "application/javascript; charset=utf-8",
    "style": "text/css; charset=utf-8",
}
_ASSET_EXPORT_LOCKS: Dict[str, threading.Lock] = {}
_ASSET_EXPORT_LOCKS_GUARD = threading.Lock()


def _asset_export_lock(key: str) -> threading.Lock:
    with _ASSET_EXPORT_LOCKS_GUARD:
        lock = _ASSET_EXPORT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ASSET_EXPORT_LOCKS[key] = lock
        return lock


@lru_cache(maxsize=8)
def _resource_content_types(renderer_directory: str, manifest_mtime: int) -> Dict[str, str]:
    del manifest_mtime  # part of the cache key so renderer updates re-read it
    manifest_path = Path(renderer_directory) / "assets" / "default-resources.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ServiceError(500, "renderer_manifest_unavailable", "resource manifest is unreadable") from error
    types: Dict[str, str] = {}
    if isinstance(data, dict):
        for item in data.values():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            content_type = _ASSET_CONTENT_TYPES.get(item.get("type"))
            if isinstance(output, str) and content_type and "/" not in output and output not in ("", ".", ".."):
                types[output] = content_type
    if not types:
        raise ServiceError(500, "renderer_manifest_unavailable", "resource manifest has no servable assets")
    return types


def resource_content_types(config) -> Dict[str, str]:
    manifest_path = config.renderer_directory / "assets" / "default-resources.json"
    try:
        manifest_mtime = int(manifest_path.stat().st_mtime)
    except OSError as error:
        raise ServiceError(500, "renderer_manifest_unavailable", "resource manifest is unreadable") from error
    return _resource_content_types(str(config.renderer_directory), manifest_mtime)


def ensure_resource_assets(config, fingerprint: str, timeout_seconds: int = DEFAULT_PUBLIC_RENDER_TIMEOUT) -> Path:
    """Materialize converted assets under workspace_root/asset-cache/<fingerprint>.

    Idempotent per fingerprint: a ready marker is written only after a complete
    export, and the final rename happens under a per-fingerprint lock so
    concurrent first requests cannot observe a partial directory.
    """
    if not _FINGERPRINT_PATTERN.fullmatch(fingerprint or ""):
        raise ServiceError(404, "not_found", "asset was not found")
    root = config.workspace_root / "asset-cache" / fingerprint
    if (root / _ASSET_READY_MARKER).is_file():
        return root
    with _asset_export_lock(fingerprint):
        if (root / _ASSET_READY_MARKER).is_file():
            return root
        parent = root.parent
        parent.mkdir(parents=True, exist_ok=True)
        # Only our own cache paths: incomplete leftovers are safe to discard.
        temporary = parent / "{}.{}".format(fingerprint, os.getpid())
        for stale in (temporary, root):
            if stale.exists():
                shutil.rmtree(stale, ignore_errors=True)
        command = [
            str(config.node_executable),
            str(config.renderer_directory / "scripts" / "build.js"),
            "--emit-resources", str(temporary),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(config.workspace_root),
                env=_renderer_environment(),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ServiceError(504, "asset_export_timeout", "asset export exceeded the configured timeout") from error
        if completed.returncode != 0 or not temporary.is_dir():
            detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
            shutil.rmtree(temporary, ignore_errors=True)
            raise ServiceError(500, "asset_export_failed", detail or "renderer asset export failed")
        try:
            (temporary / _ASSET_READY_MARKER).write_text("", encoding="utf-8")
            os.replace(temporary, root)
        except OSError as error:
            shutil.rmtree(temporary, ignore_errors=True)
            raise ServiceError(500, "asset_export_failed", "cannot publish exported assets") from error
    return root


def read_resource_asset(config, fingerprint: str, name: str, timeout_seconds: int = DEFAULT_PUBLIC_RENDER_TIMEOUT) -> Tuple[str, bytes]:
    """Return (content_type, body) for a manifest-whitelisted asset file."""
    # 指纹必须精确匹配当前 renderer：随机合法 hex 不得触发资源导出。
    if not _FINGERPRINT_PATTERN.fullmatch(fingerprint or "") or fingerprint != renderer_fingerprint(config):
        raise ServiceError(404, "not_found", "asset was not found")
    content_type = resource_content_types(config).get(name)
    if content_type is None:
        raise ServiceError(404, "not_found", "asset was not found")
    root = ensure_resource_assets(config, fingerprint, timeout_seconds)
    try:
        body = (root / name).read_bytes()
    except OSError as error:
        raise ServiceError(404, "not_found", "asset was not found") from error
    return content_type, body
