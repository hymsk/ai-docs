"""HTTP transport: routing, authentication, and server assembly."""

from __future__ import annotations

import http.server
import hmac
import json
import socket
import sys
import threading
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

from ai_docs_common import (
    DEFAULT_ASSETS_PREFIX, MAX_PREVIEW_RESPONSE_BYTES, MAX_RPC_RESPONSE_BYTES,
    PREVIEW_SESSION_COOKIE, ServiceError, json_bytes, normalized_origin,
    parse_json, safe_relative_markdown_path,
)
from ai_docs_config import ServiceConfig
from ai_docs_library import LibraryStore, PreviewStore, read_resource_asset
from ai_docs_mcp import McpService
from ai_docs_public import PublicDocs, not_found_response
from ai_docs_preview import (
    PREVIEW_EDITOR_SANDBOX, PREVIEW_READER_SANDBOX, preview_editor_page,
    preview_index_page, preview_login_page, preview_reader_page,
    preview_session_value, valid_preview_session,
)

# Server identity is injected by the entry module (ai_docs_web) so version
# literals stay in one place for the release checker.
SERVER_NAME = ""
SERVER_VERSION = ""


def configure_identity(server_name: str, server_version: str) -> None:
    """Bind the server identity before AiDocsHTTPServer is created."""
    global SERVER_NAME, SERVER_VERSION
    if not server_name or not server_version:
        raise ValueError("server identity must be non-empty")
    SERVER_NAME = server_name
    SERVER_VERSION = server_version
    AiDocsHandler.server_version = server_name + "/" + server_version


def safe_log_value(value: str) -> str:
    # 解码后的请求路径等外部输入可含 %0a 之类的控制字符；直接写入日志可伪造
    # 多行记录。转义不可打印字符，可打印字符（含中文）保持原样可读。
    return "".join(
        char if char.isprintable() else "\\u{:04x}".format(ord(char))
        for char in value
    )




