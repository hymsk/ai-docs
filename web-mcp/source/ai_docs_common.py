"""Shared constants, errors, and pure validation helpers for the AI Docs web service."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse


MCP_REFERENCE_NAME = "ai-docs"


def bundled_renderer_directory() -> Path:
    """Locate the canonical renderer in either the Skill or installed runtime."""
    source_directory = Path(__file__).resolve().parent
    candidates = (source_directory, source_directory.parent, source_directory.parents[1])
    for candidate in candidates:
        if (candidate / "scripts" / "build.js").is_file():
            return candidate
    return candidates[0]


BUNDLED_RENDERER_DIR = bundled_renderer_directory()


def effective_renderer_directory() -> Path:
    """Re-evaluate the location to keep isolated imports and copied runtimes safe."""
    return bundled_renderer_directory()


def renderer_fingerprint(config) -> str:
    """Hash build.js plus vendored assets; drives render cache and asset URLs."""
    digest = hashlib.sha256()
    scripts = config.renderer_directory / "scripts"
    targets = [scripts / "build.js"]
    vendor = scripts / "vendor"
    if vendor.is_dir():
        targets.extend(sorted(path for path in vendor.rglob("*") if path.is_file()))
    for target in targets:
        try:
            digest.update(target.relative_to(scripts).as_posix().encode("utf-8"))
            digest.update(target.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()


LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")


MODERN_PROTOCOL_VERSION = "2026-07-28"


SUPPORTED_PROTOCOL_VERSIONS = (MODERN_PROTOCOL_VERSION,) + LEGACY_PROTOCOL_VERSIONS


DEFAULT_PROTOCOL_VERSION = LEGACY_PROTOCOL_VERSIONS[0]


DEFAULT_DOCUMENTS_PREFIX = "/docs/"


# 渲染器资源端点前缀（不可配置）：/assets/<renderer-fingerprint>/<file>。
# URL 带指纹可长期缓存，版本更新自动切换新路径。
DEFAULT_ASSETS_PREFIX = "/assets/"


DEFAULT_STATIC_PREFIX = "/static/"
DEFAULT_PUBLIC_DIRECTORY = "public"
PUBLIC_INDEX_FILE = "README.md"
MARKDOWN_SUFFIXES = (".md", ".markdown", ".txt")
DEFAULT_RENDER_CACHE_BYTES = 128 * 1024 * 1024
DEFAULT_RENDER_CACHE_ENTRIES = 128
DEFAULT_RENDER_CACHE_ENTRY_BYTES = 32 * 1024 * 1024
MAX_RENDER_CACHE_BYTES = 4 * 1024 * 1024 * 1024
MAX_RENDER_CACHE_ENTRIES = 4096
DEFAULT_PUBLIC_RENDER_TIMEOUT = 30
DEFAULT_PUBLIC_CONCURRENT_RENDERS = 1


DEFAULT_MCP_PATH = "/mcp"


DEFAULT_PREVIEW_PATH = "/preview"


DEFAULT_PREVIEW_LIBRARY = "data/private/library"


PREVIEW_SESSION_COOKIE = "ai_docs_preview"


PREVIEW_SESSION_MAX_AGE = 12 * 60 * 60


PREVIEW_SESSION_CLOCK_SKEW = 60


DEFAULT_PREVIEW_MAX_FILES = 1000


DEFAULT_PREVIEW_MAX_TOTAL_BYTES = 50 * 1024 * 1024


DEFAULT_PREVIEW_MAX_PATH_DEPTH = 8


MAX_PREVIEW_FILES = 10000


MAX_PREVIEW_TOTAL_BYTES = 1024 * 1024 * 1024


MAX_PREVIEW_PATH_DEPTH = 32


MAX_RPC_MESSAGE_BYTES = 6 * 1024 * 1024


MAX_RPC_RESPONSE_BYTES = 1024 * 1024


MAX_PREVIEW_RESPONSE_BYTES = 32 * 1024 * 1024


MAX_FILENAME_LENGTH = 255


MAX_RENDER_ID_LENGTH = 64


MAX_JSON_DEPTH = 64


ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


URL_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$")


HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)


class ServiceError(RuntimeError):
    """An expected service error with an HTTP/API status."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: Optional[Dict[str, str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.details = details or {}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def safe_filename(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_FILENAME_LENGTH:
        raise ServiceError(400, "invalid_filename", "filename must be a short Markdown filename")
    if any(ord(character) < 32 or ord(character) == 127 for character in value) or "/" in value or "\\" in value:
        raise ServiceError(400, "invalid_filename", "filename must be a basename and must not contain path separators")
    name = Path(value).name
    if name != value or name in {".", ".."} or value.lower().endswith(('.html', '.htm')):
        raise ServiceError(400, "invalid_filename", "filename must be a basename and must not be HTML")
    if not value.lower().endswith(('.md', '.markdown', '.txt')):
        raise ServiceError(400, "invalid_filename", "filename must end in .md, .markdown, or .txt")
    return value


