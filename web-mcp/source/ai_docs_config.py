"""Configuration schema v2 and validation for the AI Docs web service.

Schema v2 retires the immutable render-release storage (documents/static/
metadata directories); public pages are rendered live from the library's
public directory. Use ``web-mcp-manager.py upgrade`` to migrate v1 configs.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from ai_docs_common import (
    DEFAULT_DOCUMENTS_PREFIX, DEFAULT_MCP_PATH,
    DEFAULT_PREVIEW_MAX_FILES, DEFAULT_PREVIEW_MAX_PATH_DEPTH,
    DEFAULT_PREVIEW_MAX_TOTAL_BYTES, DEFAULT_PREVIEW_PATH,
    DEFAULT_PUBLIC_CONCURRENT_RENDERS, DEFAULT_PUBLIC_DIRECTORY,
    DEFAULT_PUBLIC_RENDER_TIMEOUT, DEFAULT_RENDER_CACHE_BYTES,
    DEFAULT_RENDER_CACHE_ENTRIES, DEFAULT_RENDER_CACHE_ENTRY_BYTES,
    ENVIRONMENT_NAME_PATTERN, MARKDOWN_SUFFIXES, MAX_JSON_DEPTH,
    MAX_PREVIEW_FILES, MAX_PREVIEW_PATH_DEPTH, MAX_PREVIEW_TOTAL_BYTES,
    MAX_RENDER_CACHE_BYTES, MAX_RENDER_CACHE_ENTRIES, MAX_RPC_MESSAGE_BYTES,
    MCP_REFERENCE_NAME, PREVIEW_SESSION_MAX_AGE, PUBLIC_INDEX_FILE,
    ServiceError, bundled_renderer_directory, effective_renderer_directory,
    is_loopback_host, normalized_endpoint, normalized_origin,
    normalized_prefix, normalized_service_address, safe_relative_subdirectory,
    service_origin, validate_directory, validate_host, validated_object,
)

SCHEMA_VERSION = 2
REMOVED_V1_FIELDS = ("documents_directory", "static_directory", "metadata_directory")


def migrate_config_v1(value: Any) -> Dict[str, Any]:
    """Pure v1 → v2 schema migration. No filesystem or environment access.

    The caller (web-mcp-manager.py upgrade) owns backups, the non-empty public
    directory confirmation, and the atomic write of the result.
    """
    if not isinstance(value, dict):
        raise ServiceError(500, "invalid_configuration", "configuration must be a JSON object")
    if value.get("schema_version", 1) != 1:
        raise ServiceError(500, "invalid_configuration", "only schema_version 1 configurations can be migrated")
    candidate = dict(value)
    library = candidate.get("library_directory")
    if library is None:
        # 复现 v1 的缺省推导公式：documents_directory.parents[1] / "private/library"
        documents = candidate.get("documents_directory")
        if not isinstance(documents, str) or not documents.strip():
            raise ServiceError(500, "invalid_configuration", "cannot derive library_directory without documents_directory")
        library = str(Path(documents).parents[1] / "private" / "library")
    candidate["library_directory"] = library
    preview = candidate.get("preview")
    if isinstance(preview, dict):
        preview = dict(preview)
        limits = {}
        for key in ("max_files", "max_total_bytes", "max_path_depth"):
            if key in preview:
                limits[key] = preview.pop(key)
        candidate["preview"] = preview
        if limits and "library_limits" not in candidate:
            candidate["library_limits"] = limits
    server = candidate.get("server")
    if isinstance(server, dict):
        server = dict(server)
        server.pop("static_prefix", None)
        candidate["server"] = server
    for key in REMOVED_V1_FIELDS:
        candidate.pop(key, None)
    candidate["schema_version"] = SCHEMA_VERSION
    return candidate


class ServiceConfig:
    """Validated server configuration. The library directory is the write boundary."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.workspace_root: Path
        self.renderer_directory: Path
        self.library_directory: Path
        self.public_root: Path
        self.public_directory: str
        self.host: str
        self.port: int
        self.public_scheme: str
        self.public_host: str
        self.public_port: int
        self.public_origin: str
        self.documents_prefix: str
        self.preview_enabled: bool
        self.preview_write_back: bool
        self.preview_login_mode: str
        self.preview_path: str
        self.preview_prefix: str
        self.preview_session_secret: Optional[str]
        self.preview_session_seconds: int
        self.library_max_files: int
        self.library_max_total_bytes: int
        self.library_max_path_depth: int
        self.public_max_files: int
        self.public_max_total_bytes: int
        self.public_max_concurrent_renders: int
        self.public_render_timeout_seconds: int
        self.cache_max_bytes: int
        self.cache_max_entries: int
        self.cache_max_entry_bytes: int
        self.mcp_path: str
        self.mcp_reference: Dict[str, Any]
        self.node_executable: Path
        self.max_upload_bytes: int
        self.max_rpc_bytes: int
        self.request_timeout_seconds: int
        self.render_timeout_seconds: int
        self.max_concurrent_renders: int
        self.auth_required: bool
        self.auth_token_env: str
        self.allowed_origins: Tuple[str, ...]
        self._load()

    @staticmethod
    def config_path() -> Path:
        configured = os.environ.get("AI_DOCS_MCP_CONFIG", "").strip()
        if configured:
            return Path(configured).expanduser()
        config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return Path(config_home) / "ai-docs-web" / "server.json"

    @classmethod
    def load(cls) -> "ServiceConfig":
        path = cls.config_path()
        for parent in path.parents:
            if parent.is_symlink():
                raise ServiceError(500, "invalid_configuration", "configuration path has a symlinked parent: {}".format(parent))
        if path.is_symlink() or not path.is_file():
            raise ServiceError(500, "invalid_configuration", "configuration file does not exist: {}".format(path))
        return cls(path)

    def _load(self) -> None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise ServiceError(500, "invalid_configuration", "cannot parse configuration: {}".format(error)) from error
        if not isinstance(value, dict):
            raise ServiceError(500, "invalid_configuration", "configuration must be a JSON object")
        removed = [field for field in REMOVED_V1_FIELDS if field in value]
        if removed:
            raise ServiceError(
                500, "invalid_configuration",
                "{} were removed in schema v2; run web-mcp-manager.py upgrade to migrate".format(", ".join(removed)),
            )
        allowed = {
            "schema_version", "workspace_root", "library_directory", "public_directory",
            "library_limits", "public_docs", "render_cache", "server", "preview", "mcp",
            "renderer", "max_upload_bytes", "max_rpc_bytes", "request_timeout_seconds",
            "render_timeout_seconds", "max_concurrent_renders", "auth_required",
            "auth_token_env", "allowed_origins",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ServiceError(500, "invalid_configuration", "unknown configuration fields: {}".format(", ".join(unknown)))
        schema_version = value.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ServiceError(
                500, "invalid_configuration",
                "schema_version must be 2; run web-mcp-manager.py upgrade to migrate older configurations",
            )

        # 配置加载只校验不创建目录；目录由 install/upgrade 显式创建。
        self.workspace_root = validate_directory(Path(value.get("workspace_root", "")), "workspace_root")
        self.renderer_directory = validate_directory(effective_renderer_directory(), "bundled renderer")
        build_script = self.renderer_directory / "scripts" / "build.js"
        if build_script.is_symlink() or not build_script.is_file():
            raise ServiceError(500, "invalid_configuration", "bundled renderer/scripts/build.js is unavailable")
        resource_manifest = self.renderer_directory / "assets" / "default-resources.json"
        vendor_directory = self.renderer_directory / "scripts" / "vendor"
        markdown_runtime = vendor_directory / "markdown-it.min.js"
        if resource_manifest.is_symlink() or not resource_manifest.is_file():
            raise ServiceError(500, "invalid_configuration", "bundled renderer/assets/default-resources.json is unavailable")
        if vendor_directory.is_symlink() or not vendor_directory.is_dir():
            raise ServiceError(500, "invalid_configuration", "bundled renderer/scripts/vendor is unavailable")
        if markdown_runtime.is_symlink() or not markdown_runtime.is_file():
            raise ServiceError(500, "invalid_configuration", "bundled renderer/scripts/vendor/markdown-it.min.js is unavailable")

        configured_library = value.get("library_directory")
        if not isinstance(configured_library, str) or not configured_library.strip():
            raise ServiceError(500, "invalid_configuration", "library_directory is required (schema v2 no longer derives it)")
        self.library_directory = validate_directory(Path(configured_library), "library_directory")
        if self.workspace_root == self.library_directory or self.workspace_root.is_relative_to(
            self.library_directory
        ) or self.library_directory.is_relative_to(self.workspace_root):
            raise ServiceError(500, "invalid_configuration", "workspace_root and library_directory must not overlap")

        self.public_directory = safe_relative_subdirectory(value.get("public_directory", DEFAULT_PUBLIC_DIRECTORY), "public_directory")
        if len(self.public_directory.split("/")) > MAX_PREVIEW_PATH_DEPTH:
            raise ServiceError(500, "invalid_configuration", "public_directory is too deep")
        public_root = self.library_directory.joinpath(*self.public_directory.split("/"))
        if not public_root.is_relative_to(self.library_directory) or public_root == self.library_directory:
            raise ServiceError(500, "invalid_configuration", "public_directory must stay strictly inside library_directory")
        if public_root.is_symlink():
            raise ServiceError(500, "invalid_configuration", "public_directory must not be a symlink")
        if public_root.exists() and not public_root.is_dir():
            raise ServiceError(500, "invalid_configuration", "public_directory exists but is not a directory")
        self.public_root = public_root

        server = validated_object(value.get("server"), "server", {"host", "port", "public", "documents_prefix"})
        preview = validated_object(value.get("preview"), "preview", {
            "enabled", "path", "write_back", "session_seconds", "session_secret", "login_mode",
        })
        mcp = validated_object(value.get("mcp"), "mcp", {"path", "reference"})
        reference = validated_object(mcp.get("reference"), "mcp.reference", {
            "name", "scheme", "host", "port", "path", "timeout_ms", "token_env",
        })
        renderer = validated_object(value.get("renderer"), "renderer", {"node"})
        library_limits = validated_object(value.get("library_limits"), "library_limits", {
            "max_files", "max_total_bytes", "max_path_depth",
        })
        public_docs = validated_object(value.get("public_docs"), "public_docs", {
            "max_files", "max_total_bytes", "max_concurrent_renders", "render_timeout_seconds",
        })
        render_cache = validated_object(value.get("render_cache"), "render_cache", {
            "max_bytes", "max_entries", "max_entry_bytes",
        })

        self.host = validate_host(server.get("host", "127.0.0.1"))
        self.port = server.get("port", 18080)
        if type(self.port) is not int or self.port < 0 or self.port > 65535:
            raise ServiceError(500, "invalid_configuration", "server.port must be an integer from 0 to 65535")
        self.public_scheme, self.public_host, self.public_port = normalized_service_address(
            server.get("public"), "server.public"
        )
        self.public_origin = service_origin(self.public_scheme, self.public_host, self.public_port)
        self.documents_prefix = normalized_prefix(
            server.get("documents_prefix"), "server.documents_prefix", DEFAULT_DOCUMENTS_PREFIX
        )
        self.mcp_path = normalized_endpoint(mcp.get("path", DEFAULT_MCP_PATH), "mcp.path")
        self.preview_enabled = preview.get("enabled", False)
        if type(self.preview_enabled) is not bool:
            raise ServiceError(500, "invalid_configuration", "preview.enabled must be boolean")
        self.preview_write_back = preview.get("write_back", True)
        if type(self.preview_write_back) is not bool:
            raise ServiceError(500, "invalid_configuration", "preview.write_back must be boolean")
        self.preview_login_mode = preview.get("login_mode", "token")
        if self.preview_login_mode not in ("token", "proxy"):
            raise ServiceError(500, "invalid_configuration", "preview.login_mode must be token or proxy")
        if self.preview_login_mode == "proxy" and (self.host not in ("127.0.0.1", "::1") or not value.get("auth_required", True)):
            raise ServiceError(500, "invalid_configuration", "proxy login requires loopback binding and authentication")
        self.preview_path = normalized_endpoint(preview.get("path", DEFAULT_PREVIEW_PATH), "preview.path")
        self.preview_prefix = self.preview_path + "/"
        self.preview_session_seconds = preview.get("session_seconds", PREVIEW_SESSION_MAX_AGE)
        if type(self.preview_session_seconds) is not int or self.preview_session_seconds < 60 or self.preview_session_seconds > 7 * 24 * 60 * 60:
            raise ServiceError(500, "invalid_configuration", "preview.session_seconds must be between 60 and 604800")
        session_secret = preview.get("session_secret")
        if session_secret is not None and (not isinstance(session_secret, str) or len(session_secret) < 32):
            raise ServiceError(500, "invalid_configuration", "preview.session_secret must be at least 32 characters")
        self.preview_session_secret = session_secret

        self.library_max_files = library_limits.get("max_files", DEFAULT_PREVIEW_MAX_FILES)
        if type(self.library_max_files) is not int or self.library_max_files < 1 or self.library_max_files > MAX_PREVIEW_FILES:
            raise ServiceError(500, "invalid_configuration", "library_limits.max_files must be between 1 and {}".format(MAX_PREVIEW_FILES))
        self.library_max_total_bytes = library_limits.get("max_total_bytes", DEFAULT_PREVIEW_MAX_TOTAL_BYTES)
        if type(self.library_max_total_bytes) is not int or self.library_max_total_bytes < 1024 or self.library_max_total_bytes > MAX_PREVIEW_TOTAL_BYTES:
            raise ServiceError(500, "invalid_configuration", "library_limits.max_total_bytes must be between 1024 and {}".format(MAX_PREVIEW_TOTAL_BYTES))
        self.library_max_path_depth = library_limits.get("max_path_depth", DEFAULT_PREVIEW_MAX_PATH_DEPTH)
        if type(self.library_max_path_depth) is not int or self.library_max_path_depth < 1 or self.library_max_path_depth > MAX_PREVIEW_PATH_DEPTH:
            raise ServiceError(500, "invalid_configuration", "library_limits.max_path_depth must be between 1 and {}".format(MAX_PREVIEW_PATH_DEPTH))

        self.public_max_files = public_docs.get("max_files", max(1, self.library_max_files * 4 // 5))
        if type(self.public_max_files) is not int or self.public_max_files < 1 or self.public_max_files > self.library_max_files:
            raise ServiceError(500, "invalid_configuration", "public_docs.max_files must be between 1 and library_limits.max_files")
        self.public_max_total_bytes = public_docs.get("max_total_bytes", max(1024, self.library_max_total_bytes * 4 // 5))
        if type(self.public_max_total_bytes) is not int or self.public_max_total_bytes < 1024 or self.public_max_total_bytes > self.library_max_total_bytes:
            raise ServiceError(500, "invalid_configuration", "public_docs.max_total_bytes must be between 1024 and library_limits.max_total_bytes")
        self.public_max_concurrent_renders = public_docs.get("max_concurrent_renders", DEFAULT_PUBLIC_CONCURRENT_RENDERS)
        self.max_concurrent_renders = value.get("max_concurrent_renders", 2)
        if type(self.max_concurrent_renders) is not int or self.max_concurrent_renders < 1 or self.max_concurrent_renders > 32:
            raise ServiceError(500, "invalid_configuration", "max_concurrent_renders must be between 1 and 32")
        if type(self.public_max_concurrent_renders) is not int or self.public_max_concurrent_renders < 1 or self.public_max_concurrent_renders > self.max_concurrent_renders:
            raise ServiceError(500, "invalid_configuration", "public_docs.max_concurrent_renders must be between 1 and max_concurrent_renders")
        self.render_timeout_seconds = value.get("render_timeout_seconds", 120)
        if type(self.render_timeout_seconds) is not int or self.render_timeout_seconds < 1 or self.render_timeout_seconds > 900:
            raise ServiceError(500, "invalid_configuration", "render_timeout_seconds must be between 1 and 900")
        self.public_render_timeout_seconds = public_docs.get("render_timeout_seconds", DEFAULT_PUBLIC_RENDER_TIMEOUT)
        if type(self.public_render_timeout_seconds) is not int or self.public_render_timeout_seconds < 1 or self.public_render_timeout_seconds > 300:
            raise ServiceError(500, "invalid_configuration", "public_docs.render_timeout_seconds must be between 1 and 300")

        self.cache_max_bytes = render_cache.get("max_bytes", DEFAULT_RENDER_CACHE_BYTES)
        if type(self.cache_max_bytes) is not int or self.cache_max_bytes < 1024 * 1024 or self.cache_max_bytes > MAX_RENDER_CACHE_BYTES:
            raise ServiceError(500, "invalid_configuration", "render_cache.max_bytes must be between 1048576 and {}".format(MAX_RENDER_CACHE_BYTES))
        self.cache_max_entries = render_cache.get("max_entries", DEFAULT_RENDER_CACHE_ENTRIES)
        if type(self.cache_max_entries) is not int or self.cache_max_entries < 1 or self.cache_max_entries > MAX_RENDER_CACHE_ENTRIES:
            raise ServiceError(500, "invalid_configuration", "render_cache.max_entries must be between 1 and {}".format(MAX_RENDER_CACHE_ENTRIES))
        self.cache_max_entry_bytes = render_cache.get("max_entry_bytes", DEFAULT_RENDER_CACHE_ENTRY_BYTES)
        if type(self.cache_max_entry_bytes) is not int or self.cache_max_entry_bytes < 1024 or self.cache_max_entry_bytes > self.cache_max_bytes:
            raise ServiceError(500, "invalid_configuration", "render_cache.max_entry_bytes must be between 1024 and render_cache.max_bytes")

        routes = {
            "server.documents_prefix": self.documents_prefix,
            "preview.path": self.preview_prefix,
            "mcp.path": self.mcp_path + "/",
            "health check": "/healthz/",
        }
        route_items = list(routes.items())
        for index, (left_name, left_path) in enumerate(route_items):
            for right_name, right_path in route_items[index + 1:]:
                if left_path.startswith(right_path) or right_path.startswith(left_path):
                    raise ServiceError(500, "invalid_configuration", "{} overlaps {}".format(left_name, right_name))
        self.max_upload_bytes = value.get("max_upload_bytes", 5 * 1024 * 1024)
        if type(self.max_upload_bytes) is not int or self.max_upload_bytes < 1024 or self.max_upload_bytes > 100 * 1024 * 1024:
            raise ServiceError(500, "invalid_configuration", "max_upload_bytes must be between 1024 and 104857600")
        self.max_rpc_bytes = value.get("max_rpc_bytes", MAX_RPC_MESSAGE_BYTES)
        if type(self.max_rpc_bytes) is not int or self.max_rpc_bytes < 1024 or self.max_rpc_bytes > 10 * 1024 * 1024:
            raise ServiceError(500, "invalid_configuration", "max_rpc_bytes must be between 1024 and 10485760")
        self.request_timeout_seconds = value.get("request_timeout_seconds", 60)
        if type(self.request_timeout_seconds) is not int or self.request_timeout_seconds < 1 or self.request_timeout_seconds > 300:
            raise ServiceError(500, "invalid_configuration", "request_timeout_seconds must be between 1 and 300")
        self.auth_required = value.get("auth_required", True)
        if type(self.auth_required) is not bool:
            raise ServiceError(500, "invalid_configuration", "auth_required must be boolean")
        self.auth_token_env = value.get("auth_token_env", "AI_DOCS_API_TOKEN")
        if not isinstance(self.auth_token_env, str) or not ENVIRONMENT_NAME_PATTERN.fullmatch(self.auth_token_env):
            raise ServiceError(500, "invalid_configuration", "auth_token_env must be an environment variable name")
        configured_origins = value.get("allowed_origins", [])
        if not isinstance(configured_origins, list) or any(not isinstance(item, str) for item in configured_origins):
            raise ServiceError(500, "invalid_configuration", "allowed_origins must be an array of HTTP(S) origins")
        origins = [normalized_origin(item, "allowed_origins") for item in configured_origins]
        origins.append(self.public_origin)
        self.allowed_origins = tuple(dict.fromkeys(origins))
        reference_name = reference.get("name", MCP_REFERENCE_NAME)
        if not isinstance(reference_name, str) or not reference_name.strip() or len(reference_name.strip()) > 128:
            raise ServiceError(500, "invalid_configuration", "mcp.reference.name must be a short non-empty string")
        reference_timeout = reference.get("timeout_ms", 30000)
        if type(reference_timeout) is not int or reference_timeout < 1000 or reference_timeout > 300000:
            raise ServiceError(500, "invalid_configuration", "mcp.reference.timeout_ms must be between 1000 and 300000")
        reference_token_env = reference.get("token_env", self.auth_token_env)
        if not isinstance(reference_token_env, str) or not ENVIRONMENT_NAME_PATTERN.fullmatch(reference_token_env):
            raise ServiceError(500, "invalid_configuration", "mcp.reference.token_env must be an environment variable name")
        reference_scheme, reference_host, reference_port = normalized_service_address(
            {
                "scheme": reference.get("scheme"),
                "host": reference.get("host"),
                "port": reference.get("port"),
            },
            "mcp.reference",
        )
        reference_path = normalized_endpoint(reference.get("path", self.mcp_path), "mcp.reference.path")
        reference_url = service_origin(reference_scheme, reference_host, reference_port) + reference_path
        self.mcp_reference = {
            "name": reference_name.strip(),
            "scheme": reference_scheme,
            "host": reference_host,
            "port": reference_port,
            "path": reference_path,
            "url": reference_url,
            "timeout_ms": reference_timeout,
            "token_env": reference_token_env,
        }

        node_value = renderer.get("node")
        if not isinstance(node_value, str) or not node_value.strip():
            raise ServiceError(500, "invalid_configuration", "renderer.node must be an absolute executable path")
        environment_node = os.environ.get("AI_DOCS_NODE", "").strip()
        if environment_node and environment_node != node_value:
            raise ServiceError(500, "invalid_configuration", "AI_DOCS_NODE does not match renderer.node")
        node_path = Path(node_value).expanduser()
        if not node_path.is_absolute():
            raise ServiceError(500, "invalid_configuration", "renderer.node must be absolute")
        for parent in node_path.parents:
            if parent.is_symlink():
                raise ServiceError(500, "invalid_configuration", "renderer.node has a symlinked parent")
        if node_path.is_symlink() or not node_path.is_file() or not os.access(node_path, os.X_OK):
            raise ServiceError(500, "invalid_configuration", "renderer.node must be a regular executable file")
        self.node_executable = node_path

    def token(self) -> Optional[str]:
        if not self.auth_required:
            return None
        value = os.environ.get(self.auth_token_env, "").strip()
        if not value:
            raise ServiceError(503, "auth_unavailable", "the configured API token environment variable is empty")
        return value

    def preview_secret(self) -> str:
        """Derive the preview session key from the API token so restarts keep sessions."""
        if self.preview_session_secret is not None:
            return self.preview_session_secret
        token = self.token()
        if token is not None:
            return hashlib.sha256(b"ai-docs-preview-session:" + token.encode("utf-8")).hexdigest()
        return hashlib.sha256(b"ai-docs-preview-session:unauthenticated").hexdigest()

    def public_url_path(self, relative: str) -> str:
        """Map a public-root-relative Markdown path to its /docs URL path."""
        parts = relative.split("/")
        name = parts[-1].lower()
        if name == PUBLIC_INDEX_FILE.lower():
            directory = "/".join(quote(part) for part in parts[:-1])
            return self.documents_prefix + directory + ("/" if directory else "")
        if name.endswith(".md"):
            stem = "/".join(parts)[:-3]
            return self.documents_prefix + "/".join(quote(part) for part in stem.split("/"))
        return self.documents_prefix + "/".join(quote(part) for part in parts)

    def public_document_url(self, relative: str) -> str:
        return self.public_origin + self.public_url_path(relative)

    def describe(self) -> Dict[str, Any]:
        return {
            "config_path": str(self.path),
            "schema_version": SCHEMA_VERSION,
            "workspace_root": str(self.workspace_root),
            "renderer_directory": str(self.renderer_directory),
            "library_directory": str(self.library_directory),
            "public_directory": self.public_directory,
            "public_root": str(self.public_root),
            "server": {
                "host": self.host,
                "port": self.port,
                "public": {
                    "scheme": self.public_scheme,
                    "host": self.public_host,
                    "port": self.public_port,
                    "origin": self.public_origin,
                },
                "documents_prefix": self.documents_prefix,
                "bind_exposed": not is_loopback_host(self.host),
            },
            "preview": {
                "enabled": self.preview_enabled,
                "path": self.preview_path,
                "write_back": self.preview_write_back,
                "session_seconds": self.preview_session_seconds,
            },
            "library_limits": {
                "max_files": self.library_max_files,
                "max_total_bytes": self.library_max_total_bytes,
                "max_path_depth": self.library_max_path_depth,
            },
            "public_docs": {
                "max_files": self.public_max_files,
                "max_total_bytes": self.public_max_total_bytes,
                "max_concurrent_renders": self.public_max_concurrent_renders,
                "render_timeout_seconds": self.public_render_timeout_seconds,
            },
            "render_cache": {
                "max_bytes": self.cache_max_bytes,
                "max_entries": self.cache_max_entries,
                "max_entry_bytes": self.cache_max_entry_bytes,
            },
            "mcp": {"path": self.mcp_path, "reference": dict(self.mcp_reference)},
            "renderer": {"node": str(self.node_executable)},
            "max_upload_bytes": self.max_upload_bytes,
            "max_rpc_bytes": self.max_rpc_bytes,
            "request_timeout_seconds": self.request_timeout_seconds,
            "render_timeout_seconds": self.render_timeout_seconds,
            "max_concurrent_renders": self.max_concurrent_renders,
            "auth_required": self.auth_required,
            "auth_token_env": self.auth_token_env,
            "allowed_origins": list(self.allowed_origins),
        }
