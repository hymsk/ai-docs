#!/usr/bin/env python3
"""Install and manage the optional AI Docs Web publisher.

The Skill directory is an installation source, not a stable service runtime.
This manager copies the canonical renderer and Web MCP server into an XDG
runtime tree, keeps secrets outside the repository, and manages OpenCode only
when the user explicitly invokes the corresponding command.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import pwd
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse


APP_NAME = "ai-docs-web"
MCP_NAME = "ai-docs"
VERSION = "1.0.0rc1"
TOKEN_ENV = "AI_DOCS_API_TOKEN"
CONFIG_ENV = "AI_DOCS_MCP_CONFIG"
ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
URL_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$")
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)
def _license_files() -> Tuple[str, ...]:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "licenses/manifest.json").read_text(encoding="utf-8"))
    paths = tuple(entry["file"] for entry in manifest["files"])
    if len(set(paths)) != len(paths) or any(
        not name.startswith("licenses/") or Path(name).is_absolute() or ".." in Path(name).parts
        for name in paths
    ):
        raise ValueError("invalid license manifest paths")
    return ("LICENSE", "THIRD_PARTY_NOTICES.md", "licenses/README.md", "licenses/manifest.json") + paths


LICENSE_FILES = _license_files()
RUNTIME_FILES = (
    "VERSION",
    "source/ai_docs_web.py",
    "source/ai_docs_common.py",
    "source/ai_docs_config.py",
    "source/ai_docs_preview.py",
    "source/ai_docs_library.py",
    "source/ai_docs_public.py",
    "source/ai_docs_mcp.py",
    "source/ai_docs_http.py",
    "assets/default-resources.json",
    "scripts/build.js",
    "scripts/vendor/d3.min.js",
    "scripts/vendor/echarts.min.js",
    "scripts/vendor/highlight-styles.css",
    "scripts/vendor/highlight.min.js",
    "scripts/vendor/katex.min.css",
    "scripts/vendor/katex.min.js",
    "scripts/vendor/markdown-it.min.js",
    "scripts/vendor/markmap-lib.browser.js",
    "scripts/vendor/markmap-view.browser.js",
    "scripts/vendor/mermaid.min.js",
) + LICENSE_FILES


class ManagerError(RuntimeError):
    """An expected, user-actionable management error."""


@dataclass(frozen=True)
class InstallPaths:
    scope: str
    runtime: Path
    config: Path
    credentials: Path
    documents: Path
    static: Path
    metadata: Path
    library: Path
    workspace: Path
    state: Path
    unit: Path
    opencode_config: Path
    opencode_state: Path
    nginx_output: Path


@dataclass(frozen=True)
class StorageSettings:
    workspace: Path
    library: Path
    public: Path
    write_back: bool


def _absolute(value: Any) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def _home() -> Path:
    return _absolute(os.environ.get("HOME") or "~")


def _xdg(environment: str, fallback: Path) -> Path:
    configured = os.environ.get(environment, "").strip()
    return _absolute(configured) if configured else fallback


def install_paths(scope: str) -> InstallPaths:
    if scope == "system":
        return InstallPaths(
            scope=scope,
            runtime=Path("/opt/ai-docs-web/runtime"),
            config=Path("/etc/ai-docs-web/server.json"),
            credentials=Path("/etc/ai-docs-web/service.env"),
            documents=Path("/var/lib/ai-docs-web/public/docs"),
            static=Path("/var/lib/ai-docs-web/public/static"),
            metadata=Path("/var/lib/ai-docs-web/private/metadata"),
            library=Path("/var/lib/ai-docs-web/private/library"),
            workspace=Path("/var/cache/ai-docs-web/workspace"),
            state=Path("/var/lib/ai-docs-web/private/manager/install.json"),
            unit=Path("/etc/systemd/system/ai-docs-web.service"),
            opencode_config=_xdg("XDG_CONFIG_HOME", _home() / ".config") / "opencode" / "opencode.json",
            opencode_state=_xdg("XDG_STATE_HOME", _home() / ".local" / "state") / APP_NAME / "opencode-registration.json",
            nginx_output=Path("/etc/nginx/conf.d/ai-docs-web.conf"),
        )
    home = _home()
    data_home = _xdg("XDG_DATA_HOME", home / ".local" / "share")
    config_home = _xdg("XDG_CONFIG_HOME", home / ".config")
    cache_home = _xdg("XDG_CACHE_HOME", home / ".cache")
    state_home = _xdg("XDG_STATE_HOME", home / ".local" / "state")
    app_data = data_home / APP_NAME
    app_state = state_home / APP_NAME
    return InstallPaths(
        scope=scope,
        runtime=app_data / "runtime",
        config=config_home / APP_NAME / "server.json",
        credentials=config_home / APP_NAME / "credentials.env",
        documents=app_data / "data" / "public" / "docs",
        static=app_data / "data" / "public" / "static",
        metadata=app_data / "data" / "private" / "metadata",
        library=app_data / "data" / "private" / "library",
        workspace=cache_home / APP_NAME / "workspace",
        state=app_state / "install.json",
        unit=config_home / "systemd" / "user" / "ai-docs-web.service",
        opencode_config=config_home / "opencode" / "opencode.json",
        opencode_state=app_state / "opencode-registration.json",
        nginx_output=app_state / "nginx" / "ai-docs-web.conf",
    )


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _runtime_sources() -> Dict[str, Path]:
    root = skill_root()
    source_dir = root / "web-mcp" / "source"
    return {
        "VERSION": root / "VERSION",
        **{name: root / name for name in LICENSE_FILES},
        **{
            "source/" + name: source_dir / name
            for name in (
                "ai_docs_web.py", "ai_docs_common.py", "ai_docs_config.py",
                "ai_docs_preview.py", "ai_docs_library.py", "ai_docs_public.py",
                "ai_docs_mcp.py", "ai_docs_http.py",
            )
        },
        "assets/default-resources.json": root / "assets" / "default-resources.json",
        "scripts/build.js": root / "scripts" / "build.js",
        **{
            "scripts/vendor/" + name: root / "scripts" / "vendor" / name
            for name in (
                "d3.min.js", "echarts.min.js", "highlight-styles.css", "highlight.min.js",
                "katex.min.css", "katex.min.js", "markdown-it.min.js",
                "markmap-lib.browser.js", "markmap-view.browser.js", "mermaid.min.js",
            )
        },
    }


def _validate_parent_chain(path: Path, label: str) -> None:
    current = _absolute(path.parent)
    while current != current.parent:
        try:
            if current.is_symlink():
                raise ManagerError("{} contains a symlinked directory: {}".format(label, current))
            if current.exists() and not current.is_dir():
                raise ManagerError("{} parent is not a directory: {}".format(label, current))
        except PermissionError as error:
            raise ManagerError("{} parent is not accessible to the installer: {}".format(label, current)) from error
        current = current.parent


def _read(path: Path, label: str) -> Optional[bytes]:
    _validate_parent_chain(path, label)
    if path.is_symlink():
        raise ManagerError("{} is a symlink: {}".format(label, path))
    if not path.exists():
        return None
    if not path.is_file():
        raise ManagerError("{} is not a regular file: {}".format(label, path))
    try:
        return path.read_bytes()
    except OSError as error:
        raise ManagerError("cannot read {}: {}".format(label, error)) from error


def _write(path: Path, content: bytes, mode: int, label: str) -> None:
    _validate_parent_chain(path, label)
    if path.is_symlink():
        raise ManagerError("{} is a symlink: {}".format(label, path))
    try:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".ai-docs-web-", dir=str(path.parent))
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
            os.chmod(path, mode)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except OSError as error:
        raise ManagerError("cannot write {}: {}".format(label, error)) from error


def _restore_file(path: Path, content: Optional[bytes], mode: int, label: str) -> None:
    if content is None:
        if path.is_symlink():
            raise ManagerError("cannot restore {} because the target became a symlink: {}".format(label, path))
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise ManagerError("cannot remove newly created {}: {}".format(label, error)) from error
        return
    _write(path, content, mode, label)


def _json_bytes(value: Dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _json_object(path: Path, label: str) -> Tuple[Dict[str, Any], Optional[bytes]]:
    raw = _read(path, label)
    if raw is None:
        return {}, None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ManagerError("{} is not valid JSON: {}".format(label, error)) from error
    if not isinstance(value, dict):
        raise ManagerError("{} must be a JSON object".format(label))
    return value, raw


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _source_digest() -> str:
    digest = hashlib.sha256()
    sources = _runtime_sources()
    if tuple(sorted(sources)) != tuple(sorted(RUNTIME_FILES)):
        raise ManagerError("internal runtime file list is inconsistent")
    for relative in sorted(sources):
        source = sources[relative]
        if source.is_symlink() or not source.is_file():
            raise ManagerError("runtime source is unavailable or unsafe: {}".format(source))
        encoded = relative.encode("utf-8")
        content = source.read_bytes()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _runtime_manifest(runtime: Path) -> Optional[Dict[str, Any]]:
    path = runtime / "runtime-manifest.json"
    raw = _read(path, "runtime manifest")
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ManagerError("runtime manifest is not valid JSON: {}".format(error)) from error
    if not isinstance(value, dict):
        raise ManagerError("runtime manifest must be a JSON object")
    return value


def _installed_digest(runtime: Path) -> Optional[str]:
    if runtime.is_symlink() or not runtime.is_dir():
        return None
    digest = hashlib.sha256()
    files = []
    for path in runtime.rglob("*"):
        if path.is_symlink():
            return None
        if path.is_dir():
            continue
        if not path.is_file():
            return None
        relative = path.relative_to(runtime).as_posix()
        if relative == "runtime-manifest.json":
            continue
        # Module imports may leave bytecode caches even though the entry sets
        # sys.dont_write_bytecode; they are derived data, never drift.
        if "__pycache__" in path.relative_to(runtime).parts:
            continue
        files.append((relative, path))
    for relative, path in sorted(files):
        encoded = relative.encode("utf-8")
        content = path.read_bytes()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _read_state(path: Path) -> Optional[Dict[str, Any]]:
    value, raw = _json_object(path, "managed install state")
    return value if raw is not None else None


def _valid_state(state: Optional[Dict[str, Any]], paths: InstallPaths) -> bool:
    return bool(
        state
        and state.get("schema_version") == 1
        and state.get("scope") == paths.scope
        and state.get("runtime") == str(paths.runtime)
        and state.get("config") == str(paths.config)
        and state.get("credentials") == str(paths.credentials)
        and state.get("unit") == str(paths.unit)
        and isinstance(state.get("source_digest"), str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", state["source_digest"]))
        and isinstance(state.get("unit_sha256"), str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", state["unit_sha256"]))
    )


def _systemd_quote(value: Path) -> str:
    return '"{}"'.format(str(value).replace("\\", "\\\\").replace('"', '\\"'))


def _systemd_path(value: Path) -> str:
    """Encode one absolute path for non-command systemd directives.

    Directives such as WorkingDirectory= treat surrounding quotes as literal
    path characters on supported systemd releases. Use unit-file escapes
    instead, while also preventing accidental specifier expansion.
    """
    encoded = []
    for character in str(value):
        if character == "%":
            encoded.append("%%")
        elif character in "\\\"'":
            encoded.append("\\x{:02x}".format(ord(character)))
        elif character.isspace() or ord(character) < 32 or ord(character) == 127:
            encoded.extend("\\x{:02x}".format(byte) for byte in character.encode("utf-8"))
        else:
            encoded.append(character)
    return "".join(encoded)


def _installed_node(paths: InstallPaths) -> Optional[Path]:
    config, raw = _json_object(paths.config, "server configuration")
    if raw is None:
        return None
    renderer = config.get("renderer")
    if not isinstance(renderer, dict):
        return None
    value = renderer.get("node")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _storage_settings(paths: InstallPaths, config: Optional[Dict[str, Any]] = None) -> StorageSettings:
    """Validate mount/write boundaries without creating directories.

    Use the same pure v1 migration as installation so the first upgrade unit
    already targets the migrated library, including v1's derived default.
    """
    if config is None:
        config, raw = _json_object(paths.config, "server configuration")
        if raw is not None:
            migrated = _migrate_server_config(raw)
            if migrated is not None:
                config = migrated
        else:
            config = {"workspace_root": str(paths.workspace), "library_directory": str(paths.library)}
    source_dir = skill_root() / "web-mcp" / "source"
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
    from ai_docs_common import MAX_PREVIEW_PATH_DEPTH, ServiceError, safe_relative_subdirectory

    def directory(value: Any, label: str) -> Path:
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ManagerError("{} must be a non-empty absolute directory without control characters".format(label))
        path = Path(value)
        if not path.is_absolute() or ".." in path.parts:
            raise ManagerError("{} must be absolute and must not contain dot-dot segments".format(label))
        # Linux treats // as /; normalize before overlap checks. Do not expand
        # ~ using the manager's account: system services use a different HOME.
        path = Path("/" + str(path).lstrip("/"))
        # scope 限制是纯路径规则，必须先于任何文件系统探测：非 root 安装账户
        # 对 /root 下路径做 lstat 会直接 PermissionError，规则拒绝不应依赖
        # 探测能力（CI 等非 root 环境会因此崩溃而非干净报错）。
        if paths.scope == "system" and any(root == path or root in path.parents for root in (Path("/root"), Path("/home"), Path("/run/user"))):
            raise ManagerError("system scope requires {} outside home and user runtime directories".format(label))
        _validate_parent_chain(path, label)
        try:
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise ManagerError("{} must be a non-symlinked directory: {}".format(label, path))
        except PermissionError as error:
            raise ManagerError("{} must be accessible to the installer: {}".format(label, path)) from error
        return path

    workspace = directory(config.get("workspace_root"), "workspace_root")
    library = directory(config.get("library_directory"), "library_directory")

    def overlaps(left: Path, right: Path) -> bool:
        return left == right or left in right.parents or right in left.parents

    if overlaps(workspace, library):
        raise ManagerError("workspace_root and library_directory must not overlap")
    for storage in (workspace, library):
        for protected in (paths.runtime, paths.config.parent, paths.state.parent, paths.unit.parent):
            if overlaps(storage, protected):
                raise ManagerError("storage directory must not overlap managed runtime, configuration or state: {}".format(storage))
    try:
        relative = safe_relative_subdirectory(config.get("public_directory", "public"), "public_directory")
    except ServiceError as error:
        raise ManagerError(error.message) from error
    if len(relative.split("/")) > MAX_PREVIEW_PATH_DEPTH:
        raise ManagerError("public_directory is too deep")
    public = directory(str(library / relative), "public_directory")
    preview = config.get("preview")
    if preview is None:
        preview = {}
    if not isinstance(preview, dict) or type(preview.get("write_back", True)) is not bool:
        raise ManagerError("preview.write_back must be boolean in a preview object")
    return StorageSettings(workspace, library, public, preview.get("write_back", True))


def _unit_content(paths: InstallPaths, node_executable: Optional[Path] = None, storage: Optional[StorageSettings] = None) -> bytes:
    node = node_executable or _installed_node(paths)
    if node is None:
        node = _resolve_node_executable(paths.scope)
    user_lines = ""
    install_target = "default.target"
    storage = storage or _storage_settings(paths)
    if paths.scope == "system":
        user_lines = "User=ai-docs\nGroup=ai-docs\n"
        install_target = "multi-user.target"
    content = """[Unit]