def safe_render_id(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_RENDER_ID_LENGTH:
        raise ServiceError(400, "invalid_render_id", "render_id is invalid")
    if not all(character.isascii() and (character.isalnum() or character in "-_") for character in value):
        raise ServiceError(400, "invalid_render_id", "render_id is invalid")
    return value


def markdown_bytes(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ServiceError(400, "invalid_markdown", "markdown must be a string")
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ServiceError(400, "invalid_encoding", "markdown must contain valid Unicode text") from error


def invalid_json_constant(value: str) -> None:
    raise ValueError("invalid JSON constant: {}".format(value))


def parse_json(body: bytes, label: str) -> Any:
    try:
        value = json.loads(
            body.decode("utf-8"),
            parse_constant=invalid_json_constant,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise ServiceError(400, "invalid_json", "{} is not valid JSON".format(label)) from error
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise ServiceError(400, "invalid_json", "{} exceeds the maximum JSON nesting depth".format(label))
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def normalized_origin(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(500, "invalid_configuration", "{} must be an absolute HTTP(S) origin".format(label))
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        raise ServiceError(500, "invalid_configuration", "{} contains whitespace or control characters".format(label))
    try:
        parsed = urlparse(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ServiceError(500, "invalid_configuration", "{} contains an invalid host or port".format(label)) from error
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ServiceError(500, "invalid_configuration", "{} must be an HTTP(S) origin without credentials, path, query, or fragment".format(label))
    host = hostname.lower()
    if ":" in host:
        host = "[{}]".format(host)
    default_port = 80 if parsed.scheme.lower() == "http" else 443
    authority = host if port in {None, default_port} else "{}:{}".format(host, port)
    return "{}://{}".format(parsed.scheme.lower(), authority)


def normalized_service_address(value: Any, label: str) -> Tuple[str, str, int]:
    if not isinstance(value, dict):
        raise ServiceError(500, "invalid_configuration", "{} must be a JSON object".format(label))
    unknown = sorted(set(value) - {"scheme", "host", "port"})
    if unknown:
        raise ServiceError(500, "invalid_configuration", "unknown {} fields: {}".format(label, ", ".join(unknown)))
    scheme = value.get("scheme")
    host = value.get("host")
    port = value.get("port")
    if scheme not in {"http", "https"}:
        raise ServiceError(500, "invalid_configuration", "{}.scheme must be http or https".format(label))
    host = validate_host(host, "{}.host".format(label))
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and address.is_unspecified:
        raise ServiceError(500, "invalid_configuration", "{}.host must be a connectable host, not a wildcard address".format(label))
    if type(port) is not int or port < 1 or port > 65535:
        raise ServiceError(500, "invalid_configuration", "{}.port must be an integer from 1 to 65535".format(label))
    return scheme, host, port


def service_origin(scheme: str, host: str, port: int) -> str:
    authority_host = "[{}]".format(host) if ":" in host else host
    default_port = 80 if scheme == "http" else 443
    authority = authority_host if port == default_port else "{}:{}".format(authority_host, port)
    return "{}://{}".format(scheme, authority)


def normalized_prefix(value: Any, label: str, default_value: str) -> str:
    if value is None:
        return default_value
    if not isinstance(value, str) or not URL_PATH_PATTERN.fullmatch(value) or value == "/" or ".." in value:
        raise ServiceError(500, "invalid_configuration", "{} must be a non-root local URL path".format(label))
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or parsed.params or parsed.query or parsed.fragment:
        raise ServiceError(500, "invalid_configuration", "{} must not contain a URL origin, query, or fragment".format(label))
    return "/" + value.strip("/") + "/"


def normalized_endpoint(value: Any, label: str) -> str:
    if not isinstance(value, str) or not URL_PATH_PATTERN.fullmatch(value) or value == "/" or ".." in value:
        raise ServiceError(500, "invalid_configuration", "{} must be a non-root local URL path".format(label))
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or parsed.params or parsed.query or parsed.fragment:
        raise ServiceError(500, "invalid_configuration", "{} must not contain a URL origin, query, or fragment".format(label))
    return "/" + value.strip("/")


def validate_directory(path: Path, label: str, create: bool = False) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise ServiceError(500, "invalid_configuration", "{} must be absolute".format(label))
    for parent in path.parents:
        if parent.is_symlink():
            raise ServiceError(500, "invalid_configuration", "{} has a symlinked parent".format(label))
    if path.is_symlink():
        raise ServiceError(500, "invalid_configuration", "{} must not be a symlink".format(label))
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ServiceError(500, "invalid_configuration", "cannot create {}: {}".format(label, error)) from error
    if not path.is_dir():
        raise ServiceError(500, "invalid_configuration", "{} must be a directory".format(label))
    return path.resolve()


def validated_object(value: Any, label: str, allowed: set[str]) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ServiceError(500, "invalid_configuration", "{} must be a JSON object".format(label))
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ServiceError(500, "invalid_configuration", "unknown {} fields: {}".format(label, ", ".join(unknown)))
    return value


def safe_relative_markdown_path(value: Any) -> str:
    """Validate a Markdown path relative to the preview library root."""
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ServiceError(400, "invalid_path", "path must be a Markdown path inside the library")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ServiceError(400, "invalid_path", "path contains control characters")
    if "\\" in value or value.startswith("/") or value.endswith("/"):
        raise ServiceError(400, "invalid_path", "path must be a relative Markdown path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ServiceError(400, "invalid_path", "path must not contain empty or dot segments")
    if any(part.startswith(".") for part in parts):
        raise ServiceError(400, "invalid_path", "path must not contain hidden segments")
    if len(parts[-1]) > MAX_FILENAME_LENGTH:
        raise ServiceError(400, "invalid_path", "path contains an overlong filename")
    if not parts[-1].lower().endswith((".md", ".markdown", ".txt")):
        raise ServiceError(400, "invalid_path", "path must end in .md, .markdown, or .txt")
    return "/".join(parts)


def safe_relative_subdirectory(value: Any, label: str) -> str:
    """Validate a relative subdirectory path (no suffix requirement)."""
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ServiceError(400, "invalid_path", "{} must be a short relative directory path".format(label))
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ServiceError(400, "invalid_path", "{} contains control characters".format(label))
    if "\\" in value or value.startswith("/") or value.endswith("/"):
        raise ServiceError(400, "invalid_path", "{} must be a relative directory path".format(label))
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ServiceError(400, "invalid_path", "{} must not contain empty or dot segments".format(label))
    if any(part.startswith(".") for part in parts):
        raise ServiceError(400, "invalid_path", "{} must not contain hidden segments".format(label))
    return "/".join(parts)


def resolve_library_path(root: Path, relative: str) -> Path:
    """Resolve a validated library path, rejecting symlinked escapes."""
    relative = safe_relative_markdown_path(relative)
    target = root.joinpath(*relative.split("/"))
    for parent in target.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ServiceError(400, "invalid_path", "path must not contain symlinked directories")
    if target.is_symlink():
        raise ServiceError(400, "invalid_path", "path must not be a symlink")
    return target


def is_loopback_host(value: str) -> bool:
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def validate_host(value: Any, label: str = "server.host") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(500, "invalid_configuration", "{} must be a non-empty host or bind address".format(label))
    host = value.strip()
    if len(host) > 253 or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in host):
        raise ServiceError(500, "invalid_configuration", "{} contains invalid characters".format(label))
    if host.startswith("[") or host.endswith("]") or "/" in host or "://" in host:
        raise ServiceError(500, "invalid_configuration", "{} must not contain URL syntax or IPv6 brackets".format(label))
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if ":" in host or not HOSTNAME_PATTERN.fullmatch(host):
            raise ServiceError(500, "invalid_configuration", "{} must be a valid hostname, IPv4 address, or unbracketed IPv6 address".format(label))
    return host


def human_readable_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return "{} B".format(size_bytes)
    if size_bytes < 1024 * 1024:
        return "{:.1f} KB".format(size_bytes / 1024)
    return "{:.1f} MB".format(size_bytes / (1024 * 1024))
