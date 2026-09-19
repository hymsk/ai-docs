#!/usr/bin/env python3
"""Serve AI Docs output with Python's directory-browsing HTTP server."""

from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import sys
import threading
import webbrowser


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def fail(message: str) -> None:
    raise ValueError(message)


def read_config(config_path: pathlib.Path) -> tuple[dict, pathlib.Path]:
    absolute_path = pathlib.Path(os.path.abspath(config_path.expanduser()))
    try:
        value = json.loads(absolute_path.read_text(encoding="utf-8"))
    except OSError as error:
        fail(f"无法读取配置文件 {absolute_path}: {error}")
    except json.JSONDecodeError as error:
        fail(f"配置文件 {absolute_path} 不是有效 JSON: {error}")
    if not isinstance(value, dict):
        fail(f"配置文件 {absolute_path} 必须是 JSON 对象。")
    return value, absolute_path.parent


def config_object(config: dict, name: str, allowed_fields: set[str]) -> dict:
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        fail(f"配置项 {name} 必须是 JSON 对象。")
    unknown = set(value) - allowed_fields
    if unknown:
        fail(f"配置项 {name} 包含未知字段: {sorted(unknown)[0]}")
    return value


class SafeDirectoryHandler(http.server.SimpleHTTPRequestHandler):
    """Reject requests that resolve outside the configured root via symlinks."""

    def __init__(self, *args, directory: str, **kwargs):
        self.root_directory = pathlib.Path(directory).resolve()
        super().__init__(*args, directory=directory, **kwargs)

    def send_head(self):
        target = pathlib.Path(super().translate_path(self.path)).resolve()
        if target != self.root_directory and self.root_directory not in target.parents:
            self.send_error(403, "Path escapes server root")
            return None
        return super().send_head()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动支持目录浏览的 AI Docs 本地静态文件服务器。")
    parser.add_argument("-c", "--config", help="AI Docs JSON 配置文件")
    parser.add_argument("-d", "--directory", help="服务根目录")
    parser.add_argument("--host", help=f"监听地址（默认 {DEFAULT_HOST}）")
    parser.add_argument("-p", "--port", type=int, help=f"监听端口，0 表示自动分配（默认 {DEFAULT_PORT}）")
    open_group = parser.add_mutually_exclusive_group()
    open_group.add_argument("--open", dest="open_browser", action="store_true", help="启动后打开浏览器")
    open_group.add_argument("--no-open", dest="open_browser", action="store_false", help="启动后不打开浏览器")
    parser.set_defaults(open_browser=None)
    return parser.parse_args()


def resolve_options(args: argparse.Namespace) -> tuple[pathlib.Path, str, int, bool]:
    config = {}
    config_dir = pathlib.Path.cwd()
    if args.config:
        config, config_dir = read_config(pathlib.Path(args.config))

    output = config_object(config, "output", {"mode", "directory", "fileName"})
    server = config_object(config, "server", {"host", "port", "directory", "open"})

    configured_directory = server.get("directory", output.get("directory", "."))
    if not isinstance(configured_directory, str) or not configured_directory.strip():
        fail("server.directory 或 output.directory 必须是非空字符串。")
    directory = pathlib.Path(args.directory).resolve() if args.directory else (config_dir / configured_directory).resolve()
    if not directory.exists():
        fail(f"服务目录不存在: {directory}")
    if not directory.is_dir():
        fail(f"服务路径不是目录: {directory}")

    host = args.host if args.host is not None else server.get("host", DEFAULT_HOST)
    if not isinstance(host, str) or not host.strip():
        fail("server.host 必须是非空字符串。")
    host = host.strip()

    port = args.port if args.port is not None else server.get("port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or port < 0 or port > 65535:
        fail("server.port 必须是 0 到 65535 之间的整数。")

    open_browser = args.open_browser if args.open_browser is not None else server.get("open", False)
    if not isinstance(open_browser, bool):
        fail("server.open 必须是布尔值。")
    return directory, host, port, open_browser


def main() -> int:
    args = parse_args()
    try:
        directory, host, port, open_browser = resolve_options(args)
    except ValueError as error:
        print(f"启动失败: {error}", file=sys.stderr)
        return 1

    def handler(*handler_args, **handler_kwargs):
        return SafeDirectoryHandler(*handler_args, directory=str(directory), **handler_kwargs)
    try:
        server = http.server.ThreadingHTTPServer((host, port), handler)
    except OSError as error:
        print(f"启动失败: 无法监听 {host}:{port}: {error}", file=sys.stderr)
        return 1

    actual_port = server.server_address[1]
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url_host = f"[{browser_host}]" if ":" in browser_host and not browser_host.startswith("[") else browser_host
    url = f"http://{url_host}:{actual_port}/"
    print(f"服务目录: {directory}", flush=True)
    print(f"访问地址: {url}", flush=True)
    print("目录浏览: 已启用", flush=True)

    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止。", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