Description=AI Docs Web publisher and MCP service
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
{user_lines}WorkingDirectory={workspace}
EnvironmentFile={credentials}
Environment=AI_DOCS_NODE={node}
ExecStart={python} {server} serve
Restart=on-failure
RestartSec=3s
TimeoutStopSec=30s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome={protect_home}
ReadOnlyPaths={runtime}{readonly_library}
ReadWritePaths={workspace} {writable_library}
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy={install_target}
""".format(
        user_lines=user_lines,
        workspace=_systemd_path(storage.workspace),
        credentials=_systemd_path(paths.credentials),
        node=_systemd_quote(node),
        python=_systemd_quote(_absolute(shutil.which("python3") or sys.executable)),
        server=_systemd_quote(paths.runtime / "source" / "ai_docs_web.py"),
        protect_home="true" if paths.scope == "system" else "read-only",
        runtime=_systemd_path(paths.runtime),
        readonly_library="" if storage.write_back else " " + _systemd_path(storage.library),
        writable_library=_systemd_path(storage.library if storage.write_back else storage.public),
        install_target=install_target,
    )
    return content.encode("utf-8")


def _connectable_host(host: str) -> Optional[str]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    return None if address.is_unspecified else host


def _service_origin(scheme: str, host: str, port: int) -> str:
    authority_host = "[{}]".format(host) if ":" in host else host
    default_port = 80 if scheme == "http" else 443
    authority = authority_host if port == default_port else "{}:{}".format(authority_host, port)
    return "{}://{}".format(scheme, authority)


def _resolve_node_executable(scope: str) -> Path:
    configured = shutil.which("node")
    if configured is None:
        raise ManagerError("node is unavailable; install Node.js 18+ before installing AI Docs Web")
    try:
        resolved = Path(configured).resolve(strict=True)
    except OSError as error:
        raise ManagerError("cannot resolve node executable: {}".format(error)) from error
    if resolved.is_symlink() or not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ManagerError("node must resolve to a regular executable file: {}".format(resolved))
    if scope == "system" and any(root == resolved or root in resolved.parents for root in (Path("/root"), Path("/home"), Path("/run/user"))):
        raise ManagerError("system scope requires a system-wide node executable outside home and user runtime directories")
    return resolved


def _configured_node_executable(paths: InstallPaths) -> Path:
    configured = _installed_node(paths)
    if configured is None:
        raise ManagerError("existing server configuration must define renderer.node")
    try:
        resolved = configured.resolve(strict=True)
    except OSError as error:
        raise ManagerError("configured renderer.node is unavailable: {}".format(error)) from error
    if resolved != configured or not configured.is_file() or not os.access(configured, os.X_OK):
        raise ManagerError("configured renderer.node must be a non-symlinked absolute executable file: {}".format(configured))
    if paths.scope == "system" and any(root == configured or root in configured.parents for root in (Path("/root"), Path("/home"), Path("/run/user"))):
        raise ManagerError("system scope requires renderer.node outside home and user runtime directories")
    return configured


def _default_config(
    paths: InstallPaths,
    host: str,
    port: int,
    endpoint: Dict[str, Any],
    node_executable: Path,
) -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "workspace_root": str(paths.workspace),
        "library_directory": str(paths.library),
        "public_directory": "public",
        "server": {
            "host": host,
            "port": port,
            "public": {
                "scheme": endpoint["public_scheme"],
                "host": endpoint["public_host"],
                "port": endpoint["public_port"],
            },
            "documents_prefix": "/docs/",
        },
        "preview": {
            "enabled": True,
            "path": "/preview",
            "write_back": True,
            "session_seconds": 43200,
        },
        "library_limits": {
            "max_files": 1000,
            "max_total_bytes": 50 * 1024 * 1024,
            "max_path_depth": 8,
        },
        "mcp": {
            "path": "/mcp",
            "reference": {
                "name": MCP_NAME,
                "scheme": endpoint["mcp_scheme"],
                "host": endpoint["mcp_host"],
                "port": endpoint["mcp_port"],
                "path": "/mcp",
                "timeout_ms": 30000,
                "token_env": TOKEN_ENV,
            },
        },
        "renderer": {"node": str(node_executable)},
        "max_upload_bytes": 5 * 1024 * 1024,
        "max_rpc_bytes": 6 * 1024 * 1024,
        "request_timeout_seconds": 60,
        "render_timeout_seconds": 120,
        "max_concurrent_renders": 2,
        "auth_required": True,
        "auth_token_env": TOKEN_ENV,
        "allowed_origins": [],
    }


def _validate_host(value: Any, label: str, *, connectable: bool) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManagerError("{} must be a non-empty hostname or IP address".format(label))
    host = value.strip()
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in host):
        raise ManagerError("{} contains invalid characters".format(label))
    if host.startswith("[") or host.endswith("]") or "://" in host or "/" in host:
        raise ManagerError("{} must not contain URL syntax or IPv6 brackets".format(label))
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if ":" in host or not HOSTNAME_PATTERN.fullmatch(host):
            raise ManagerError("{} must be a valid hostname, IPv4 address, or unbracketed IPv6 address".format(label))
    else:
        if connectable and address.is_unspecified:
            raise ManagerError("{} must be connectable and cannot be a wildcard address".format(label))
    return host


def _validate_port(value: Any, label: str) -> int:
    if type(value) is not int or value < 1 or value > 65535:
        raise ManagerError("{} must be an integer from 1 to 65535".format(label))
    return value


def _validate_scheme(value: Any, label: str) -> str:
    if value not in {"http", "https"}:
        raise ManagerError("{} must be http or https".format(label))
    return value


def _validate_install_arguments(args: argparse.Namespace) -> Dict[str, Any]:
    host = _validate_host(args.bind_host, "bind_host", connectable=False)
    port = _validate_port(args.port, "port")
    default_host = _connectable_host(host)
    public_host = args.public_host or default_host
    if public_host is None:
        raise ManagerError("--public-host is required when --bind-host is a wildcard address")
    public_host = _validate_host(public_host, "public_host", connectable=True)
    mcp_host = _validate_host(args.mcp_host or default_host or "127.0.0.1", "mcp_host", connectable=True)
    public_port = _validate_port(args.public_port if args.public_port is not None else port, "public_port")
    mcp_port = _validate_port(args.mcp_port if args.mcp_port is not None else port, "mcp_port")
    return {
        "bind_host": host,
        "port": port,
        "public_scheme": _validate_scheme(args.public_scheme, "public_scheme"),
        "public_host": public_host,
        "public_port": public_port,
        "mcp_scheme": _validate_scheme(args.mcp_scheme, "mcp_scheme"),
        "mcp_host": mcp_host,
        "mcp_port": mcp_port,
    }


def _validate_https_template_arguments(args: argparse.Namespace) -> Dict[str, Any]:
    if args.public_host is None:
        raise ManagerError("nginx-template requires --public-host")
    settings = {
        "public_scheme": _validate_scheme(args.public_scheme, "public_scheme"),
        "public_host": _validate_host(args.public_host, "public_host", connectable=True),
        "public_port": _validate_port(args.public_port if args.public_port is not None else 443, "public_port"),
    }
    if settings["public_scheme"] != "https":
        raise ManagerError("nginx-template requires --public-scheme https")
    return settings


def _ensure_scope(scope: str, writing: bool) -> None:
    if scope != "system" or not writing:
        return
    if os.geteuid() != 0:
        raise ManagerError("system scope writes require root; this manager never invokes sudo")
    try:
        pwd.getpwnam("ai-docs")
    except KeyError as error:
        raise ManagerError("system scope requires an existing service account named ai-docs") from error


def _copy_runtime(paths: InstallPaths, source_digest: str) -> Optional[Path]:
    _validate_parent_chain(paths.runtime, "runtime")
    paths.runtime.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ai-docs-web-runtime-", dir=str(paths.runtime.parent)))
    backup: Optional[Path] = None
    try:
        for relative, source in _runtime_sources().items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target, follow_symlinks=False)
            os.chmod(target, 0o755 if target.suffix in {".py", ".js"} and target.name in {"ai_docs_web.py", "build.js"} else 0o644)
        _write(temporary / "runtime-manifest.json", _json_bytes({
            "schema_version": 1,
            "version": VERSION,
            "source_digest": source_digest,
            "installed_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }), 0o644, "runtime manifest")
        for directory in sorted((path for path in temporary.rglob("*") if path.is_dir()), key=lambda item: len(item.parts), reverse=True):
            os.chmod(directory, 0o755)
        os.chmod(temporary, 0o755)
        if paths.runtime.exists() or paths.runtime.is_symlink():
            if paths.runtime.is_symlink() or not paths.runtime.is_dir():
                raise ManagerError("managed runtime target is not a regular directory: {}".format(paths.runtime))
            backup = paths.runtime.parent / (".ai-docs-web-runtime-backup-" + secrets.token_hex(8))
            os.replace(paths.runtime, backup)
        try:
            os.replace(temporary, paths.runtime)
        except OSError:
            if backup is not None and not paths.runtime.exists():
                os.replace(backup, paths.runtime)
                backup = None
            raise
        return backup
    except OSError as error:
        raise ManagerError("cannot install runtime: {}".format(error)) from error
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _credentials_values(path: Path) -> Dict[str, str]:
    raw = _read(path, "credentials")
    if raw is None:
        return {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ManagerError("credentials file must be UTF-8") from error
    values: Dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ManagerError("credentials file contains an invalid line")
        name, value = stripped.split("=", 1)
        if not ENVIRONMENT_NAME_PATTERN.fullmatch(name) or "\n" in value or "\r" in value:
            raise ManagerError("credentials file contains an invalid assignment")
        values[name] = value
    return values


def _create_directories(paths: InstallPaths, storage: StorageSettings) -> None:
    # Create public before starting the sandbox: a read-only library cannot
    # create its own writable mount point. Nested public directories need the
    # same service ownership in system scope. Existing custom roots are not
    # recursively chmod/chowned; their administrator retains ownership policy.
    public_chain = list(reversed(storage.public.relative_to(storage.library).parents))[1:]
    directories = [storage.workspace, storage.library]
    directories.extend(storage.library / relative for relative in public_chain)
    directories.append(storage.public)
    account = pwd.getpwnam("ai-docs") if paths.scope == "system" else None
    for directory in directories:
        _validate_parent_chain(directory, "managed directory")
        if directory.is_symlink():
            raise ManagerError("managed directory must not be a symlink: {}".format(directory))
        existed = directory.exists()
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not existed or directory in (paths.workspace, paths.library, paths.library / "public"):
            os.chmod(directory, 0o700)
            if account is not None:
                os.chown(directory, account.pw_uid, account.pw_gid)


def _prepare_system_parent_directories(paths: InstallPaths) -> None:
    if paths.scope != "system":
        return
    account = pwd.getpwnam("ai-docs")
    specifications = (
        (paths.runtime.parent, 0, 0, 0o755),
        (paths.workspace.parent, 0, account.pw_gid, 0o750),
        (paths.library.parent, 0, account.pw_gid, 0o750),
        (paths.state.parent, 0, 0, 0o700),
    )
    for directory, uid, gid, mode in specifications:
        _validate_parent_chain(directory, "system managed parent directory")
        if directory.is_symlink():
            raise ManagerError("system managed parent directory must not be a symlink: {}".format(directory))
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, uid, gid)
        os.chmod(directory, mode)


def _apply_system_config_permissions(paths: InstallPaths) -> None:
    if paths.scope != "system":
        return
    account = pwd.getpwnam("ai-docs")
    config_directory = paths.config.parent
    if config_directory.is_symlink() or not config_directory.is_dir():
        raise ManagerError("system configuration directory is unsafe: {}".format(config_directory))
    os.chown(config_directory, 0, account.pw_gid)
    os.chmod(config_directory, 0o750)
    for path in (paths.config, paths.credentials):
        if path.is_symlink() or not path.is_file():
            raise ManagerError("system configuration file is unsafe: {}".format(path))
        os.chown(path, 0, account.pw_gid)
        os.chmod(path, 0o640)


def _migrate_server_config(raw: bytes) -> Optional[Dict[str, Any]]:
    """Return the schema v2 rewrite of a v1 configuration, or None if current.

    The pure mapping lives in the runtime source (ai_docs_config.migrate_config_v1);
    this wrapper owns the manager-facing error translation only. Backups, the
    non-empty public/ safety check, and the atomic write stay in _install.
    """
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ManagerError("server configuration is not valid JSON: {}".format(error)) from error
    if not isinstance(value, dict):
        raise ManagerError("server configuration must be a JSON object")
    removed = [field for field in ("documents_directory", "static_directory", "metadata_directory") if field in value]
    if value.get("schema_version") == 2:
        if removed:
            raise ManagerError(
                "server configuration mixes schema v2 with removed v1 fields: {}; remove them manually".format(", ".join(removed))
            )
        return None
    source_dir = skill_root() / "web-mcp" / "source"
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))
    from ai_docs_common import ServiceError as ConfigError  # noqa: PLC0415
    from ai_docs_config import migrate_config_v1  # noqa: PLC0415
    try:
        return migrate_config_v1(value)
    except ConfigError as error:
        raise ManagerError("cannot migrate schema v1 configuration: {}".format(error.message)) from error


def _install(paths: InstallPaths, args: argparse.Namespace) -> Dict[str, Any]:
    _ensure_scope(paths.scope, True)
    _prepare_system_parent_directories(paths)
    endpoint = _validate_install_arguments(args)
    before_config = _read(paths.config, "server configuration")
    node_executable = _resolve_node_executable(paths.scope) if before_config is None else _configured_node_executable(paths)
    source_digest = _source_digest()
    state = _read_state(paths.state)
    managed = _valid_state(state, paths)
    installed_digest = _installed_digest(paths.runtime)
    manifest = _runtime_manifest(paths.runtime) if paths.runtime.is_dir() and not paths.runtime.is_symlink() else None
    runtime_owned = bool(
        manifest
        and manifest.get("schema_version") == 1
        and manifest.get("version") == VERSION
        and isinstance(manifest.get("source_digest"), str)
        and manifest.get("source_digest") == installed_digest
    )
    if paths.runtime.exists() and not (managed or runtime_owned):
        raise ManagerError("runtime exists without matching managed state or ownership; refusing to overwrite: {}".format(paths.runtime))
    migrated = _migrate_server_config(before_config) if before_config is not None else None
    desired_config = migrated if migrated is not None else (
        json.loads(before_config) if before_config is not None else
        _default_config(paths, endpoint["bind_host"], endpoint["port"], endpoint, node_executable)
    )
    storage = _storage_settings(paths, desired_config)
    if migrated is not None and storage.public.is_dir() and any(
        path.is_file() and not path.is_symlink() and path.suffix.lower() in {".md", ".markdown", ".txt"}
        for path in storage.public.rglob("*")
    ):
        raise ManagerError(
            "schema v2 migration would publish existing Markdown under {}; "
            "review and clear it, then re-run the upgrade".format(storage.public)
        )
    unit = _unit_content(paths, node_executable, storage)
    before_credentials = _read(paths.credentials, "credentials")
    current_unit = _read(paths.unit, "systemd unit")
    before_state = _read(paths.state, "managed install state")
    runtime_matches_state = bool(
        managed
        and installed_digest is not None
        and hmac.compare_digest(installed_digest, state["source_digest"])
    )
    unit_matches_state = bool(
        managed
        and current_unit is not None
        and hmac.compare_digest(_sha256(current_unit), state["unit_sha256"])
    )
    if managed and paths.runtime.exists() and not (runtime_matches_state or installed_digest == source_digest):
        raise ManagerError("managed runtime has drifted; refusing to overwrite local changes: {}".format(paths.runtime))
    if current_unit is not None and current_unit != unit and not unit_matches_state:
        raise ManagerError("systemd unit is unmanaged or has drifted; refusing to overwrite: {}".format(paths.unit))
    changed: List[str] = []
    backup: Optional[Path] = None
    config_backup_path = paths.config.with_name(paths.config.name + ".v1-backup")
    config_backup_touched = False
    config_backup_before: Optional[bytes] = None
    runtime_changed = installed_digest != source_digest
    if runtime_changed:
        backup = _copy_runtime(paths, source_digest)
        changed.append("runtime")
    try:
        _create_directories(paths, storage)
        if before_config is None:
            _write(
                paths.config,
                _json_bytes(desired_config),
                0o600,
                "server configuration",
            )
            changed.append("config")
        else:
            if migrated is not None:
                # 迁移失败回滚时需要把 backup 还原到迁移前状态（删除或恢复旧内容），
                # 否则残留的 backup 看似来自一次成功迁移，原子性不成立。
                try:
                    config_backup_before = config_backup_path.read_bytes()
                except FileNotFoundError:
                    config_backup_before = None
                config_backup_touched = True
                _write(
                    config_backup_path,
                    before_config,
                    0o600,
                    "v1 configuration backup",
                )
                _write(paths.config, _json_bytes(migrated), 0o600, "server configuration")
                changed.append("config_migration")
        if before_credentials is None:
            token = secrets.token_urlsafe(48)
            content = "{}={}\n{}={}\n".format(CONFIG_ENV, paths.config, TOKEN_ENV, token).encode("utf-8")
            _write(paths.credentials, content, 0o600, "credentials")
            changed.append("credentials")
        _apply_system_config_permissions(paths)
        credentials = _credentials_values(paths.credentials)
        if credentials.get(CONFIG_ENV) != str(paths.config) or not credentials.get(TOKEN_ENV):
            raise ManagerError("credentials must define {}={} and a non-empty {}".format(CONFIG_ENV, paths.config, TOKEN_ENV))
        if paths.scope == "user":
            for path, label in ((paths.config, "server configuration"), (paths.credentials, "credentials")):
                if path.stat().st_mode & 0o077:
                    os.chmod(path, 0o600)
                    changed.append(label + "_permissions")
        if current_unit != unit:
            _write(paths.unit, unit, 0o644, "systemd unit")
            changed.append("systemd_unit")
        _write(paths.state, _json_bytes({
            "schema_version": 1,
            "scope": paths.scope,
            "version": VERSION,
            "runtime": str(paths.runtime),
            "config": str(paths.config),
            "credentials": str(paths.credentials),
            "unit": str(paths.unit),
            "source_digest": source_digest,
            "unit_sha256": _sha256(unit),
        }), 0o600, "managed install state")
    except Exception as original_error:
        rollback_errors: List[str] = []
        if runtime_changed and paths.runtime.exists() and not paths.runtime.is_symlink():
            shutil.rmtree(paths.runtime, ignore_errors=True)
        if backup is not None:
            try:
                os.replace(backup, paths.runtime)
                backup = None
            except OSError as rollback_error:
                rollback_errors.append("runtime: {}".format(rollback_error))
        for path, content, mode, label in (
            (paths.config, before_config, 0o600, "server configuration"),
            (paths.credentials, before_credentials, 0o600, "credentials"),
            (paths.unit, current_unit, 0o644, "systemd unit"),
            (paths.state, before_state, 0o600, "managed install state"),
        ):
            try:
                _restore_file(path, content, mode, label)
            except ManagerError as rollback_error:
                rollback_errors.append(str(rollback_error))
        if config_backup_touched:
            try:
                _restore_file(config_backup_path, config_backup_before, 0o600, "v1 configuration backup")
            except ManagerError as rollback_error:
                rollback_errors.append(str(rollback_error))
        if paths.scope == "system" and before_config is not None and before_credentials is not None:
            try:
                _apply_system_config_permissions(paths)
            except (ManagerError, OSError) as rollback_error:
                rollback_errors.append("system configuration permissions: {}".format(rollback_error))
        if rollback_errors:
            raise ManagerError("install failed ({}) and rollback was incomplete: {}".format(original_error, "; ".join(rollback_errors))) from original_error
        raise
    finally:
        if backup is not None and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    return {
        "ok": True,
        "status": "changed" if changed else "current",
        "changed": changed,
        "paths": _describe_paths(paths),
        "next": [
            "Run '{} doctor --scope {}'".format(Path(__file__).name, paths.scope),
            "Run '{} start --scope {}' to enable the service".format(Path(__file__).name, paths.scope),
            "Run '{} register --scope {} --host opencode' after making {} available to OpenCode".format(Path(__file__).name, paths.scope, TOKEN_ENV),
        ],
    }


def _describe_paths(paths: InstallPaths) -> Dict[str, str]:
    storage = _storage_settings(paths)
    return {
        "runtime": str(paths.runtime),
        "config": str(paths.config),
        "credentials": str(paths.credentials),
        "library": str(storage.library),
        "public": str(storage.public),
        "workspace": str(storage.workspace),
        "state": str(paths.state),
        "systemd_unit": str(paths.unit),
        "opencode_config": str(paths.opencode_config),
        "nginx_output": str(paths.nginx_output),
    }


def _user_file_is_private(paths: InstallPaths, path: Path) -> bool:
    if paths.scope != "user":
        return True
    return path.is_file() and not path.is_symlink() and not (path.stat().st_mode & 0o077)


def _status(paths: InstallPaths) -> Dict[str, Any]:
    source_digest = _source_digest()
    state = _read_state(paths.state)
    unit = _read(paths.unit, "systemd unit")
    credentials = _credentials_values(paths.credentials) if paths.credentials.exists() else {}
    details = {
        "managed_state": _valid_state(state, paths),
        "runtime_current": _installed_digest(paths.runtime) == source_digest,
        "config_present": paths.config.is_file() and not paths.config.is_symlink(),
        "credentials_present": bool(credentials.get(TOKEN_ENV)) and credentials.get(CONFIG_ENV) == str(paths.config),
        "config_permissions_private": _user_file_is_private(paths, paths.config),
        "credentials_permissions_private": _user_file_is_private(paths, paths.credentials),
        "unit_current": unit == _unit_content(paths),
        "paths": _describe_paths(paths),
    }
    current = all(details[key] for key in (
        "managed_state", "runtime_current", "config_present", "credentials_present",
        "config_permissions_private", "credentials_permissions_private", "unit_current",
    ))
    return {"ok": True, "status": "current" if current else "not-installed-or-drifted", "details": details}


def _service_command(paths: InstallPaths, action: str) -> Dict[str, Any]:
    _ensure_scope(paths.scope, True)
    if not _valid_state(_read_state(paths.state), paths):
        raise ManagerError("AI Docs Web is not installed with matching managed state")
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        raise ManagerError("systemctl is unavailable")
    prefix = [systemctl] + (["--user"] if paths.scope == "user" else [])
    commands = [prefix + ["daemon-reload"]]
    if action == "start":
        commands.append(prefix + ["enable", "--now", "ai-docs-web.service"])
    elif action == "stop":
        commands.append(prefix + ["disable", "--now", "ai-docs-web.service"])
    else:
        commands.append(prefix + ["restart", "ai-docs-web.service"])
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if completed.returncode != 0:
            raise ManagerError("service command failed: {}".format((completed.stderr or completed.stdout).strip()))
    return {"ok": True, "status": action + "ed" if action != "stop" else "stopped", "unit": str(paths.unit)}


def _systemctl(paths: InstallPaths, arguments: Sequence[str], *, tolerate_absent: bool = False) -> None:
    executable = shutil.which("systemctl")
    if executable is None:
        if tolerate_absent:
            return
        raise ManagerError("systemctl is unavailable")
    command = [executable] + (["--user"] if paths.scope == "user" else []) + list(arguments)
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        if tolerate_absent and any(marker in detail.lower() for marker in ("not loaded", "not found", "does not exist")):
            return
        raise ManagerError("systemctl {} failed: {}".format(" ".join(arguments), detail or completed.returncode))


def _systemctl_state(paths: InstallPaths, check: str) -> bool:
    executable = shutil.which("systemctl")
    if executable is None:
        return False
    command = [executable] + (["--user"] if paths.scope == "user" else []) + [check, "ai-docs-web.service"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if completed.returncode == 0:
        return True
    output = (completed.stdout + "\n" + completed.stderr).strip().lower()
    if check == "is-enabled" and output in {"disabled", "static", "indirect", "masked", "not-found"}:
        return False
    if check == "is-active" and output in {"inactive", "failed", "unknown", "deactivating"}:
        return False
    raise ManagerError("systemctl {} failed: {}".format(check, (completed.stderr or completed.stdout).strip() or completed.returncode))


def _restore_systemd_state(paths: InstallPaths, was_enabled: bool, was_active: bool) -> None:
    _systemctl(paths, ["daemon-reload"], tolerate_absent=True)
    if was_enabled:
        _systemctl(paths, ["enable", "ai-docs-web.service"])
    if was_active:
        _systemctl(paths, ["start", "ai-docs-web.service"])


def _doctor(paths: InstallPaths) -> Dict[str, Any]:
    if not _user_file_is_private(paths, paths.config):
        raise ManagerError("server configuration permissions are not private; run install to repair them")
    if not _user_file_is_private(paths, paths.credentials):
        raise ManagerError("credentials permissions are not private; run install to repair them")
    server = paths.runtime / "source" / "ai_docs_web.py"
    if server.is_symlink() or not server.is_file():
        raise ManagerError("installed server is unavailable: {}".format(server))
    environment = dict(os.environ)
    environment.update(_credentials_values(paths.credentials))
    completed = subprocess.run(
        [sys.executable, str(server), "doctor", "--json"],
        cwd=str(_storage_settings(paths).workspace), env=environment, capture_output=True, text=True, timeout=30, check=False,
    )
    try:
        payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
    except ValueError:
        payload = {}
    if completed.returncode != 0:
        raise ManagerError("doctor failed: {}".format((completed.stderr or completed.stdout).strip()))
    return payload


def _server_reference(paths: InstallPaths) -> Dict[str, Any]:
    config, raw = _json_object(paths.config, "server configuration")
    if raw is None:
        raise ManagerError("server configuration does not exist: {}".format(paths.config))
    mcp = config.get("mcp", {})
    server = config.get("server", {})
    if not isinstance(mcp, dict) or not isinstance(server, dict):
        raise ManagerError("server and mcp configuration sections must be objects")
    reference = mcp.get("reference", {})
    if not isinstance(reference, dict):
        raise ManagerError("mcp.reference must be an object")
    name = reference.get("name", MCP_NAME)
    token_env = reference.get("token_env", config.get("auth_token_env", TOKEN_ENV))
    timeout = reference.get("timeout_ms", 30000)
    scheme = _validate_scheme(reference.get("scheme"), "mcp.reference.scheme")
    host = _validate_host(reference.get("host"), "mcp.reference.host", connectable=True)
    port = _validate_port(reference.get("port"), "mcp.reference.port")
    path = reference.get("path", mcp.get("path", "/mcp"))
    if not isinstance(path, str) or not URL_PATH_PATTERN.fullmatch(path) or path == "/" or ".." in path:
        raise ManagerError("mcp.reference.path must be a non-root local URL path")
    path = "/" + path.strip("/")
    url = _service_origin(scheme, host, port) + path
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 128:
        raise ManagerError("mcp.reference.name must be a short non-empty string")
    if type(timeout) is not int or timeout < 1000 or timeout > 300000:
        raise ManagerError("mcp.reference.timeout_ms must be between 1000 and 300000")
    if not isinstance(token_env, str) or not ENVIRONMENT_NAME_PATTERN.fullmatch(token_env):
        raise ManagerError("mcp.reference.token_env must be an environment variable name")
    return {
        "name": name.strip(), "scheme": scheme, "host": host, "port": port, "path": path,
        "url": url, "timeout_ms": timeout, "token_env": token_env,
    }


def _mcp_entry(reference: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "remote",
        "url": reference["url"],
        "enabled": True,
        "oauth": False,
        "timeout": reference["timeout_ms"],
        "headers": {"Authorization": "Bearer {env:" + reference["token_env"] + "}"},
    }


def _registration_state(paths: InstallPaths) -> Optional[Dict[str, Any]]:
    value, raw = _json_object(paths.opencode_state, "OpenCode registration state")
    return value if raw is not None else None


def _backup(path: Path, raw: Optional[bytes], paths: InstallPaths) -> Optional[Path]:
    if raw is None:
        return None
    backup_root = paths.opencode_state.parent / "backups"
    backup_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_root / (path.name + "." + timestamp + "." + secrets.token_hex(4) + ".bak")
    _write(target, raw, 0o600, "OpenCode configuration backup")
    return target


def _opencode_backup_root(paths: InstallPaths) -> Path:
    return paths.opencode_state.parent / "backups"


def _register_opencode(paths: InstallPaths) -> Dict[str, Any]:
    reference = _server_reference(paths)
    desired = _mcp_entry(reference)
    config, before = _json_object(paths.opencode_config, "OpenCode configuration")
    section = config.get("mcp", {})
    if not isinstance(section, dict):
        raise ManagerError("OpenCode mcp section must be an object")
    entry_name = reference["name"]
    entry_present = entry_name in section
    current = section.get(entry_name)
    state = _registration_state(paths)
    if state:
        if state.get("schema_version") != 1 or state.get("config") != str(paths.opencode_config):
            raise ManagerError("OpenCode registration state is invalid or belongs to another configuration")
        if state.get("entry_name") != reference["name"]:
            raise ManagerError("OpenCode registration name changed; unregister the previous managed entry before registering {}".format(reference["name"]))
    managed = bool(
        isinstance(current, dict)
        and state
        and state.get("schema_version") == 1
        and state.get("config") == str(paths.opencode_config)
        and state.get("entry_name") == reference["name"]
        and isinstance(state.get("entry_sha256"), str)
        and hmac.compare_digest(state["entry_sha256"], _sha256(_json_bytes(current)))
    )
    before_state = _read(paths.opencode_state, "OpenCode registration state")
    if current == desired and managed:
        status = "current"
    elif entry_present and not managed:
        raise ManagerError("OpenCode already has an unmanaged {} entry; refusing to overwrite".format(reference["name"]))
    else:
        updated = dict(config)
        updated.setdefault("$schema", "https://opencode.ai/config.json")
        updated_section = dict(section)
        updated_section[reference["name"]] = desired
        updated["mcp"] = updated_section
        _backup(paths.opencode_config, before, paths)
        _write(paths.opencode_config, _json_bytes(updated), 0o600, "OpenCode configuration")
        status = "changed"
    try:
        _write(paths.opencode_state, _json_bytes({
            "schema_version": 1,
            "config": str(paths.opencode_config),
            "entry_name": reference["name"],
            "entry_sha256": _sha256(_json_bytes(desired)),
        }), 0o600, "OpenCode registration state")
    except ManagerError as original_error:
        rollback_errors: List[str] = []
        if status == "changed":
            try:
                _restore_file(paths.opencode_config, before, 0o600, "OpenCode configuration")
            except ManagerError as rollback_error:
                rollback_errors.append(str(rollback_error))
        try:
            _restore_file(paths.opencode_state, before_state, 0o600, "OpenCode registration state")
        except ManagerError as rollback_error:
            rollback_errors.append(str(rollback_error))
        if rollback_errors:
            raise ManagerError("registration failed ({}) and rollback was incomplete: {}".format(original_error, "; ".join(rollback_errors))) from original_error
        raise
    return {
        "ok": True,
        "status": status,
        "host": "opencode",
        "entry_name": reference["name"],
        "url": reference["url"],
        "token_environment": reference["token_env"],
        "warning": "The token value is not copied into OpenCode config; launch OpenCode with the named environment variable available.",
    }


def _unregister_opencode(paths: InstallPaths) -> Dict[str, Any]:
    state = _registration_state(paths)
    if not state:
        return {"ok": True, "status": "absent", "host": "opencode"}
    if state.get("schema_version") != 1 or state.get("config") != str(paths.opencode_config):
        raise ManagerError("OpenCode registration state is invalid or belongs to another configuration")
    config, before = _json_object(paths.opencode_config, "OpenCode configuration")
    section = config.get("mcp", {})
    if not isinstance(section, dict):
        raise ManagerError("OpenCode mcp section must be an object")
    name = state.get("entry_name")
    current = section.get(name)
    expected = state.get("entry_sha256")
    if current is not None and (not isinstance(current, dict) or not isinstance(expected, str) or not hmac.compare_digest(_sha256(_json_bytes(current)), expected)):
        raise ManagerError("managed OpenCode entry has drifted; refusing to remove it")
    before_state = _read(paths.opencode_state, "OpenCode registration state")
    if current is not None:
        updated = dict(config)
        updated_section = dict(section)
        del updated_section[name]
        if updated_section:
            updated["mcp"] = updated_section
        else:
            updated.pop("mcp", None)
        _backup(paths.opencode_config, before, paths)
        _write(paths.opencode_config, _json_bytes(updated), 0o600, "OpenCode configuration")
    try:
        paths.opencode_state.unlink()
    except FileNotFoundError:
        pass
    except OSError as original_error:
        rollback_errors: List[str] = []
        if current is not None:
            try:
                _restore_file(paths.opencode_config, before, 0o600, "OpenCode configuration")
            except ManagerError as rollback_error:
                rollback_errors.append(str(rollback_error))
        try:
            _restore_file(paths.opencode_state, before_state, 0o600, "OpenCode registration state")
        except ManagerError as rollback_error:
            rollback_errors.append(str(rollback_error))
        if rollback_errors:
            raise ManagerError("unregister failed ({}) and rollback was incomplete: {}".format(original_error, "; ".join(rollback_errors))) from original_error
        raise ManagerError("cannot remove OpenCode registration state: {}".format(original_error)) from original_error
    return {"ok": True, "status": "changed" if current is not None else "absent", "host": "opencode"}


def _normalized_nginx_prefix(value: Any, label: str, default_value: str) -> str:
    if value is None:
        return default_value
    if not isinstance(value, str) or not URL_PATH_PATTERN.fullmatch(value) or value == "/" or ".." in value:
        raise ManagerError("{} must be a non-root local URL path".format(label))
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or parsed.params or parsed.query or parsed.fragment:
        raise ManagerError("{} must not contain a URL origin, query, or fragment".format(label))
    return "/" + value.strip("/") + "/"


def _nginx_server_settings(paths: InstallPaths) -> Tuple[str, int, str]:
    config, raw = _json_object(paths.config, "server configuration")
    if raw is None:
        return "127.0.0.1", 18080, "/docs/"
    server = config.get("server", {})
    if not isinstance(server, dict):
        raise ManagerError("server configuration section must be an object")
    host = _validate_host(server.get("host", "127.0.0.1"), "server.host", connectable=False)
    port = server.get("port", 18080)
    if type(port) is not int or port < 1 or port > 65535:
        raise ManagerError("server.port must be an integer from 1 to 65535 for the Nginx template")
    documents_prefix = _normalized_nginx_prefix(server.get("documents_prefix"), "server.documents_prefix", "/docs/")
    backend_host = "127.0.0.1" if host == "0.0.0.0" else "::1" if host == "::" else host
    backend_authority = "[{}]".format(backend_host) if ":" in backend_host else backend_host
    return backend_authority, port, documents_prefix


def _nginx_preview_settings(paths: InstallPaths) -> Tuple[bool, str]:
    config, raw = _json_object(paths.config, "server configuration")
    if raw is None:
        return False, "/preview/"
    preview = config.get("preview", {})
    if not isinstance(preview, dict):
        raise ManagerError("preview configuration section must be an object")
    enabled = preview.get("enabled", False)
    if type(enabled) is not bool:
        raise ManagerError("preview.enabled must be boolean")
    prefix = _normalized_nginx_prefix(preview.get("path"), "preview.path", "/preview/")
    return enabled, prefix


def _nginx_template(paths: InstallPaths, public_settings: Dict[str, Any], expose_mcp: bool = False, expose_preview: bool = False) -> str:
    backend_host, port, documents_prefix = _nginx_server_settings(paths)
    preview_enabled, preview_prefix = _nginx_preview_settings(paths)
    if expose_preview and not preview_enabled:
        raise ManagerError("--expose-preview requires backend preview.enabled=true")
    preview_enabled = preview_enabled and expose_preview
    config, _ = _json_object(paths.config, "server configuration")
    proxy_login = config.get("preview", {}).get("login_mode", "token") == "proxy"
    if preview_enabled and not proxy_login:
        # token 登录页会显式发送 Authorization: Bearer，与 Basic Auth 共用同一请求头，
        # 生成的 auth_basic 块会在后端签发会话之前拒绝登录请求，公网预览必然无法登录。
        raise ManagerError(
            '--expose-preview requires preview.login_mode="proxy": with the default "token" login '
            "mode the login page sends Authorization: Bearer, which the generated Nginx Basic Auth "
            'block rejects. Set preview.login_mode to "proxy" before exposing the preview publicly.'
        )
    listen_port = public_settings["public_port"]
    if preview_enabled:
        preview_block = """
    location ^~ %(preview_prefix)s {
        auth_basic "AI Docs preview";
        auth_basic_user_file /etc/nginx/ai-docs-preview.htpasswd;
        proxy_pass http://%(backend_host)s:%(port)s;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 120s;
        client_max_body_size 8m;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Cache-Control "no-store" always;
        add_header X-Robots-Tag "noindex, nofollow" always;
    }