class AiDocsHandler(http.server.BaseHTTPRequestHandler):
    """HTTP API, static document endpoint, and remote MCP endpoint."""

    protocol_version = "HTTP/1.1"

    @property
    def service(self) -> "AiDocsHTTPServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, format_string: str, *args: Any) -> None:
        sys.stderr.write("ai-docs-web: " + (format_string % args) + "\n")

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        """Log only the normalized path; never copy query strings or credentials."""
        self.log_message('"%s %s %s" %s %s', self.command, self._log_path(), self.request_version, str(code), str(size))

    def _log_path(self) -> str:
        return safe_log_value(self._path())

    def _send_json(self, status: int, value: Any, headers: Optional[Dict[str, str]] = None, maximum: int = MAX_RPC_RESPONSE_BYTES) -> None:
        body = json_bytes(value)
        if len(body) > maximum:
            status = 500
            body = json_bytes({"error": {"code": "response_too_large", "message": "response exceeds the configured limit"}})
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int, headers: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _error(self, error: ServiceError) -> None:
        self.close_connection = True
        headers = dict(error.headers)
        headers["Connection"] = "close"
        self._send_json(error.status, {"error": {"code": error.code, "message": error.message}}, headers)

    def _path(self) -> str:
        return unquote(urlparse(self.path).path)

    def _send_html(self, status: int, body: str, headers: Optional[Dict[str, str]] = None) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _send_redirect(self, location: str, headers: Optional[Dict[str, str]] = None, status: int = 303) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _send_bytes(self, status: int, body: bytes, headers: Optional[Dict[str, str]] = None, head: bool = False) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and not head:
            self.wfile.write(body)

    def _preview_cookie(self) -> Optional[str]:
        for header in self.headers.get_all("Cookie") or []:
            for item in header.split(";"):
                name, separator, value = item.strip().partition("=")
                if separator and name == PREVIEW_SESSION_COOKIE:
                    return value
        return None

    def _authorized_preview(self) -> None:
        config = self.service.config
        if not config.preview_enabled:
            raise ServiceError(404, "not_found", "preview is disabled")
        if valid_preview_session(config.preview_secret(), self._preview_cookie(), config.preview_session_seconds):
            return
        raise ServiceError(401, "unauthorized", "a preview session is required")

    def _create_preview_session(self) -> None:
        config = self.service.config
        if not config.preview_enabled:
            raise ServiceError(404, "not_found", "preview is disabled")
        self._authorized()
        if config.preview_login_mode == "proxy":
            origin = self.headers.get("Origin")
            if origin is None or normalized_origin(origin, "Origin") not in config.allowed_origins:
                raise ServiceError(403, "origin_forbidden", "proxy session requires an allowed Origin")
        # SameSite=Lax：阅读页内容渲染在无 allow-same-origin 的 sandbox iframe（opaque origin）中，
        # 其链接以 target=_top 跳转 /preview/view 时，浏览器把这次顶层导航的发起方视为跨站，
        # Strict 会话 cookie 会被拦截导致 401；Lax 仍覆盖顶层 GET 导航，
        # 而 api/render、api/save 均为 POST，跨站请求不携带 cookie，CSRF 边界不变。
        cookie = "{}={}; Path={}; HttpOnly; SameSite=Lax; Max-Age={}".format(
            PREVIEW_SESSION_COOKIE,
            preview_session_value(config.preview_secret(), config.preview_session_seconds),
            config.preview_prefix,
            config.preview_session_seconds,
        )
        if config.public_scheme == "https":
            cookie += "; Secure"
        self._send_empty(204, {"Set-Cookie": cookie})

    def _mcp_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin is None:
            return
        try:
            normalized = normalized_origin(origin, "Origin")
        except ServiceError as error:
            raise ServiceError(403, "origin_forbidden", "Origin is not allowed") from error
        if normalized not in self.service.config.allowed_origins:
            raise ServiceError(403, "origin_forbidden", "Origin is not allowed")

    def _authorized(self) -> None:
        token = self.service.config.token()
        if token is None:
            return
        value = self.headers.get("Authorization", "")
        if not hmac.compare_digest(value, "Bearer " + token):
            raise ServiceError(401, "unauthorized", "Bearer token is required")

    def _body(self, maximum: int) -> bytes:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError as error:
            raise ServiceError(400, "invalid_request", "Content-Length is invalid") from error
        if length < 0:
            raise ServiceError(411, "length_required", "Content-Length is required")
        if length > maximum:
            raise ServiceError(413, "request_too_large", "request body exceeds the configured limit")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ServiceError(400, "invalid_request", "request body is truncated")
        return body

    def _preview_request(self) -> Tuple[str, str]:
        value = parse_json(self._body(self.service.config.max_upload_bytes + 64 * 1024), "request body")
        if not isinstance(value, dict) or set(value) - {"path", "markdown"}:
            raise ServiceError(400, "invalid_json", "request body must contain path and markdown")
        relative = safe_relative_markdown_path(value.get("path"))
        markdown = value.get("markdown")
        if not isinstance(markdown, str):
            raise ServiceError(400, "invalid_markdown", "markdown must be a string")
        return relative, markdown

    def do_GET(self) -> None:
        try:
            path = self._path()
            if path == self.service.config.mcp_path:
                self._mcp_origin()
                self._authorized()
                self._send_empty(405, {"Allow": "POST"})
                return
            if path == "/healthz":
                self._send_json(200, {"ok": True, "server": SERVER_NAME, "version": SERVER_VERSION})
                return
            if path == "/v1/config":
                self._authorized()
                self._send_json(200, {"ok": True, "config": self.service.config.describe()})
                return
            if path.startswith(DEFAULT_ASSETS_PREFIX):
                self._serve_asset(path)
                return
            prefix = self.service.config.documents_prefix
            preview_prefix = self.service.config.preview_prefix
            if path.rstrip("/") == self.service.config.preview_path:
                if not self.service.config.preview_enabled:
                    raise ServiceError(404, "not_found", "preview is disabled")
                query = urlparse(self.path).query
                if any(item.partition("=")[0] == "token" for item in query.split("&")):
                    raise ServiceError(400, "query_auth_not_supported", "preview tokens must not be sent in URLs")
                if path == preview_prefix:
                    if not valid_preview_session(
                        self.service.config.preview_secret(), self._preview_cookie(),
                        self.service.config.preview_session_seconds,
                    ):
                        self._send_redirect(preview_prefix + "login")
                        return
                    current_dir = ""
                    for item in query.split("&"):
                        name, separator, value = item.partition("=")
                        if separator and name == "dir":
                            current_dir = unquote(value)
                            break
                    entries, truncated = self.service.preview.entries()
                    self._send_html(200, preview_index_page(
                        entries, self.service.config.preview_path,
                        self.service.config.preview_write_back, truncated, current_dir,
                        pinned_dirs=(self.service.config.public_directory,),
                    ))
                    return
                self._send_redirect(preview_prefix)
                return
            if path.startswith(preview_prefix):
                parsed = urlparse(self.path)
                if path == preview_prefix + "login":
                    self._send_html(200, preview_login_page(self.service.config.preview_path, self.service.config.preview_login_mode))
                    return
                self._authorized_preview()
                if path in (preview_prefix + "edit", preview_prefix + "view"):
                    relative = None
                    for item in parsed.query.split("&"):
                        name, separator, value = item.partition("=")
                        if separator and name == "path":
                            relative = unquote(value)
                            break
                    if relative is None:
                        raise ServiceError(400, "invalid_path", "path is required")
                    document = self.service.preview.read(relative)
                    if path == preview_prefix + "view":
                        rendered = self.service.preview.render(document["path"], document["markdown"])
                        entries, _ = self.service.preview.entries()
                        self._send_html(200, preview_reader_page(
                            document["path"], rendered, self.service.config.preview_path, entries,
                        ))
                        return
                    self._send_html(200, preview_editor_page(
                        document["path"], document["markdown"], self.service.config.preview_path,
                        self.service.config.preview_write_back,
                    ))
                    return
                raise ServiceError(404, "not_found", "preview route was not found")
            if path == prefix.rstrip("/") or path.startswith(prefix):
                self._serve_docs(path)
                return
            raise ServiceError(404, "not_found", "route was not found")
        except ServiceError as error:
            self._error(error)
        except OSError as error:
            self._error(ServiceError(500, "io_error", str(error)))

    def _serve_asset(self, path: str, head: bool = False) -> None:
        """Serve one manifest-whitelisted renderer asset; fingerprint pins the bytes."""
        remainder = path[len(DEFAULT_ASSETS_PREFIX):]
        fingerprint, separator, name = remainder.partition("/")
        if not separator or not name or "/" in name:
            raise ServiceError(404, "not_found", "asset was not found")
        content_type, body = read_resource_asset(self.service.config, fingerprint, name)
        self._send_bytes(200, body, {
            "Content-Type": content_type,
            # fingerprint 在 URL 里，版本更新会切换到新 URL。
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        }, head=head)

    def _serve_docs(self, path: str, head: bool = False) -> None:
        """Serve the public docs surface; any failure collapses to the HTML 404 page."""
        prefix = self.service.config.documents_prefix
        if path == prefix.rstrip("/"):
            self._send_redirect(prefix, status=308)
            return
        try:
            status, response_headers, body = self.service.public.serve(
                path[len(prefix):], self.headers.get("If-None-Match")
            )
        except ServiceError as error:
            if error.status != 404:
                # 真实原因留在服务端日志（journal），对外只暴露统一 404 页面。
                self.log_message("public docs failure collapsed to 404 page: %s %s", error.code, safe_log_value(path))
            status, response_headers, body = not_found_response()
        self._send_bytes(status, body, response_headers, head=head)

    def do_HEAD(self) -> None:
        """Public docs and renderer assets support HEAD; everything else 404s."""
        try:
            path = self._path()
            if path.startswith(DEFAULT_ASSETS_PREFIX):
                self._serve_asset(path, head=True)
                return
            prefix = self.service.config.documents_prefix
            if path == prefix.rstrip("/") or path.startswith(prefix):
                self._serve_docs(path, head=True)
                return
            raise ServiceError(404, "not_found", "route was not found")
        except ServiceError as error:
            self._error(error)
        except OSError as error:
            self._error(ServiceError(500, "io_error", str(error)))

    def do_DELETE(self) -> None:
        try:
            if self._path() == self.service.config.mcp_path:
                self._mcp_origin()
                self._authorized()
                self._send_empty(405, {"Allow": "POST"})
                return
            raise ServiceError(404, "not_found", "route was not found")
        except ServiceError as error:
            self._error(error)

    def do_POST(self) -> None:
        try:
            path = self._path()
            if path == self.service.config.preview_prefix + "session":
                self._create_preview_session()
                return
            if path == self.service.config.preview_prefix + "api/render":
                self._authorized_preview()
                relative, markdown = self._preview_request()
                self._send_json(
                    200,
                    {"path": relative, "html": self.service.preview.render(relative, markdown, link_target="_blank", editor_preview=True)},
                    maximum=MAX_PREVIEW_RESPONSE_BYTES,
                )
                return
            if path == self.service.config.preview_prefix + "api/save":
                self._authorized_preview()
                relative, markdown = self._preview_request()
                self._send_json(200, self.service.preview.save(relative, markdown))
                return
            if path == self.service.config.mcp_path:
                self._mcp_origin()
                self._authorized()
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    raise ServiceError(415, "unsupported_media_type", "MCP requests must use application/json")
                accept = self.headers.get("Accept", "").lower()
                if "application/json" not in accept or "text/event-stream" not in accept:
                    raise ServiceError(406, "not_acceptable", "MCP clients must accept both application/json and text/event-stream")
                body = self._body(self.service.config.max_rpc_bytes)
                try:
                    message = parse_json(body, "MCP request")
                except ServiceError:
                    self._send_json(400, self.service.mcp_service.rpc_error(None, -32700, "Parse error"))
                    return
                status, response = self.service.mcp_service.handle(message, self.headers)
                if response is not None:
                    self._send_json(status, response)
                else:
                    self._send_empty(status)
                return
            raise ServiceError(404, "not_found", "route was not found")
        except ServiceError as error:
            self._error(error)
        except OSError as error:
            self._error(ServiceError(500, "io_error", str(error)))


class AiDocsHTTPServer(http.server.ThreadingHTTPServer):
    """Threading server carrying validated configuration and the library store."""

    def __init__(self, config: ServiceConfig) -> None:
        if ":" in config.host:
            self.address_family = socket.AF_INET6
        try:
            super().__init__((config.host, config.port), AiDocsHandler)
        except OSError as error:
            raise ServiceError(503, "bind_failed", "cannot bind {}:{}: {}".format(config.host, config.port, error)) from error
        self.config = config
        self.render_capacity = threading.BoundedSemaphore(config.max_concurrent_renders)
        self.library = LibraryStore(config)
        self.preview = PreviewStore(config, self.render_capacity, self.library)
        self.public = PublicDocs(config, self.library)
        self.mcp_service = McpService(self.library, SERVER_NAME, SERVER_VERSION)
        self.daemon_threads = True

    request_queue_size = 64
    allow_reuse_address = True

    def get_request(self) -> Tuple[socket.socket, Any]:
        connection, address = super().get_request()
        connection.settimeout(self.config.request_timeout_seconds)
        return connection, address
