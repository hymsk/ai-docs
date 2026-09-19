"""MCP protocol handling: JSON-RPC framing, era negotiation, and tool dispatch.

Transport concerns (Accept contract, auth, body limits) stay in ai_docs_http;
this module owns the protocol surface itself, including the tool catalog.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ai_docs_common import (
    DEFAULT_PROTOCOL_VERSION, LEGACY_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS, ServiceError, json_compact,
)
from ai_docs_library import LibraryStore


class McpService:
    """Remote MCP endpoint logic bound to the library store."""

    def __init__(self, library: LibraryStore, server_name: str, server_version: str) -> None:
        self.library = library
        self.server_name = server_name
        self.server_version = server_version

    @staticmethod
    def rpc_error(request_id: Any, code: int, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        error: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    @staticmethod
    def _tools() -> List[Dict[str, Any]]:
        return [
            {
                "name": "publish_document",
                "title": "Publish Document",
                "description": "Publish one UTF-8 Markdown document into the public docs folder; it is rendered live at its /docs URL",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Markdown path relative to the public docs root, e.g. guide/intro.md"},
                        "markdown": {"type": "string", "description": "UTF-8 Markdown source"},
                        "overwrite": {"type": "boolean", "description": "Replace an existing document (default false)"},
                        "expected_sha256": {"type": "string", "description": "SHA-256 of the existing document for optimistic concurrency; requires overwrite=true"},
                    },
                    "required": ["path", "markdown"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_documents",
                "title": "List Documents",
                "description": "List documents published in the public docs folder",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prefix": {"type": "string", "description": "Only list paths under this directory prefix"},
                        "recursive": {"type": "boolean", "description": "Recurse into subdirectories (default true)"},
                        "limit": {"type": "integer", "description": "Maximum documents per page (default 100, maximum 100)"},
                        "cursor": {"type": "string", "description": "Opaque cursor from a previous list_documents response"},
                    },
                    "additionalProperties": False,
                },
            },
        ]

    def _list_documents(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        prefix = arguments.get("prefix")
        if prefix is not None and not isinstance(prefix, str):
            raise ServiceError(400, "invalid_argument", "prefix must be a string")
        recursive = arguments.get("recursive", True)
        if not isinstance(recursive, bool):
            raise ServiceError(400, "invalid_argument", "recursive must be a boolean")
        limit = arguments.get("limit", 100)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ServiceError(400, "invalid_argument", "limit must be an integer between 1 and 100")
        cursor = arguments.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise ServiceError(400, "invalid_argument", "cursor must be a string")
        return self.library.list_documents(prefix, recursive, limit, cursor)

    def _modern_request(self, message: Dict[str, Any], headers: Any) -> Tuple[int, Optional[Dict[str, Any]]]:
        params = message.get("params", {})
        if not isinstance(params, dict):
            return 400, self.rpc_error(message.get("id"), -32602, "params must be an object")
        metadata = params.get("_meta")
        if not isinstance(metadata, dict):
            return 400, self.rpc_error(message.get("id"), -32602, "modern MCP requests require params._meta")
        version = metadata.get("io.modelcontextprotocol/protocolVersion")
        header_version = headers.get("MCP-Protocol-Version")
        if version != header_version:
            return 400, self.rpc_error(message.get("id"), -32020, "HeaderMismatch", {"header": "MCP-Protocol-Version"})
        if version != MODERN_PROTOCOL_VERSION:
            return 400, self.rpc_error(message.get("id"), -32022, "Unsupported protocol version", {"supported": list(SUPPORTED_PROTOCOL_VERSIONS), "requested": version})
        if not isinstance(metadata.get("io.modelcontextprotocol/clientInfo"), dict) or not isinstance(metadata.get("io.modelcontextprotocol/clientCapabilities"), dict):
            return 400, self.rpc_error(message.get("id"), -32602, "modern MCP requests require clientInfo and clientCapabilities metadata")
        method = message.get("method")
        if headers.get("Mcp-Method") != method:
            return 400, self.rpc_error(message.get("id"), -32020, "HeaderMismatch", {"header": "Mcp-Method"})
        if method == "tools/call" and headers.get("Mcp-Name") != params.get("name"):
            return 400, self.rpc_error(message.get("id"), -32020, "HeaderMismatch", {"header": "Mcp-Name"})
        return 200, None

    def handle(self, message: Any, headers: Any) -> Tuple[int, Optional[Dict[str, Any]]]:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return 400, self.rpc_error(None, -32600, "Invalid JSON-RPC request")
        request_id = message.get("id")
        method = message.get("method")
        if method is None and "id" in message and ("result" in message or "error" in message):
            return 202, None
        if not isinstance(method, str):
            return 400, self.rpc_error(request_id, -32600, "JSON-RPC method must be a string")
        is_notification = "id" not in message
        if is_notification:
            return 202, None
        params = message.get("params", {})
        if not isinstance(params, dict):
            return 200, self.rpc_error(request_id, -32602, "params must be an object")
        metadata = params.get("_meta")
        modern = (
            headers.get("MCP-Protocol-Version") == MODERN_PROTOCOL_VERSION
            or isinstance(metadata, dict) and "io.modelcontextprotocol/protocolVersion" in metadata
        )
        if modern:
            validation_status, error = self._modern_request(message, headers)
            if error is not None:
                return validation_status, error
        else:
            header_version = headers.get("MCP-Protocol-Version")
            if header_version and header_version not in LEGACY_PROTOCOL_VERSIONS:
                return 400, self.rpc_error(request_id, -32022, "Unsupported protocol version", {"supported": list(SUPPORTED_PROTOCOL_VERSIONS), "requested": header_version})
        if method == "initialize":
            if modern:
                return 404, self.rpc_error(request_id, -32601, "Method not found")
            requested_version = params.get("protocolVersion")
            if (
                not isinstance(requested_version, str)
                or not isinstance(params.get("capabilities"), dict)
                or not isinstance(params.get("clientInfo"), dict)
            ):
                return 200, self.rpc_error(request_id, -32602, "initialize requires protocolVersion, capabilities, and clientInfo")
            negotiated = requested_version if requested_version in LEGACY_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
            return 200, {"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.server_name, "version": self.server_version},
                "instructions": "Publish Markdown into the public docs folder with publish_document and inspect it with list_documents. Every document under the public folder is rendered live at its /docs URL; publish success does not guarantee the document renders.",
            }}
        if method == "ping":
            result: Dict[str, Any] = {"resultType": "complete"} if modern else {}
            return 200, {"jsonrpc": "2.0", "id": request_id, "result": result}
        if method == "server/discover":
            if not modern:
                return 200, self.rpc_error(request_id, -32601, "Method not found")
            return 200, {"jsonrpc": "2.0", "id": request_id, "result": {
                "resultType": "complete",
                "supportedVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
                "capabilities": {"tools": {}},
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": self.server_name, "version": self.server_version}},
                "instructions": "Publish one Markdown document into the public docs folder and receive its live /docs URL.",
                "ttlMs": 0,
                "cacheScope": "private",
            }}
        if method == "tools/list":
            result = {"tools": self._tools()}
            if modern:
                result.update({"resultType": "complete", "ttlMs": 0, "cacheScope": "private"})
            return 200, {"jsonrpc": "2.0", "id": request_id, "result": result}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return 200, self.rpc_error(request_id, -32602, "tools/call requires name and object arguments")
            try:
                if name == "publish_document":
                    if set(arguments) - {"path", "markdown", "overwrite", "expected_sha256"}:
                        raise ServiceError(400, "invalid_argument", "publish_document received unknown arguments")
                    markdown = arguments.get("markdown")
                    if not isinstance(markdown, str):
                        raise ServiceError(400, "invalid_markdown", "markdown must be a string")
                    result = self.library.publish(
                        arguments.get("path"),
                        markdown,
                        arguments.get("overwrite", False),
                        arguments.get("expected_sha256"),
                    )
                elif name == "list_documents":
                    if set(arguments) - {"prefix", "recursive", "limit", "cursor"}:
                        raise ServiceError(400, "invalid_argument", "list_documents received unknown arguments")
                    result = self._list_documents(arguments)
                else:
                    return 200, self.rpc_error(request_id, -32602, "Unknown tool: {}".format(name))
                tool_result: Dict[str, Any] = {"content": [{"type": "text", "text": json_compact(result)}], "structuredContent": result, "isError": False}
                if modern:
                    tool_result["resultType"] = "complete"
                return 200, {"jsonrpc": "2.0", "id": request_id, "result": tool_result}
            except ServiceError as error:
                error_payload = {"code": error.code, "message": error.message}
                if error.details:
                    error_payload["details"] = error.details
                result = {"error": error_payload}
                tool_result = {"content": [{"type": "text", "text": json_compact(result)}], "structuredContent": result, "isError": True}
                if modern:
                    tool_result["resultType"] = "complete"
                return 200, {"jsonrpc": "2.0", "id": request_id, "result": tool_result}
        status = 404 if modern else 200
        return status, self.rpc_error(request_id, -32601, "Method not found")