""" % {
            "preview_prefix": preview_prefix,
            "backend_host": backend_host,
            "port": port,
        }
    else:
        preview_block = "\n    location = %s { return 404; }\n    location ^~ %s { return 404; }\n" % (preview_prefix.rstrip("/"), preview_prefix)
    if preview_enabled and proxy_login:
        origin = _service_origin(public_settings["public_scheme"], public_settings["public_host"], public_settings["public_port"])
        preview_block = preview_block.replace('proxy_set_header Host $host;', 'proxy_set_header Host $host;\n        proxy_set_header Authorization "";')
        preview_block += '''
    # Create this root-owned 0600 include separately; never commit its token.
    # Content: proxy_set_header Authorization "Bearer <actual-token>";
    location = %(prefix)ssession {
        auth_basic "AI Docs preview";
        auth_basic_user_file /etc/nginx/ai-docs-preview.htpasswd;
        if ($request_method != POST) { return 405; }
        if ($http_origin != "%(origin)s") { return 403; }
        proxy_pass http://%(host)s:%(port)s;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        include /etc/nginx/ai-docs-session-auth.inc;
        add_header Cache-Control "no-store, private" always;
    }
''' % {"prefix": preview_prefix, "origin": origin, "host": backend_host, "port": port}
    # MCP 路径与公共渲染超时跟随后端配置：自定义 mcp.path 或更长的
    # public_docs.render_timeout_seconds 不应生成必然 404 或被 Nginx 先行中断的模板。
    mcp_path = config.get("mcp", {}).get("path", "/mcp")
    if not isinstance(mcp_path, str) or not re.fullmatch(r"/[A-Za-z0-9._~/-]*", mcp_path):
        raise ManagerError("mcp.path is missing or contains characters unsafe for an Nginx location: {!r}".format(mcp_path))
    try:
        docs_render_timeout = int(config.get("public_docs", {}).get("render_timeout_seconds", 30))
    except (TypeError, ValueError):
        raise ManagerError("public_docs.render_timeout_seconds must be an integer number of seconds")
    if not 1 <= docs_render_timeout <= 300:
        raise ManagerError("public_docs.render_timeout_seconds must be between 1 and 300 seconds")
    # 代理读超时在后端冷渲染超时之上保留 15 秒，覆盖代理与连接开销。
    docs_proxy_read_timeout = docs_render_timeout + 15
    if expose_mcp:
        # Per-IP request limiting keeps the public render endpoint from being
        # used as a free rendering farm; the backend still enforces the Bearer
        # token, request size caps and the render concurrency semaphore.
        mcp_rate_limit = "limit_req_zone $binary_remote_addr zone=ai_docs_mcp:10m rate=30r/m;\n"
        mcp_block = """
    # Public MCP endpoint. The backend validates the Bearer token itself, so
    # Authorization must pass through untouched; never inject or strip it here.
    location = %(mcp_path)s {
        limit_req zone=ai_docs_mcp burst=10;
        proxy_pass http://%(backend_host)s:%(port)s;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-AI-Docs-Token "";
        proxy_set_header Forwarded "";
        proxy_connect_timeout 5s;
        proxy_send_timeout 130s;
        proxy_read_timeout 130s;
        client_max_body_size 8m;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Cache-Control "no-store" always;
        add_header X-Robots-Tag "noindex, nofollow" always;
    }
