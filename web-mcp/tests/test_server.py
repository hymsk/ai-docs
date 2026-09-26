"""HTTP, storage, and MCP contract tests for the remote AI Docs service."""

import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from urllib.parse import quote as urlquote


WEB_MCP_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = WEB_MCP_ROOT.parent
SOURCE_ROOT = WEB_MCP_ROOT / "source"
sys.path.insert(0, str(SOURCE_ROOT))

from ai_docs_common import DEFAULT_ASSETS_PREFIX, renderer_fingerprint
from ai_docs_config import migrate_config_v1
from ai_docs_public import CacheEntry, RenderCache
from ai_docs_web import (
    AiDocsHTTPServer, ServiceConfig, ServiceError, normalized_origin,
    prepare_preview_html, preview_session_token, valid_preview_session,
)


class AiDocsServerTest(unittest.TestCase):
    """Exercise library publishing, authentication, preview, and both MCP eras."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.library = self.root / "library"
        self.public = self.library / "public"
        self.workspace.mkdir()
        self.library.mkdir()
        self.config_path = self.root / "server.json"
        self.config_path.write_text(json.dumps({
            "schema_version": 2,
            "workspace_root": str(self.workspace),
            "library_directory": str(self.library),
            "public_directory": "public",
            "server": {
                "host": "127.0.0.1",
                "port": 0,
                "public": {"scheme": "http", "host": "127.0.0.1", "port": 18765},
                "documents_prefix": "/docs/"
            },
            "preview": {"enabled": True, "write_back": True},
            "mcp": {
                "path": "/mcp",
                "reference": {
                    "scheme": "https",
                    "host": "docs.example.test",
                    "port": 443,
                    "path": "/custom-mcp",
                    "timeout_ms": 45000,
                    "token_env": "AI_DOCS_TEST_TOKEN"
                }
            },
            "renderer": {"node": str(Path(shutil.which("node")).resolve())},
            "max_upload_bytes": 5 * 1024 * 1024,
            "max_rpc_bytes": 6 * 1024 * 1024,
            "render_timeout_seconds": 120,
            "max_concurrent_renders": 2,
            "auth_required": True,
            "auth_token_env": "AI_DOCS_TEST_TOKEN",
            "allowed_origins": ["https://client.example.test"],
        }), encoding="utf-8")
        self.previous_config = os.environ.get("AI_DOCS_MCP_CONFIG")
        self.previous_token = os.environ.get("AI_DOCS_TEST_TOKEN")
        os.environ["AI_DOCS_MCP_CONFIG"] = str(self.config_path)
        os.environ["AI_DOCS_TEST_TOKEN"] = "test-token"
        self.config = ServiceConfig.load()
        self.server = AiDocsHTTPServer(self.config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.previous_config is None:
            os.environ.pop("AI_DOCS_MCP_CONFIG", None)
        else:
            os.environ["AI_DOCS_MCP_CONFIG"] = self.previous_config
        if self.previous_token is None:
            os.environ.pop("AI_DOCS_TEST_TOKEN", None)
        else:
            os.environ["AI_DOCS_TEST_TOKEN"] = self.previous_token
        self.temporary.cleanup()

    def request(self, method, path, body=b"", content_type="application/json", token="test-token", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        request_headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        if token is not None:
            request_headers["Authorization"] = "Bearer " + token
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read()
        response_headers = {name.lower(): value for name, value in response.getheaders()}
        connection.close()
        return response.status, payload, response_headers

    def mcp(self, message, headers=None):
        request_headers = {"Accept": "application/json, text/event-stream"}
        request_headers.update(headers or {})
        return self.request("POST", "/mcp", json.dumps(message).encode("utf-8"), headers=request_headers)

    def publish(self, path="report.md", markdown="# Report\n\nGenerated.\n", **arguments):
        payload = {"path": path, "markdown": markdown}
        payload.update(arguments)
        status, response, unused_headers = self.mcp({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "publish_document", "arguments": payload},
        })
        self.assertEqual(status, 200, response)
        return json.loads(response)["result"]

    def list_documents(self, **arguments):
        status, response, unused_headers = self.mcp({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "list_documents", "arguments": arguments},
        })
        self.assertEqual(status, 200, response)
        return json.loads(response)["result"]

    def preview_cookie(self, token="test-token"):
        status, payload, headers = self.request("POST", "/preview/session", token=token)
        self.assertEqual(status, 204, payload)
        cookie = headers.get("set-cookie", "")
        self.assertIn("ai_docs_preview=", cookie)
        return {"Cookie": cookie.split(";", 1)[0]}

    def library_file(self, relative, content):
        target = self.library / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def test_library_reader_is_private_live_and_does_not_publish(self):
        target = self.library_file("notes/中文 guide.md", "# First reading\n")
        route = "/preview/view?path=" + urlquote("notes/中文 guide.md", safe="")
        denied, _, _ = self.request("GET", route, token=None)
        self.assertEqual(denied, 401)
        cookie = self.preview_cookie()
        status, payload, headers = self.request("GET", route, token=None, headers=cookie)
        self.assertEqual(status, 200)
        self.assertIn(b"First reading", payload)
        self.assertIn(b"sandbox=\"allow-scripts allow-downloads allow-modals allow-popups "
                      b"allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation\"", payload)
        self.assertIn("no-store", headers["cache-control"])
        target.write_text("# Updated reading\n", encoding="utf-8")
        status, payload, _ = self.request("GET", route, headers=cookie)
        self.assertEqual(status, 200)
        self.assertIn(b"Updated reading", payload)
        self.assertFalse(self.public.exists())
        for relative, expected in [("../escape.md", 400), ("missing.md", 404)]:
            status, _, _ = self.request("GET", "/preview/view?path=" + urlquote(relative, safe=""), headers=cookie)
            self.assertEqual(status, expected)

    def test_proxy_login_bootstrap_keeps_bearer_and_origin_checks(self):
        self.config.preview_login_mode = "proxy"
        status, payload, _ = self.request("GET", "/preview/login", token=None)
        self.assertEqual(status, 200)
        self.assertIn(b'credentials:"same-origin"', payload)
        self.assertNotIn(b'id="token"', payload)
        self.assertNotIn(b'test-token', payload)
        status, _, _ = self.request("POST", "/preview/session", token=None, headers={"Origin": "https://client.example.test"})
        self.assertEqual(status, 401)
        for origin in [None, "https://evil.example"]:
            status, _, _ = self.request("POST", "/preview/session", headers={"Origin": origin} if origin else {})
            self.assertEqual(status, 403)
        status, _, headers = self.request("POST", "/preview/session", headers={"Origin": "https://client.example.test"})
        self.assertEqual(status, 204)
        self.assertIn("HttpOnly", headers["set-cookie"])

    def test_preview_reader_sibling_navigation_and_manual_refresh(self):
        # Creation order deliberately differs from the library's filename order.
        for name in ["notes/c.markdown", "notes/B.txt", "notes/a.md", "notes/deep/b.md",
                     "other/a.md", "root.md", "notes/.hidden.md", "notes/image.png"]:
            self.library_file(name, "# Example\n")
        (self.library / "notes/link.md").symlink_to(self.library / "root.md")
        cookie = self.preview_cookie()

        def page(name):
            status, payload, headers = self.request(
                "GET", "/preview/view?path=" + urlquote(name, safe=""), token=None, headers=cookie)
            self.assertEqual(status, 200)
            self.assertIn("no-store", headers["cache-control"])
            return payload.decode()

        middle = page("notes/B.txt")
        self.assertIn('rel="prev" href="/preview/view?path=notes%2Fa.md"', middle)
        self.assertIn('rel="next" href="/preview/view?path=notes%2Fc.markdown"', middle)
        self.assertNotIn("刷新最新内容", middle)
        self.assertNotIn("location.reload()", middle)
        first = page("notes/a.md")
        self.assertIn('disabled aria-label="上一篇"', first)
        self.assertNotIn('rel="prev"', first)
        last = page("notes/c.markdown")
        self.assertIn('disabled aria-label="下一篇"', last)
        self.assertNotIn('rel="next"', last)
        root = page("root.md")
        self.assertIn('disabled aria-label="上一篇"', root)
        self.assertIn('disabled aria-label="下一篇"', root)
        self.assertFalse(self.public.exists())

        # A normal new GET (browser refresh) sees saved content and membership.
        (self.library / "notes/c.markdown").unlink()
        self.library_file("notes/d.md", "# New neighbor\n")
        self.library_file("notes/B.txt", "# Updated manually\n")
        refreshed = page("notes/B.txt")
        self.assertIn('rel="next" href="/preview/view?path=notes%2Fd.md"', refreshed)
        self.assertIn("Updated manually", refreshed)

    def test_preview_reader_navigation_encodes_names_and_breaks_case_ties(self):
        for name in ["目录/a.md", "目录/A.md", '目录/中文 &"<>#.md']:
            self.library_file(name, "# Safe\n")
        cookie = self.preview_cookie()
        entries, _ = self.server.preview.entries()
        self.assertEqual([entry["path"] for entry in entries],
                         ["目录/A.md", "目录/a.md", '目录/中文 &"<>#.md'])
        status, payload, _ = self.request(
            "GET", "/preview/view?path=" + urlquote("目录/a.md", safe=""), token=None, headers=cookie)
        self.assertEqual(status, 200)
        page = payload.decode()
        self.assertIn('rel="prev" href="/preview/view?path=' + urlquote("目录/A.md", safe="") + '"', page)
        self.assertIn('rel="next" href="/preview/view?path=' + urlquote('目录/中文 &"<>#.md', safe="") + '"', page)
        self.assertIn('title="中文 &amp;&quot;&lt;&gt;#.md"', page)
        self.assertNotIn('title="中文 &"<>#.md"', page)

    def test_preview_index_pins_empty_public_directory(self):
        cookie = self.preview_cookie()
        status, payload, _ = self.request("GET", "/preview/", token=None, headers=cookie)
        self.assertEqual(status, 200)
        page = payload.decode()
        self.assertIn('href="/preview/?dir=public%2F"', page)

        status, payload, _ = self.request("GET", "/preview/?dir=public%2F", token=None, headers=cookie)
        self.assertEqual(status, 200)

    def test_preview_reader_title_links_parent_folders(self):
        self.library_file("notes/deep/guide.md", "# Guide\n")
        self.library_file("root.md", "# Root\n")
        cookie = self.preview_cookie()

        status, payload, _ = self.request(
            "GET", "/preview/view?path=" + urlquote("notes/deep/guide.md", safe=""), token=None, headers=cookie)
        self.assertEqual(status, 200)
        page = payload.decode()
        self.assertIn('class="brand-crumbs"', page)
        self.assertIn('<a href="/preview/">文档库</a>', page)
        self.assertIn('href="/preview/?dir=notes%2F"', page)
        self.assertIn('href="/preview/?dir=notes%2Fdeep%2F"', page)
        self.assertIn('aria-current="page">guide.md</span>', page)

        status, payload, _ = self.request("GET", "/preview/view?path=root.md", token=None, headers=cookie)
        self.assertEqual(status, 200)
        page = payload.decode()
        self.assertIn('class="brand-crumbs"', page)
        self.assertIn('<a href="/preview/">文档库</a>', page)
        self.assertIn('aria-current="page">root.md</span>', page)

    def test_preview_reader_title_escapes_folder_names(self):
        self.library_file('目录/中文 &"<>#/a.md', "# Safe\n")
        cookie = self.preview_cookie()
        status, payload, _ = self.request(
            "GET", "/preview/view?path=" + urlquote('目录/中文 &"<>#/a.md', safe=""), token=None, headers=cookie)
        self.assertEqual(status, 200)
        page = payload.decode()
        self.assertIn('<a href="/preview/">文档库</a>', page)
        self.assertIn('href="/preview/?dir=' + urlquote("目录/", safe="") + '"', page)
        self.assertIn('href="/preview/?dir=' + urlquote('目录/中文 &"<>#/', safe="") + '"', page)
        self.assertIn('>' + "中文 &amp;&quot;&lt;&gt;#" + '</a>', page)
        self.assertNotIn('>中文 &"<>#</a>', page)

    def test_library_browses_directories_with_leading_whitespace(self):
        # 目录名可合法包含前导空白；目录页不得做有损规范化后误报 400。
        self.library_file(" notes/guide.md", "# Guide\n")
        cookie = self.preview_cookie()
        encoded_dir = urlquote(" notes/", safe="")
        status, payload, _ = self.request("GET", "/preview/?dir=" + encoded_dir, headers=cookie)
        self.assertEqual(status, 200)
        self.assertIn('view?path=' + urlquote(" notes/guide.md", safe=""), payload.decode())
        # 阅读页标题中的文件夹链接指向同一目录，点击后必须仍可打开。
        status, payload, _ = self.request(
            "GET", "/preview/view?path=" + urlquote(" notes/guide.md", safe=""), headers=cookie)
        self.assertEqual(status, 200)
        self.assertIn('href="/preview/?dir=' + encoded_dir + '"', payload.decode())

    def test_request_log_escapes_decoded_control_characters(self):
        # 解码后的路径可含 %0a 等控制字符；日志必须转义，不能伪造多行记录。
        buffer = StringIO()
        with redirect_stderr(buffer):
            status, _, _ = self.request("GET", "/docs/%0aFORGED", token=None)
        self.assertEqual(status, 404)
        logged = buffer.getvalue()
        self.assertIn("\\u000a", logged)
        self.assertNotIn("\nFORGED", logged)

    def test_proxy_login_config_requires_loopback_and_authentication(self):
        data = json.loads(self.config_path.read_text())
        data["preview"]["login_mode"] = "proxy"
        for host, required in [("0.0.0.0", True), ("127.0.0.1", False)]:
            data["server"]["host"] = host
            data["auth_required"] = required
            self.config_path.write_text(json.dumps(data))
            with self.assertRaises(ServiceError):
                ServiceConfig.load()

    def test_library_navigation_browses_folders_and_links_reader_pages(self):
        self.library_file("notes/deep/guide.md", "# Guide\n")
        status, payload, _ = self.request("GET", "/preview/", headers=self.preview_cookie())
        self.assertEqual(status, 200)
        for marker in [b'id="library-search"', b'class="breadcrumbs"', b'?dir=notes%2F', b'role="status"']:
            self.assertIn(marker, payload)
        self.assertNotIn(b'view?path=notes%2Fdeep%2Fguide.md', payload)
        status, payload, _ = self.request("GET", "/preview/?dir=notes%2Fdeep%2F", headers=self.preview_cookie())
        self.assertEqual(status, 200)
        for marker in [b'view?path=notes%2Fdeep%2Fguide.md', b'edit?path=notes%2Fdeep%2Fguide.md', b'aria-current="page">deep']:
            self.assertIn(marker, payload)
        for bad_dir in ["..%2F", "missing%2F"]:
            status, _, _ = self.request("GET", "/preview/?dir=" + bad_dir, headers=self.preview_cookie())
            self.assertEqual(status, 400)

    def test_preview_reader_injects_client_side_link_helper(self):
        # 渲染器把 Markdown 交给浏览器端转换，锚点只在客户端出现；
        # 链接改写由注入 srcdoc 的 helper 脚本完成，服务端只注入上下文。
        self.library_file("notes/guide.md", "# 指南\n\n[同级](sibling.md)\n")
        cookie = self.preview_cookie()
        status, payload, _ = self.request(
            "GET", "/preview/view?path=" + urlquote("notes/guide.md", safe=""), token=None, headers=cookie
        )
        self.assertEqual(status, 200)
        page = payload.decode("utf-8")
        # srcdoc 属性经过 HTML 转义，helper 上下文中的双引号呈现为 &quot;
        self.assertIn(
            '&quot;path&quot;:&quot;notes/guide.md&quot;,'
            '&quot;viewBase&quot;:&quot;/preview/view?path=&quot;,'
            '&quot;target&quot;:&quot;_top&quot;',
            page,
        )
        self.assertIn("decodeURIComponent", page)
        self.assertIn("noopener noreferrer", page)
        # 阅读页把 URL 片段接力给 iframe 内的锚点滚动
        self.assertIn('id="reader-frame"', page)
        self.assertIn("ai-docs-scroll", page)
        self.assertNotIn('html { scroll-behavior: auto; } .container { animation: none; }', page)

        render_body = json.dumps({"path": "notes/guide.md", "markdown": "[同级](sibling.md)\n"}).encode("utf-8")
        status, payload, _ = self.request("POST", "/preview/api/render", render_body, headers=cookie)
        self.assertEqual(status, 200, payload)
        rendered = json.loads(payload)
        # 编辑器预览在新标签页打开链接，避免离开编辑会话
        self.assertIn(
            '{"path":"notes/guide.md","viewBase":"/preview/view?path=","target":"_blank"}',
            rendered["html"],
        )
        self.assertIn('http-equiv="Content-Security-Policy"', rendered["html"])
        self.assertIn('html { scroll-behavior: auto; } .container { animation: none; }', rendered["html"])
        self.assertIn("type: 'ai-docs-scroll-state'", rendered["html"])
        self.assertIn("type: 'ai-docs-scroll-restored'", rendered["html"])
        self.assertIn("document.getElementById(state.id)", rendered["html"])
        self.assertLess(rendered["html"].index('animation: viewer-in 260ms'),
                        rendered["html"].index('.container { animation: none; }'))
        self.assertLess(rendered["html"].index('.container { animation: none; }'),
                        rendered["html"].index('</head>'))

    def test_prepare_preview_html_anchors_real_body_close_tag(self):
        # 内联 vendor 脚本可能含有 "</body></html>" 字符串（如 DOMPurify），
        # helper 必须注入文档末尾真正的 </body> 之前，不能插进 JS 字符串字面量。
        crafted = (
            '<!doctype html><html><head></head><body>'
            '<script>var s="</body></html>";</script>'
            '<script>console.log("bootstrap");</script>'
            '</body></html>'
        )
        result = prepare_preview_html(crafted, "guide.md", "/preview/", "_top")
        self.assertIn('var s="</body></html>";', result)
        self.assertEqual(result.count("</body>"), 2)
        helper_at = result.find("ai-docs-scroll")
        self.assertGreater(helper_at, result.find("bootstrap"))
        self.assertLess(helper_at, result.rindex("</body>"))

    def test_publish_document_writes_into_public_root_with_auth_and_cas(self):
        publish_call = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "publish_document", "arguments": {"path": "guide/intro.md", "markdown": "# Intro\n"}},
        }
        body = json.dumps(publish_call).encode("utf-8")
        denied_status, denied_payload, _ = self.request(
            "POST", "/mcp", body, token=None, headers={"Accept": "application/json, text/event-stream"}
        )
        self.assertEqual(denied_status, 401)
        self.assertEqual(json.loads(denied_payload)["error"]["code"], "unauthorized")
        self.assertFalse(self.public.exists())

        result = self.publish("guide/intro.md", "# Intro\n")
        self.assertFalse(result["isError"])
        content = result["structuredContent"]
        self.assertEqual(content["path"], "guide/intro.md")
        self.assertEqual(content["status"], "created")
        self.assertEqual(content["public_url"], "http://127.0.0.1:18765/docs/guide/intro")
        self.assertEqual(content["render_status"], "not_checked")
        written = self.public / "guide" / "intro.md"
        self.assertEqual(written.read_text(encoding="utf-8"), "# Intro\n")
        self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o600)

        conflict = self.publish("guide/intro.md", "# Other\n")
        self.assertTrue(conflict["isError"])
        error = conflict["structuredContent"]["error"]
        self.assertEqual(error["code"], "document_exists")
        self.assertEqual(error["details"]["sha256"], content["sha256"])
        self.assertEqual(written.read_text(encoding="utf-8"), "# Intro\n")

        stale = self.publish("guide/intro.md", "# Other\n", overwrite=True, expected_sha256="0" * 64)
        self.assertTrue(stale["isError"])
        self.assertEqual(stale["structuredContent"]["error"]["code"], "version_conflict")
        replaced = self.publish("guide/intro.md", "# Other\n", overwrite=True, expected_sha256=content["sha256"])
        self.assertFalse(replaced["isError"])
        self.assertEqual(replaced["structuredContent"]["status"], "replaced")
        unchanged = self.publish("guide/intro.md", "# Other\n", overwrite=True)
        self.assertEqual(unchanged["structuredContent"]["status"], "unchanged")

        mismatched_arguments = self.publish("guide/intro.md", "# Other\n", expected_sha256=content["sha256"])
        self.assertTrue(mismatched_arguments["isError"])
        self.assertEqual(mismatched_arguments["structuredContent"]["error"]["code"], "invalid_argument")

    def test_publish_validates_paths_and_enforces_public_sub_quota(self):
        for bad_path in ("../escape.md", "/absolute.md", "a//b.md", "notes.exe", ""):
            with self.subTest(bad_path=bad_path):
                result = self.publish(bad_path, "# x\n")
                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["code"], "invalid_path")
        self.assertFalse(self.public.exists())

        self.config.public_max_files = 1
        first = self.publish("one.md", "1")
        self.assertFalse(first["isError"])
        over = self.publish("two.md", "2")
        self.assertTrue(over["isError"])
        self.assertEqual(over["structuredContent"]["error"]["code"], "library_quota_exceeded")
        self.assertIn("public_docs.max_files", over["structuredContent"]["error"]["message"])
        self.assertFalse((self.public / "two.md").exists())

    def test_list_documents_filters_paginates_and_maps_urls(self):
        self.publish("README.md", "# Home\n")
        self.publish("guide/intro.md", "# Intro\n")
        self.publish("guide/deep/more.md", "# More\n")

        listed = self.list_documents()
        self.assertFalse(listed["isError"])
        content = listed["structuredContent"]
        self.assertEqual(content["count"], 3)
        paths = [entry["path"] for entry in content["documents"]]
        self.assertEqual(paths, ["guide/deep/more.md", "guide/intro.md", "README.md"])
        self.assertNotIn("next_cursor", content)
        by_path = {entry["path"]: entry for entry in content["documents"]}
        self.assertEqual(by_path["README.md"]["public_url"], "http://127.0.0.1:18765/docs/")
        self.assertEqual(by_path["guide/intro.md"]["public_url"], "http://127.0.0.1:18765/docs/guide/intro")
        self.assertEqual(by_path["guide/deep/more.md"]["sha256"], hashlib.sha256(b"# More\n").hexdigest())

        filtered = self.list_documents(prefix="guide")["structuredContent"]
        self.assertEqual([entry["path"] for entry in filtered["documents"]], ["guide/deep/more.md", "guide/intro.md"])
        shallow = self.list_documents(prefix="guide", recursive=False)["structuredContent"]
        self.assertEqual([entry["path"] for entry in shallow["documents"]], ["guide/intro.md"])

        first_page = self.list_documents(limit=2)["structuredContent"]
        self.assertEqual([entry["path"] for entry in first_page["documents"]], ["guide/deep/more.md", "guide/intro.md"])
        second_page = self.list_documents(limit=2, cursor=first_page["next_cursor"])["structuredContent"]
        self.assertEqual([entry["path"] for entry in second_page["documents"]], ["README.md"])
        self.assertNotIn("next_cursor", second_page)

        bad_cursor = self.list_documents(cursor="!!!")
        self.assertTrue(bad_cursor["isError"])
        self.assertEqual(bad_cursor["structuredContent"]["error"]["code"], "invalid_cursor")
        bad_limit = self.list_documents(limit=0)
        self.assertTrue(bad_limit["isError"])
        self.assertEqual(bad_limit["structuredContent"]["error"]["code"], "invalid_argument")
        bad_prefix = self.list_documents(prefix="../outside")
        self.assertTrue(bad_prefix["isError"])
        self.assertEqual(bad_prefix["structuredContent"]["error"]["code"], "invalid_path")

    def test_public_docs_serve_live_markdown_raw_sources_and_directory_indexes(self):
        self.publish("README.md", "# Home\n\n[指南](guide/intro.md)\n")
        self.publish("guide/intro.md", "# Intro\n\n[首页](../README.md)\n")
        self.publish("guide/deep/more.md", "# More\n")
        self.publish("notes.txt", "plain text\n")
        self.publish("paper.markdown", "# Paper\n")

        status, payload, headers = self.request("GET", "/docs/", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
        self.assertEqual(headers["cache-control"], "private, max-age=0, must-revalidate")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertIn("default-src 'none'", headers["content-security-policy"])
        self.assertTrue(headers["etag"].startswith('"'))
        self.assertIn(b"Home", payload)
        # 链接助手把相对 .md 链接改写到 /docs 空间（顶层页面不经 srcdoc 转义）
        page = payload.decode("utf-8")
        self.assertIn('{"path":"README.md","docsBase":"/docs/"}', page)
        self.assertIn("publicUrl", page)

        status, _, headers = self.request("GET", "/docs", token=None)
        self.assertEqual(status, 308)
        self.assertEqual(headers["location"], "/docs/")

        status, payload, _ = self.request("GET", "/docs/guide/intro", token=None)
        self.assertEqual(status, 200)
        self.assertIn(b"Intro", payload)

        # 无 README 的目录不跳转，直接 404；补上 README 后 308 → 目录索引
        status, _, _ = self.request("GET", "/docs/guide", token=None)
        self.assertEqual(status, 404)
        self.publish("guide/README.md", "# Guide index\n")
        status, _, headers = self.request("GET", "/docs/guide", token=None)
        self.assertEqual(status, 308)
        self.assertEqual(headers["location"], "/docs/guide/")
        status, payload, _ = self.request("GET", "/docs/guide/", token=None)
        self.assertEqual(status, 200)
        self.assertIn(b"Guide index", payload)

        # 带后缀路径返回原文；.markdown/.txt 只有原文形式
        status, payload, headers = self.request("GET", "/docs/guide/intro.md", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "text/markdown; charset=utf-8")
        self.assertEqual(payload, "# Intro\n\n[首页](../README.md)\n".encode("utf-8"))
        status, payload, headers = self.request("GET", "/docs/paper.markdown", token=None)
        self.assertEqual(headers["content-type"], "text/markdown; charset=utf-8")
        status, _, _ = self.request("GET", "/docs/paper", token=None)
        self.assertEqual(status, 404)
        status, payload, headers = self.request("GET", "/docs/notes.txt", token=None)
        self.assertEqual(headers["content-type"], "text/plain; charset=utf-8")

        status, _, _ = self.request("GET", "/docs/missing", token=None)
        self.assertEqual(status, 404)
        status, payload, headers = self.request("GET", "/docs/missing/", token=None)
        self.assertEqual(status, 404)
        # 缺失页面返回统一 HTML 404 页面，而非 JSON 错误；不含任何导航链接
        self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn(b"<title>404", payload)
        self.assertNotIn(b"<a ", payload)

    def test_public_docs_reject_traversal_and_hidden_segments(self):
        self.publish("guide/intro.md", "# Intro\n")
        for candidate in (
            "/docs/../server.json",
            "/docs/%2e%2e/secret.md",
            "/docs/.hidden",
            "/docs/guide//intro",
            "/docs/.git/",
        ):
            with self.subTest(candidate=candidate):
                # 公共面失败统一塌缩为 HTML 404 页面，不泄露路径校验细节
                status, payload, headers = self.request("GET", candidate, token=None)
                self.assertEqual(status, 404)
                self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
                self.assertIn(b"<title>404", payload)

    def test_public_docs_revalidate_with_etag_and_reflect_edits_and_deletes(self):
        self.publish("guide/intro.md", "# Intro\n")
        status, payload, headers = self.request("GET", "/docs/guide/intro", token=None)
        self.assertEqual(status, 200)
        etag = headers["etag"]
        status, payload, _ = self.request("GET", "/docs/guide/intro", token=None, headers={"If-None-Match": etag})
        self.assertEqual(status, 304)
        self.assertEqual(payload, b"")

        raw_status, _, raw_headers = self.request("GET", "/docs/guide/intro.md", token=None)
        self.assertEqual(raw_status, 200)
        raw_etag = raw_headers["etag"]
        raw_status, raw_payload, _ = self.request(
            "GET", "/docs/guide/intro.md", token=None, headers={"If-None-Match": raw_etag}
        )
        self.assertEqual(raw_status, 304)
        self.assertEqual(raw_payload, b"")

        # 编辑后源 sha256 变化 → 缓存键变化 → 旧 etag 不再命中
        self.publish("guide/intro.md", "# Updated\n", overwrite=True)
        status, payload, headers = self.request("GET", "/docs/guide/intro", token=None, headers={"If-None-Match": etag})
        self.assertEqual(status, 200)
        self.assertIn(b"Updated", payload)
        self.assertNotEqual(headers["etag"], etag)

        # HEAD 与 GET 走同一解析与缓存，返回相同 etag 但无正文
        head_status, head_payload, head_headers = self.request("HEAD", "/docs/guide/intro", token=None)
        self.assertEqual(head_status, 200)
        self.assertEqual(head_payload, b"")
        self.assertEqual(head_headers["etag"], headers["etag"])
        self.assertEqual(head_headers["content-type"], "text/html; charset=utf-8")

        # 删除后即使携带最新 etag 也必须 404
        (self.public / "guide" / "intro.md").unlink()
        status, _, _ = self.request("GET", "/docs/guide/intro", token=None, headers={"If-None-Match": headers["etag"]})
        self.assertEqual(status, 404)

        # 缺失文档的 HEAD 同样返回 404（无正文）
        head_status, head_payload, head_headers = self.request("HEAD", "/docs/guide/intro", token=None)
        self.assertEqual(head_status, 404)
        self.assertEqual(head_payload, b"")
        self.assertEqual(head_headers["content-type"], "text/html; charset=utf-8")

    def test_public_render_cache_is_byte_bounded_and_entry_limited(self):
        cache = RenderCache(100, 2, 40)

        def entry(body):
            return CacheEntry(body=body, etag='"x"')

        cache.put(("a", "", "", ""), entry(b"1" * 30))
        cache.put(("b", "", "", ""), entry(b"2" * 30))
        self.assertIsNotNone(cache.get(("a", "", "", "")))
        cache.put(("c", "", "", ""), entry(b"3" * 30))
        self.assertIsNone(cache.get(("b", "", "", "")))
        self.assertIsNotNone(cache.get(("a", "", "", "")))
        cache.put(("oversized", "", "", ""), entry(b"4" * 50))
        self.assertIsNone(cache.get(("oversized", "", "", "")))
        # 前面 get(a) 已把 a 移到尾部，LRU 前端是 c
        cache.put(("e", "", "", ""), entry(b"5" * 30))
        self.assertIsNone(cache.get(("c", "", "", "")))
        self.assertIsNotNone(cache.get(("a", "", "", "")))
        self.assertEqual(len(cache), 2)

    def test_public_render_capacity_is_separate_and_serves_404_page_when_busy(self):
        self.publish("busy.md", "# busy\n")
        self.assertTrue(self.server.public.capacity.acquire(blocking=False))
        try:
            status, payload, headers = self.request("GET", "/docs/busy", token=None)
        finally:
            self.server.public.capacity.release()
        # 过载对公共访问者只呈现 404 页面；render_busy 细节留在服务端日志
        self.assertEqual(status, 404)
        self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
        self.assertIn(b"<title>404", payload)
        # 预览渲染容量与公共渲染容量相互独立
        self.assertTrue(self.server.render_capacity.acquire(blocking=False))
        self.server.render_capacity.release()

    def test_invalid_unicode_and_non_finite_json_are_client_errors(self):
        # 孤立代理项能通过 JSON 解析，但在 Markdown UTF-8 编码处被拒绝，
        # 经 tools/call 的 isError 通道返回，而不是 HTTP 层错误。
        invalid_unicode = (
            b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":'
            b'{"name":"publish_document","arguments":{"path":"document.md","markdown":"\\ud800"}}}'
        )
        status, payload, unused_headers = self.request(
            "POST", "/mcp", invalid_unicode, headers={"Accept": "application/json, text/event-stream"}
        )
        self.assertEqual(status, 200)
        unicode_result = json.loads(payload)["result"]
        self.assertTrue(unicode_result["isError"])
        self.assertEqual(unicode_result["structuredContent"]["error"]["code"], "invalid_encoding")
        self.assertFalse(self.public.exists())

        non_finite = b'{"jsonrpc":"2.0","id":2,"method":"ping","params":{"value":NaN}}'
        finite_status, finite_payload, unused_headers = self.request(
            "POST", "/mcp", non_finite, headers={"Accept": "application/json, text/event-stream"}
        )
        self.assertEqual(finite_status, 400)
        self.assertEqual(json.loads(finite_payload)["error"]["code"], -32700)

    def test_graphviz_fence_degrades_to_code_block_without_exposing_temporary_paths(self):
        cookie = self.preview_cookie()
        body = json.dumps({
            "path": "graph.md",
            "markdown": "# Graph\n\n```dot\ndigraph G { A -> B }\n```\n",
        }).encode("utf-8")

        status, payload, unused_headers = self.request("POST", "/preview/api/render", body, headers=cookie)

        rendered = json.loads(payload)["html"]
        self.assertEqual(status, 200)
        self.assertIn("graph.md:3: 不支持 dot/graphviz 图表代码块", rendered)
        self.assertIn("code-chart-badge", rendered)
        self.assertNotIn(str(self.library), rendered)
        self.assertNotIn(".ai-docs-preview-", rendered)

    def test_opencode_legacy_streamable_http_sequence(self):
        initialize = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        }
        status, payload, unused_headers = self.mcp(initialize)
        initialized = json.loads(payload)
        notification_status, notification_payload, notification_headers = self.mcp({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }, {"MCP-Protocol-Version": "2025-11-25"})
        tools_status, tools_payload, unused_headers = self.mcp(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"MCP-Protocol-Version": "2025-11-25"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(initialized["result"]["capabilities"], {"tools": {}})
        self.assertEqual(notification_status, 202)
        self.assertEqual(notification_payload, b"")
        self.assertEqual(notification_headers["content-length"], "0")
        self.assertEqual(tools_status, 200)
        self.assertEqual(
            [item["name"] for item in json.loads(tools_payload)["result"]["tools"]],
            ["publish_document", "list_documents"],
        )

    def test_mcp_parse_error_accept_contract_and_initialize_validation(self):
        parse_status, parse_payload, unused_headers = self.request(
            "POST", "/mcp", b"{", headers={"Accept": "application/json, text/event-stream"}
        )
        accept_status, accept_payload, unused_headers = self.request(
            "POST", "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}).encode("utf-8"),
            headers={"Accept": "application/json"},
        )
        initialize_status, initialize_payload, unused_headers = self.mcp({
            "jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}
        })
        self.assertEqual(parse_status, 400)
        self.assertEqual(json.loads(parse_payload)["error"]["code"], -32700)
        self.assertEqual(accept_status, 406)
        self.assertEqual(json.loads(accept_payload)["error"]["code"], "not_acceptable")
        self.assertEqual(initialize_status, 200)
        self.assertEqual(json.loads(initialize_payload)["error"]["code"], -32602)

    def test_legacy_mcp_can_publish_and_list(self):
        publish_request = {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "publish_document", "arguments": {"path": "mcp.md", "markdown": "# MCP"}},
        }
        status, payload, unused_headers = self.mcp(publish_request, {"MCP-Protocol-Version": "2025-11-25"})
        result = json.loads(payload)["result"]
        self.assertEqual(status, 200)
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["status"], "created")
        query_status, query_payload, unused_headers = self.mcp({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "list_documents", "arguments": {}},
        }, {"MCP-Protocol-Version": "2025-11-25"})
        self.assertEqual(query_status, 200)
        listed = json.loads(query_payload)["result"]["structuredContent"]
        self.assertEqual([entry["path"] for entry in listed["documents"]], ["mcp.md"])

        unknown_status, unknown_payload, unused_headers = self.mcp({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "render_markdown", "arguments": {}},
        }, {"MCP-Protocol-Version": "2025-11-25"})
        self.assertEqual(unknown_status, 200)
        self.assertEqual(json.loads(unknown_payload)["error"]["code"], -32602)

    def test_modern_discovery_and_tools_list_validate_request_metadata(self):
        metadata = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        discover = {"jsonrpc": "2.0", "id": "discover", "method": "server/discover", "params": {"_meta": metadata}}
        status, payload, unused_headers = self.mcp(discover, {
            "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "server/discover"
        })
        listed_status, listed_payload, unused_headers = self.mcp({
            "jsonrpc": "2.0", "id": "tools", "method": "tools/list", "params": {"_meta": metadata}
        }, {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"})
        self.assertEqual(status, 200)
        self.assertIn("2025-11-25", json.loads(payload)["result"]["supportedVersions"])
        self.assertEqual(listed_status, 200)
        listed = json.loads(listed_payload)["result"]
        self.assertEqual(listed["resultType"], "complete")
        self.assertEqual(listed["ttlMs"], 0)

    def test_modern_header_mismatch_and_unsupported_version_are_rejected(self):
        metadata = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        mismatch_status, mismatch_payload, unused_headers = self.mcp({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": metadata}
        }, {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call"})
        unsupported_metadata = dict(metadata)
        unsupported_metadata["io.modelcontextprotocol/protocolVersion"] = "2099-01-01"
        unsupported_status, unsupported_payload, unused_headers = self.mcp({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": unsupported_metadata}
        }, {"MCP-Protocol-Version": "2099-01-01", "Mcp-Method": "tools/list"})
        self.assertEqual(mismatch_status, 400)
        self.assertEqual(json.loads(mismatch_payload)["error"]["code"], -32020)
        self.assertEqual(unsupported_status, 400)
        self.assertEqual(json.loads(unsupported_payload)["error"]["code"], -32022)

    def test_mcp_get_delete_and_origin_security(self):
        get_status, get_payload, get_headers = self.request("GET", "/mcp")
        delete_status, delete_payload, delete_headers = self.request("DELETE", "/mcp")
        forbidden_status, forbidden_payload, unused_headers = self.mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            {"Origin": "https://forbidden.example.test", "MCP-Protocol-Version": "2025-11-25"},
        )
        allowed_status, unused_payload, unused_headers = self.mcp(
            {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
            {"Origin": "https://client.example.test", "MCP-Protocol-Version": "2025-11-25"},
        )
        self.assertEqual((get_status, delete_status), (405, 405))
        self.assertEqual((get_payload, delete_payload), (b"", b""))
        self.assertEqual((get_headers["allow"], delete_headers["allow"]), ("POST", "POST"))
        self.assertEqual(forbidden_status, 403)
        self.assertEqual(json.loads(forbidden_payload)["error"]["code"], "origin_forbidden")
        self.assertEqual(allowed_status, 200)

    def test_path_traversal_and_unknown_document_are_rejected(self):
        # 公共访问面：穿越与未知文档统一塌缩为 HTML 404 页面
        status, payload, headers = self.request("GET", "/docs/../server.json")
        self.assertEqual(status, 404)
        self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
        self.assertIn(b"<title>404", payload)
        unknown_status, unknown_payload, unused_headers = self.request("GET", "/docs/not-a-real-doc/index.html")
        self.assertEqual(unknown_status, 404)
        self.assertIn(b"<title>404", unknown_payload)
        # MCP 工具面保持 JSON 错误契约
        traversal = self.publish("../escape.md", "# x\n")
        self.assertTrue(traversal["isError"])
        self.assertEqual(traversal["structuredContent"]["error"]["code"], "invalid_path")

    def test_origin_normalization_supports_domain_ipv4_and_ipv6(self):
        self.assertEqual(normalized_origin("https://docs.example.test", "test"), "https://docs.example.test")
        self.assertEqual(normalized_origin("http://192.0.2.10:18080", "test"), "http://192.0.2.10:18080")
        self.assertEqual(normalized_origin("http://[2001:db8::1]:18080", "test"), "http://[2001:db8::1]:18080")

    def test_required_token_and_server_exposure_configuration_are_validated(self):
        previous = os.environ.pop("AI_DOCS_TEST_TOKEN", None)
        try:
            with self.assertRaisesRegex(ServiceError, "environment variable is empty"):
                self.config.token()
        finally:
            if previous is not None:
                os.environ["AI_DOCS_TEST_TOKEN"] = previous

        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["server"]["host"] = "0.0.0.0"
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        exposed = ServiceConfig.load()
        self.assertEqual(exposed.host, "0.0.0.0")
        self.assertTrue(exposed.describe()["server"]["bind_exposed"])

        data["server"]["host"] = "https://invalid.example.test"
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "must not contain URL syntax"):
            ServiceConfig.load()

        data["server"]["host"] = "127.0.0.1:18080"
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "valid hostname, IPv4 address"):
            ServiceConfig.load()

    def test_server_and_mcp_reference_defaults_and_overrides_are_described(self):
        described = self.config.describe()
        self.assertEqual(described["schema_version"], 2)
        self.assertEqual(described["server"]["host"], "127.0.0.1")
        self.assertEqual(described["server"]["documents_prefix"], "/docs/")
        self.assertNotIn("static_prefix", described["server"])
        self.assertEqual(described["public_directory"], "public")
        self.assertEqual(described["public_root"], str(self.public))
        self.assertEqual(described["mcp"]["path"], "/mcp")
        self.assertEqual(described["mcp"]["reference"], {
            "name": "ai-docs",
            "scheme": "https",
            "host": "docs.example.test",
            "port": 443,
            "path": "/custom-mcp",
            "url": "https://docs.example.test/custom-mcp",
            "timeout_ms": 45000,
            "token_env": "AI_DOCS_TEST_TOKEN",
        })

    def test_server_and_mcp_sections_default_to_local_service(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data.pop("server")
        data["server"] = {
            "public": {"scheme": "http", "host": "127.0.0.1", "port": 18080}
        }
        data["mcp"] = {
            "reference": {"scheme": "http", "host": "127.0.0.1", "port": 18080, "path": "/mcp"}
        }
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        defaulted = ServiceConfig.load()
        self.assertEqual(defaulted.host, "127.0.0.1")
        self.assertEqual(defaulted.port, 18080)
        self.assertEqual(defaulted.documents_prefix, "/docs/")
        self.assertEqual(defaulted.public_directory, "public")
        self.assertEqual(defaulted.public_root, self.library / "public")
        self.assertEqual(defaulted.mcp_path, "/mcp")
        self.assertEqual(defaulted.mcp_reference["url"], "http://127.0.0.1:18080/mcp")
        self.assertFalse(defaulted.describe()["server"]["bind_exposed"])

    def test_external_renderer_configuration_is_rejected(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["renderer_dir"] = "/opt/external-renderer"
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "unknown configuration fields: renderer_dir"):
            ServiceConfig.load()

    def test_symlinked_configuration_parent_is_rejected(self):
        original = os.environ["AI_DOCS_MCP_CONFIG"]
        linked_parent = self.root.parent / (self.root.name + "-linked-config")
        linked_parent.symlink_to(self.root, target_is_directory=True)
        os.environ["AI_DOCS_MCP_CONFIG"] = str(linked_parent / "server.json")
        try:
            with self.assertRaisesRegex(ServiceError, "symlinked parent"):
                ServiceConfig.load()
        finally:
            os.environ["AI_DOCS_MCP_CONFIG"] = original
            linked_parent.unlink()

    def test_config_schema_v2_is_required_and_v1_fields_are_rejected(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data.pop("schema_version")
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "schema_version must be 2"):
            ServiceConfig.load()

        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["schema_version"] = 2
        data["documents_directory"] = str(self.root / "documents")
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "removed in schema v2"):
            ServiceConfig.load()

        data.pop("documents_directory")
        data.pop("library_directory")
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "library_directory is required"):
            ServiceConfig.load()

        data["library_directory"] = str(self.library)
        data["public_directory"] = ".."
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "public_directory"):
            ServiceConfig.load()

        data["public_directory"] = "docs"
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        relocated = ServiceConfig.load()
        self.assertEqual(relocated.public_root, self.library / "docs")

    def test_migrate_config_v1_rewrites_the_schema_without_side_effects(self):
        migrated = migrate_config_v1({
            "documents_directory": "/srv/ai-docs/data/public/docs",
            "static_directory": "/srv/ai-docs/data/public/static",
            "metadata_directory": "/srv/ai-docs/data/private/metadata",
            "library_directory": "/srv/ai-docs/data/private/library",
            "server": {"host": "127.0.0.1", "static_prefix": "/static/"},
            "preview": {"enabled": True, "max_files": 5, "max_total_bytes": 1024},
        })
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["library_directory"], "/srv/ai-docs/data/private/library")
        for removed in ("documents_directory", "static_directory", "metadata_directory"):
            self.assertNotIn(removed, migrated)
        self.assertNotIn("static_prefix", migrated["server"])
        self.assertEqual(migrated["library_limits"], {"max_files": 5, "max_total_bytes": 1024})
        self.assertEqual(migrated["preview"], {"enabled": True})

        derived = migrate_config_v1({"documents_directory": "/srv/ai-docs/data/public/docs"})
        self.assertEqual(derived["library_directory"], "/srv/ai-docs/data/private/library")

        with self.assertRaisesRegex(ServiceError, "only schema_version 1"):
            migrate_config_v1({"schema_version": 2})
        with self.assertRaisesRegex(ServiceError, "cannot derive library_directory"):
            migrate_config_v1({"schema_version": 1})

    def test_renderer_is_loaded_from_the_canonical_skill_directory(self):
        self.assertEqual(self.config.renderer_directory, SKILL_ROOT)
        self.assertTrue((self.config.renderer_directory / "scripts" / "build.js").is_file())
        self.assertTrue((self.config.renderer_directory / "scripts" / "vendor" / "markdown-it.min.js").is_file())

    def test_preview_uses_header_login_and_rejects_query_tokens_without_logging_them(self):
        missing_status, missing_payload, unused_headers = self.request("GET", "/preview/", token=None)
        self.assertEqual(missing_status, 303)
        self.assertEqual(unused_headers["location"], "/preview/login")

        login_status, login_payload, unused_headers = self.request("GET", "/preview/login", token=None)
        self.assertEqual(login_status, 200)
        self.assertIn(b'Authorization:"Bearer "+value', login_payload)

        rejected, rejected_payload, unused_headers = self.request("POST", "/preview/session", token="wrong")
        self.assertEqual(rejected, 401)
        self.assertEqual(json.loads(rejected_payload)["error"]["code"], "unauthorized")

        log = StringIO()
        with redirect_stderr(log):
            query_status, query_payload, unused_headers = self.request(
                "GET", "/preview/?token=do-not-log-this", token=None
            )
        self.assertEqual(query_status, 400)
        self.assertEqual(json.loads(query_payload)["error"]["code"], "query_auth_not_supported")
        self.assertNotIn("do-not-log-this", log.getvalue())
        self.assertIn('GET /preview/ HTTP/1.1', log.getvalue())

        accepted, unused_payload, headers = self.request("POST", "/preview/session")
        self.assertEqual(accepted, 204)
        cookie = headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Path=/preview/", cookie)
        self.assertNotIn("Secure", cookie)

        spoofed, unused_payload, spoofed_headers = self.request(
            "POST", "/preview/session", headers={"X-Forwarded-Proto": "https", "Forwarded": "proto=https"}
        )
        self.assertEqual(spoofed, 204)
        self.assertNotIn("Secure", spoofed_headers["set-cookie"])

        stale = {"Cookie": "ai_docs_preview=9999999999." + "0" * 64}
        stale_status, unused_payload, unused_headers = self.request("GET", "/preview/", token=None, headers=stale)
        self.assertEqual(stale_status, 303)

    def test_preview_https_configuration_sets_secure_cookie_without_proxy_headers(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["server"]["public"] = {"scheme": "https", "host": "docs.example.test", "port": 443}
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        secure_server = AiDocsHTTPServer(ServiceConfig.load())
        thread = threading.Thread(target=secure_server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", secure_server.server_address[1], timeout=30)
            connection.request("POST", "/preview/session", headers={
                "Authorization": "Bearer test-token", "Content-Length": "0", "X-Forwarded-Proto": "http",
            })
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 204)
            self.assertIn("Secure", response.getheader("Set-Cookie"))
            connection.close()
        finally:
            secure_server.shutdown()
            secure_server.server_close()
            thread.join(timeout=2)

    def test_preview_lists_and_renders_library_markdown_without_publishing(self):
        self.library_file("notes/guide.md", "# 指南\n\n正文。\n")
        self.library_file("top.md", "# Top\n")
        cookie = self.preview_cookie()

        status, payload, unused_headers = self.request("GET", "/preview/", token=None, headers=cookie)
        self.assertEqual(status, 200)
        page = payload.decode("utf-8")
        self.assertIn("top.md", page)
        self.assertIn('?dir=notes%2F', page)
        self.assertNotIn("notes/guide.md", page)

        status, payload, unused_headers = self.request("GET", "/preview/?dir=notes%2F", token=None, headers=cookie)
        self.assertEqual(status, 200)
        page = payload.decode("utf-8")
        self.assertIn("notes/guide.md", page)
        self.assertIn("/preview/edit?path=notes%2Fguide.md", page)

        editor_status, editor_payload, unused_headers = self.request(
            "GET", "/preview/edit?path=notes/guide.md", token=None, headers=cookie
        )
        self.assertEqual(editor_status, 200)
        editor = editor_payload.decode("utf-8")
        self.assertIn("Markdown 编辑器", editor)
        self.assertIn("渲染结果", editor)
        self.assertIn(
            'sandbox="allow-scripts allow-downloads allow-modals allow-popups allow-popups-to-escape-sandbox"',
            editor,
        )
        self.assertIn('data-base="/preview/"', editor)
        self.assertIn("type: 'ai-docs-scroll-sync'", editor)
        self.assertIn("type: 'ai-docs-scroll-restore'", editor)

        render_body = json.dumps({
            "path": "notes/guide.md",
            "markdown": "# 新标题\n\n```mermaid\nflowchart LR\n  A --> B\n```\n",
        }).encode("utf-8")
        render_status, render_payload, unused_headers = self.request(
            "POST", "/preview/api/render", render_body, headers=cookie
        )
        self.assertEqual(render_status, 200, render_payload)
        rendered = json.loads(render_payload)
        self.assertEqual(rendered["path"], "notes/guide.md")
        self.assertIn("新标题", rendered["html"])
        self.assertIn("mermaid", rendered["html"])
        self.assertNotIn("/static/", rendered["html"])
        self.assertIn('http-equiv="Content-Security-Policy"', rendered["html"])
        self.assertIn("connect-src &#x27;none&#x27;", rendered["html"])
        self.assertEqual((self.library / "notes" / "guide.md").read_text(encoding="utf-8"), "# 指南\n\n正文。\n")
        self.assertFalse(self.public.exists())

    def test_preview_save_writes_back_atomically_and_is_configurable(self):
        cookie = self.preview_cookie()
        save_body = json.dumps({"path": "deep/new.md", "markdown": "# 新建\n"}).encode("utf-8")
        status, payload, unused_headers = self.request("POST", "/preview/api/save", save_body, headers=cookie)
        self.assertEqual(status, 200, payload)
        created = json.loads(payload)
        self.assertTrue(created["saved"])
        self.assertEqual(created["path"], "deep/new.md")
        self.assertEqual((self.library / "deep" / "new.md").read_text(encoding="utf-8"), "# 新建\n")

        existing = self.library_file("keep.md", "# 旧\n")
        os.chmod(existing, 0o640)
        update_body = json.dumps({"path": "keep.md", "markdown": "# 新\n"}).encode("utf-8")
        update_status, unused_payload, unused_headers = self.request(
            "POST", "/preview/api/save", update_body, headers=cookie
        )
        self.assertEqual(update_status, 200)
        self.assertEqual(existing.read_text(encoding="utf-8"), "# 新\n")
        self.assertEqual(stat.S_IMODE(existing.stat().st_mode), 0o640)

        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["preview"]["write_back"] = False
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        readonly = AiDocsHTTPServer(ServiceConfig.load())
        readonly_thread = threading.Thread(target=readonly.serve_forever, daemon=True)
        readonly_thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", readonly.server_address[1], timeout=30)
            connection.request("POST", "/preview/session", headers={
                "Authorization": "Bearer test-token", "Content-Length": "0",
            })
            token_response = connection.getresponse()
            unused_token_payload = token_response.read()
            self.assertEqual(token_response.status, 204, unused_token_payload)
            cookie = token_response.getheader("Set-Cookie").split(";", 1)[0]
            connection.request("POST", "/preview/api/save", body=update_body, headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(update_body)),
                "Cookie": cookie,
            })
            response = connection.getresponse()
            readonly_payload = response.read()
            connection.close()
            self.assertEqual(response.status, 403, readonly_payload)
            self.assertEqual(json.loads(readonly_payload)["error"]["code"], "write_back_disabled")

            self.library_file("readonly.md", "# 只读\n")
            connection.request("GET", "/preview/edit?path=readonly.md", headers={
                "Cookie": cookie,
            })
            readonly_page = connection.getresponse()
            readonly_html = readonly_page.read()
            connection.close()
            self.assertEqual(readonly_page.status, 200)
            self.assertNotIn(b'id="save"', readonly_html)
            self.assertIn(b'id="editor"', readonly_html)
        finally:
            readonly.shutdown()
            readonly.server_close()
            readonly_thread.join(timeout=2)

    def test_preview_rejects_traversal_symlinks_and_non_markdown_paths(self):
        cookie = self.preview_cookie()
        outside = self.root / "outside.md"
        outside.write_text("# secret\n", encoding="utf-8")
        self.library_file("ok.md", "# ok\n")
        (self.library / "link.md").symlink_to(outside)
        (self.library / "linked").symlink_to(self.root)

        for candidate in (
            "../outside.md",
            "/etc/passwd",
            "notes/../../outside.md",
            "ok.htm",
            "link.md",
            "linked/anything.md",
            "",
        ):
            with self.subTest(candidate=candidate):
                status, payload, unused_headers = self.request(
                    "GET", "/preview/edit?path=" + urlquote(candidate, safe=""), token=None, headers=cookie
                )
                self.assertIn(status, {400, 404}, payload)

        render_body = json.dumps({"path": "../outside.md", "markdown": "# x\n"}).encode("utf-8")
        render_status, unused_payload, unused_headers = self.request(
            "POST", "/preview/api/render", render_body, headers=cookie
        )
        self.assertEqual(render_status, 400)

        save_body = json.dumps({"path": "../outside.md", "markdown": "# x\n"}).encode("utf-8")
        save_status, unused_payload, unused_headers = self.request(
            "POST", "/preview/api/save", save_body, headers=cookie
        )
        self.assertEqual(save_status, 400)
        self.assertEqual(outside.read_text(encoding="utf-8"), "# secret\n")

    def test_preview_is_absent_when_disabled(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["preview"]["enabled"] = False
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        disabled = ServiceConfig.load()
        self.assertFalse(disabled.preview_enabled)
        self.assertFalse(disabled.describe()["preview"]["enabled"])

        server = AiDocsHTTPServer(disabled)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
            for path in ("/preview", "/preview/", "/preview/?token=test-token", "/preview/api/save"):
                with self.subTest(path=path):
                    connection.request("GET", path)
                    response = connection.getresponse()
                    payload = response.read()
                    self.assertEqual(response.status, 404, payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_preview_rejects_a_short_session_secret_and_bad_configuration(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["preview"]["session_secret"] = "too-short"
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "preview.session_secret"):
            ServiceConfig.load()

        data["preview"] = {"enabled": "yes"}
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "preview.enabled must be boolean"):
            ServiceConfig.load()

        data["preview"] = {"enabled": True, "session_seconds": 10}
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "preview.session_seconds"):
            ServiceConfig.load()

        data["preview"] = {"enabled": True, "unknown": 1}
        self.config_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ServiceError, "unknown preview fields"):
            ServiceConfig.load()

    def test_preview_render_capacity_is_enforced_and_released(self):
        cookie = self.preview_cookie()
        body = json.dumps({"path": "busy.md", "markdown": "# busy\n"}).encode("utf-8")
        acquired = 0
        while self.server.render_capacity.acquire(blocking=False):
            acquired += 1
        self.assertEqual(acquired, self.config.max_concurrent_renders)
        try:
            preview_status, preview_payload, preview_headers = self.request(
                "POST", "/preview/api/render", body, headers=cookie
            )
        finally:
            for unused in range(acquired):
                self.server.render_capacity.release()
        self.assertEqual(preview_status, 429, preview_payload)
        self.assertEqual(preview_headers["retry-after"], "2")

        failed = json.dumps({"path": "bad.md", "markdown": "```echarts\n{invalid}\n```\n"}).encode("utf-8")
        failed_status, unused_payload, unused_headers = self.request(
            "POST", "/preview/api/render", failed, headers=cookie
        )
        self.assertEqual(failed_status, 422)
        self.assertTrue(self.server.render_capacity.acquire(blocking=False))
        self.server.render_capacity.release()

    def test_preview_save_enforces_library_quotas_for_create_update_and_concurrency(self):
        preview = self.server.preview
        self.config.library_max_files = 2
        self.config.library_max_total_bytes = 12
        self.config.library_max_path_depth = 2

        preview.save("a.md", "1234")
        preview.save("a.md", "123456")
        preview.save("dir/b.md", "12")
        with self.assertRaisesRegex(ServiceError, "max_files"):
            preview.save("c.md", "1")
        with self.assertRaisesRegex(ServiceError, "max_total_bytes"):
            preview.save("a.md", "12345678901")
        with self.assertRaisesRegex(ServiceError, "max_path_depth"):
            preview.save("too/deep/c.md", "1")
        self.assertEqual((self.library / "a.md").read_text(encoding="utf-8"), "123456")
        self.assertFalse((self.library / "c.md").exists())

        self.config.library_max_files = 3
        self.config.library_max_total_bytes = 100
        barrier = threading.Barrier(3)
        outcomes = []

        def create(relative):
            barrier.wait()
            try:
                preview.save(relative, "x")
                outcomes.append("saved")
            except ServiceError as error:
                outcomes.append(error.code)

        first = threading.Thread(target=create, args=("c.md",))
        second = threading.Thread(target=create, args=("d.md",))
        first.start()
        second.start()
        barrier.wait()
        first.join(timeout=2)
        second.join(timeout=2)
        self.assertEqual(sorted(outcomes), ["library_quota_exceeded", "saved"])
        entries, truncated = preview.entries()
        self.assertFalse(truncated)
        self.assertEqual(len(entries), 3)

        self.library_file("external.md", "outside quota")
        with self.assertRaisesRegex(ServiceError, "must be reduced manually"):
            preview.entries()
        self.assertTrue((self.library / "external.md").is_file())

    def test_preview_session_validation_matches_configured_12h_24h_and_7d(self):
        secret = "s" * 32
        now = int(time.time())
        for seconds in (12 * 60 * 60, 24 * 60 * 60, 7 * 24 * 60 * 60):
            with self.subTest(seconds=seconds):
                expires = now + seconds
                value = "{}.{}".format(expires, preview_session_token(secret, expires))
                self.assertTrue(valid_preview_session(secret, value, seconds))
                self.assertFalse(valid_preview_session(secret, value, seconds - 120))
        expired = now - 120
        expired_value = "{}.{}".format(expired, preview_session_token(secret, expired))
        self.assertFalse(valid_preview_session(secret, expired_value, 7 * 24 * 60 * 60))
        forged = "{}.{}".format(now + 3600, "0" * 64)
        self.assertFalse(valid_preview_session(secret, forged, 7 * 24 * 60 * 60))

    def test_preview_session_cookie_uses_configured_24h_and_7d_durations(self):
        for seconds in (24 * 60 * 60, 7 * 24 * 60 * 60):
            with self.subTest(seconds=seconds):
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                data["preview"]["session_seconds"] = seconds
                self.config_path.write_text(json.dumps(data), encoding="utf-8")
                configured = ServiceConfig.load()
                server = AiDocsHTTPServer(configured)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
                    connection.request("POST", "/preview/session", headers={
                        "Authorization": "Bearer test-token", "Content-Length": "0",
                    })
                    response = connection.getresponse()
                    response.read()
                    cookie = response.getheader("Set-Cookie")
                    self.assertEqual(response.status, 204)
                    self.assertIn("Max-Age={}".format(seconds), cookie)
                    value = cookie.split("ai_docs_preview=", 1)[1].split(";", 1)[0]
                    self.assertTrue(valid_preview_session(configured.preview_secret(), value, seconds))
                    connection.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_preview_csp_blocks_remote_subresources_but_keeps_links(self):
        cookie = self.preview_cookie()
        body = json.dumps({
            "path": "remote.md",
            "markdown": "# Remote\n\n![tracker](https://assets.example.test/pixel.png)\n\n[ordinary link](https://example.test/page)\n",
        }).encode("utf-8")
        status, payload, unused_headers = self.request("POST", "/preview/api/render", body, headers=cookie)
        self.assertEqual(status, 200, payload)
        rendered = json.loads(payload)["html"]
        self.assertIn("https://assets.example.test/pixel.png", rendered)
        self.assertIn("https://example.test/page", rendered)
        self.assertIn("img-src data: blob:", rendered)
        self.assertIn("connect-src &#x27;none&#x27;", rendered)
        # 引用型 HTML 需要同源脚本/样式；仍然拒绝任何远程源
        self.assertIn("script-src &#x27;unsafe-inline&#x27; &#x27;self&#x27;", rendered)
        self.assertIn("style-src &#x27;unsafe-inline&#x27; &#x27;self&#x27;", rendered)

    def test_renderer_assets_serve_whitelisted_files_with_fingerprinted_cache(self):
        fingerprint = renderer_fingerprint(self.config)
        assets = "{}{}/".format(DEFAULT_ASSETS_PREFIX, fingerprint)
        self.publish("README.md", "# Home\n\n```mermaid\ngraph TD; A-->B;\n```\n")
        status, payload, headers = self.request("GET", "/docs/", token=None)
        self.assertEqual(status, 200)
        page = payload.decode("utf-8")

        # 渲染产物只引用托管资源：大引擎排在 clientRuntime 之后以避免阻塞首屏
        self.assertIn(assets + "markdown-it.min.js", page)
        runtime_index = page.index("container.innerHTML = md.render(raw);")
        self.assertLess(page.index(assets + "markdown-it.min.js"), runtime_index)
        mermaid_index = page.index(assets + "mermaid.min.js")
        self.assertLess(runtime_index, mermaid_index)
        self.assertIn('data-defer-engine="mermaid"', page)
        self.assertNotIn("globalThis.mermaid", page, "引擎不应内联进 HTML")
        self.assertIn("script-src 'unsafe-inline' 'self'", headers["content-security-policy"])

        # 端点返回经 build.js 同套转换的字节，可长期缓存
        status, asset, asset_headers = self.request("GET", assets + "mermaid.min.js", token=None)
        self.assertEqual(status, 200)
        self.assertIn(b"mermaid", asset[:400])
        self.assertEqual(asset_headers["content-type"], "application/javascript; charset=utf-8")
        self.assertEqual(asset_headers["cache-control"], "public, max-age=31536000, immutable")
        self.assertEqual(asset_headers["x-content-type-options"], "nosniff")

        status, asset, asset_headers = self.request("GET", assets + "katex.min.css", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(asset_headers["content-type"], "text/css; charset=utf-8")

        status, d3, _ = self.request("GET", assets + "d3.min.js", token=None)
        self.assertEqual(status, 200)
        self.assertIn(b"var d3=globalThis.d3;", d3[-80:], "资源必须经过与内联一致的转换")

        status, body, _ = self.request("HEAD", assets + "markdown-it.min.js", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

        # 白名单外、坏路径、坏指纹都不可读；端点不参与 Bearer 鉴权（srcdoc 子资源无法携带 header）
        for bad_path in (
            assets + "build.js",
            DEFAULT_ASSETS_PREFIX + fingerprint + "/../build.js",
            DEFAULT_ASSETS_PREFIX + "not-a-fingerprint/markdown-it.min.js",
            DEFAULT_ASSETS_PREFIX + "extra/" + fingerprint + "/markdown-it.min.js",
            # 合法格式但与当前 renderer 不符的指纹同样 404（不得触发资源导出）
            DEFAULT_ASSETS_PREFIX + ("0" * 64) + "/markdown-it.min.js",
        ):
            status, _, _ = self.request("GET", bad_path, token=None)
            self.assertEqual(status, 404, bad_path)

    def test_renderer_asset_endpoint_rejects_missing_assets(self):
        fingerprint = renderer_fingerprint(self.config)
        assets = "{}{}/".format(DEFAULT_ASSETS_PREFIX, fingerprint)
        status, _, _ = self.request("GET", assets + "markdown-it.min.js", token=None)
        self.assertEqual(status, 200)
        # 未被文档选中的资源依然可服务（白名单是 manifest 而非页面选择结果）
        status, _, _ = self.request("GET", assets + "markmap-lib.browser.js", token=None)
        self.assertEqual(status, 200)
        status, _, _ = self.request("GET", DEFAULT_ASSETS_PREFIX, token=None)
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
