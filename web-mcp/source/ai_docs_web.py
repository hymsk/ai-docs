#!/usr/bin/env python3
"""Optional AI Docs Web publishing service with HTTP and MCP interfaces."""

from __future__ import annotations

import sys

# The installed runtime is hashed for drift detection; never litter it with
# __pycache__ bytecode from sibling module imports.
sys.dont_write_bytecode = True

import argparse
import json
import os
from typing import List, Optional

from ai_docs_common import DEFAULT_ASSETS_PREFIX, ServiceError, normalized_origin  # noqa: F401  (re-exported)
from ai_docs_config import ServiceConfig  # noqa: F401  (re-exported)
from ai_docs_http import AiDocsHTTPServer, configure_identity
from ai_docs_preview import (  # noqa: F401  (re-exported)
    prepare_preview_html, preview_session_token, valid_preview_session,
)

SERVER_NAME = "ai-docs-web"
SERVER_VERSION = "1.0.0rc1"

configure_identity(SERVER_NAME, SERVER_VERSION)


def serve_http() -> int:
    config = ServiceConfig.load()
    config.token()
    server = AiDocsHTTPServer(config)
    actual_host, actual_port = server.server_address[:2]
    sys.stdout.write("ai-docs-web listening on {}:{}\n".format(actual_host, actual_port))
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0



def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVER_NAME)
    subparsers = parser.add_subparsers(dest="action")
    subparsers.add_parser("serve", help="run the remote HTTP API and MCP endpoint")
    doctor = subparsers.add_parser("doctor", help="validate server configuration")
    doctor.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    try:
        config = ServiceConfig.load()
        if args.action == "serve":
            return serve_http()
        if args.action == "doctor":
            token_configured = config.token() is not None if config.auth_required else True
            writable = {
                "library_directory": os.access(config.library_directory, os.W_OK | os.X_OK),
                "public_root": os.access(config.public_root, os.W_OK | os.X_OK),
            }
            proxy_paths = [config.mcp_path, config.documents_prefix, DEFAULT_ASSETS_PREFIX, "/healthz"]
            if config.preview_enabled:
                proxy_paths.extend((config.preview_path, config.preview_prefix))
            payload = {"ok": token_configured and all(writable.values()), "server": {"name": SERVER_NAME, "version": SERVER_VERSION}, "config": config.describe(), "node": {"available": True, "executable": str(config.node_executable)}, "authentication": {"required": config.auth_required, "token_configured": token_configured}, "writable": writable, "nginx": {
                "proxy_paths": proxy_paths,
                "document_alias_path": config.documents_prefix,
                "public_root": str(config.public_root),
                "public_origin": config.public_origin,
            }, "mcp_reference": config.mcp_reference, "warnings": ["This process does not write or reload Nginx configuration."]}
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            return 0 if payload["ok"] else 1
        parser.print_help()
        return 0
    except ServiceError as error:
        sys.stderr.write("{}: {}\n".format(error.code, error.message))
        return 1



if __name__ == "__main__":
    raise SystemExit(main())