""" % {"mcp_path": mcp_path, "backend_host": backend_host, "port": port}
    else:
        mcp_rate_limit = ""
        mcp_block = "\n    location = %s { return 404; }\n" % (mcp_path,)
    # The docs tree is rendered live by the backend, so it must stay dynamic:
    # no immutable caching, no static file alias, and a per-IP request limit
    # that absorbs cold-render bursts without becoming a free rendering farm.
    rate_limit_preamble = (
        "limit_req_zone $binary_remote_addr zone=ai_docs_docs:10m rate=120r/m;\n"
        + mcp_rate_limit
        + "limit_req_status 429;\n\n"
    )
    return """# Generated template only. Review certificate paths before enabling it.
%(rate_limit_preamble)sserver {
    listen %(listen_port)s ssl http2;
    server_name %(host)s;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location ^~ %(documents_prefix)s {
        limit_req zone=ai_docs_docs burst=40;
        proxy_pass http://%(backend_host)s:%(port)s;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout %(docs_proxy_read_timeout)ss;
        add_header X-Content-Type-Options "nosniff" always;
    }

    # Renderer assets (/assets/<fingerprint>/<file>): manifest-whitelisted vendor
    # files only, served read-only by the backend with immutable caching.
    location ^~ /assets/ {
        proxy_pass http://%(backend_host)s:%(port)s;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
%(preview_block)s%(mcp_block)s    location ^~ /v1/ { return 404; }
    location = /healthz { return 404; }
    location / { return 404; }
}
""" % {
        "host": public_settings["public_host"],
        "backend_host": backend_host,
        "port": port,
        "listen_port": listen_port,
        "documents_prefix": documents_prefix,
        "preview_block": preview_block,
        "mcp_block": mcp_block,
        "rate_limit_preamble": rate_limit_preamble,
        "docs_proxy_read_timeout": docs_proxy_read_timeout,
    }


def _write_nginx_template(paths: InstallPaths, public_settings: Dict[str, Any], output: Optional[str], expose_mcp: bool = False, expose_preview: bool = False) -> Dict[str, Any]:
    target = _absolute(output) if output else paths.nginx_output
    if paths.scope == "system" and target == paths.nginx_output:
        raise ManagerError("system scope does not write Nginx configuration automatically; pass --output to a review location")
    content = _nginx_template(paths, public_settings, expose_mcp, expose_preview).encode("utf-8")
    current = _read(target, "Nginx template")
    if current is not None and current != content:
        raise ManagerError("Nginx template target already exists with different content: {}".format(target))
    if current is None:
        _write(target, content, 0o600, "Nginx template")
    return {"ok": True, "status": "current" if current == content else "changed", "output": str(target)}


def _uninstall(paths: InstallPaths, purge: bool) -> Dict[str, Any]:
    _ensure_scope(paths.scope, True)
    state = _read_state(paths.state)
    if not _valid_state(state, paths):
        raise ManagerError("matching managed install state is required for uninstall")
    installed_digest = _installed_digest(paths.runtime)
    if installed_digest is None or not hmac.compare_digest(installed_digest, state["source_digest"]):
        raise ManagerError("managed runtime has drifted; refusing to uninstall local changes: {}".format(paths.runtime))
    current_unit = _read(paths.unit, "systemd unit")
    if current_unit is None or not hmac.compare_digest(_sha256(current_unit), state["unit_sha256"]):
        raise ManagerError("managed systemd unit has drifted; refusing to uninstall local changes: {}".format(paths.unit))
    removal_targets = [paths.unit, paths.runtime, paths.state]
    if purge:
        removal_targets.extend((
            paths.config, paths.credentials, paths.documents, paths.static, paths.metadata, paths.library,
            paths.workspace, _opencode_backup_root(paths),
        ))
    for target in removal_targets:
        _validate_parent_chain(target, "uninstall target")
        if target.is_symlink():
            raise ManagerError("refusing to remove symlinked managed target: {}".format(target))
    backup_root = paths.state.parent / ("uninstall-backup-" + secrets.token_hex(8))
    backup_root.mkdir(parents=True, mode=0o700)
    was_enabled = _systemctl_state(paths, "is-enabled")
    was_active = _systemctl_state(paths, "is-active")
    moved: List[Tuple[Path, Path]] = []
    try:
        _systemctl(paths, ["disable", "--now", "ai-docs-web.service"], tolerate_absent=True)
        for target in (paths.unit, paths.runtime):
            if target.exists():
                backup = backup_root / ("unit" if target == paths.unit else "runtime")
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
                moved.append((target, backup))
        _systemctl(paths, ["daemon-reload"], tolerate_absent=True)
        if paths.opencode_state.exists():
            _unregister_opencode(paths)
    except Exception as original_error:
        rollback_errors: List[str] = []
        for target, backup in reversed(moved):
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
            except OSError as rollback_error:
                rollback_errors.append("{}: {}".format(target, rollback_error))
        try:
            _restore_systemd_state(paths, was_enabled, was_active)
        except ManagerError as rollback_error:
            rollback_errors.append("service state: {}".format(rollback_error))
        shutil.rmtree(backup_root, ignore_errors=True)
        if rollback_errors:
            raise ManagerError("uninstall failed ({}) and rollback was incomplete: {}".format(original_error, "; ".join(rollback_errors))) from original_error
        raise
    shutil.rmtree(backup_root, ignore_errors=True)
    removed = ["unit", "runtime", "state"]
    if purge:
        for target in (
            paths.config, paths.credentials, paths.documents, paths.static, paths.metadata, paths.library,
            paths.workspace, _opencode_backup_root(paths),
        ):
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        removed.append("persistent-data")
    if paths.state.exists():
        paths.state.unlink()
    return {"ok": True, "status": "changed", "removed": removed, "purged": purge}


def _plan(paths: InstallPaths, args: argparse.Namespace) -> Dict[str, Any]:
    endpoint = _validate_install_arguments(args)
    node_executable = _resolve_node_executable(paths.scope)
    return {
        "ok": True,
        "status": "planned",
        "scope": paths.scope,
        "paths": _describe_paths(paths),
        "defaults": {
            "host": endpoint["bind_host"],
            "port": endpoint["port"],
            "public": {
                "scheme": endpoint["public_scheme"],
                "host": endpoint["public_host"],
                "port": endpoint["public_port"],
                "origin": _service_origin(endpoint["public_scheme"], endpoint["public_host"], endpoint["public_port"]),
            },
            "mcp": {
                "scheme": endpoint["mcp_scheme"],
                "host": endpoint["mcp_host"],
                "port": endpoint["mcp_port"],
                "url": _service_origin(endpoint["mcp_scheme"], endpoint["mcp_host"], endpoint["mcp_port"]) + "/mcp",
            },
            "node": str(node_executable),
            "auth_required": True,
        },
        "writes": ["runtime", "server configuration", "credentials", "systemd unit", "managed state"],
        "does_not": ["start the service", "register a Host", "write Nginx configuration", "open firewall ports", "request TLS certificates"],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="web-mcp-manager.py")
    parser.add_argument("action", choices=(
        "plan", "install", "upgrade", "status", "doctor", "start", "stop", "restart",
        "register", "unregister", "nginx-template", "uninstall",
    ))
    parser.add_argument("--scope", choices=("user", "system"), default="user")
    parser.add_argument("--bind-host", default="127.0.0.1", help="bind address used when creating a new configuration")
    parser.add_argument("--port", type=int, default=18080, help="port used when creating a new configuration")
    parser.add_argument("--public-scheme", choices=("http", "https"), default="http", help="scheme used in published document URLs")
    parser.add_argument("--public-host", help="host used in published document URLs; defaults to a connectable bind host")
    parser.add_argument("--public-port", type=int, help="port used in published document URLs; defaults to --port")
    parser.add_argument("--mcp-scheme", choices=("http", "https"), default="http", help="scheme used by the Host MCP reference")
    parser.add_argument("--mcp-host", help="host used by the Host MCP reference; defaults to a connectable bind host")
    parser.add_argument("--mcp-port", type=int, help="port used by the Host MCP reference; defaults to --port")
    parser.add_argument("--host", choices=("opencode",), default="opencode", help="Host used by register or unregister")
    parser.add_argument("--output", help="output path for nginx-template")
    parser.add_argument("--expose-mcp", action="store_true", help="proxy /mcp through Nginx for public Bearer-authenticated MCP access")
    parser.add_argument("--expose-preview", action="store_true", help="explicitly proxy the enabled backend preview through Nginx with Basic Auth (default: 404)")
    parser.add_argument("--purge", action="store_true", help="remove configuration, credentials, and published data")
    args = parser.parse_args(argv)
    paths = install_paths(args.scope)
    try:
        if args.action == "plan":
            payload = _plan(paths, args)
        elif args.action in {"install", "upgrade"}:
            payload = _install(paths, args)
        elif args.action == "status":
            payload = _status(paths)
        elif args.action == "doctor":
            payload = _doctor(paths)
        elif args.action in {"start", "stop", "restart"}:
            payload = _service_command(paths, args.action)
        elif args.action == "register":
            payload = _register_opencode(paths)
        elif args.action == "unregister":
            payload = _unregister_opencode(paths)
        elif args.action == "nginx-template":
            payload = _write_nginx_template(paths, _validate_https_template_arguments(args), args.output, args.expose_mcp, args.expose_preview)
        else:
            payload = _uninstall(paths, args.purge)
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return 0
    except (ManagerError, OSError, subprocess.SubprocessError) as error:
        sys.stderr.write("{}: {}\n".format(APP_NAME, error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
    host = _validate_host(server.get("host", "127.0.0.1"), "server.host", connectable=False)
