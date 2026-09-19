#!/usr/bin/env python3
"""Optional Chromium smoke test; requires developer-only Python Playwright.

No global installation, public listener or persistent profile is created.
Use --chromium for an existing executable, otherwise Playwright's cached one.
"""

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ai-docs-browser-") as temporary:
        directory = Path(temporary)
        for mode in ("single", "multi"):
            subprocess.run(["node", str(ROOT / "scripts/build.js"), "--input", str(ROOT / "assets/full-example.md"),
                            "--output", str(directory / (mode + ".html")), "--output-mode", mode],
                           check=True, stdout=subprocess.DEVNULL)
        handler = functools.partial(QuietHandler, directory=str(directory))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                options = {"headless": True}
                if args.chromium:
                    options["executable_path"] = args.chromium
                browser = playwright.chromium.launch(**options)
                try:
                    results = []
                    identities = []
                    origin = "http://127.0.0.1:{}".format(server.server_port)
                    for mode in ("single", "multi"):
                        page = browser.new_page(accept_downloads=True)
                        errors, external, failures = [], [], []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("request", lambda request: external.append(request.url)
                                if request.url.startswith(("https://", "http://")) and not request.url.startswith(origin + "/") else None)
                        page.on("response", lambda response: failures.append(response.status) if response.status >= 400 else None)
                        url = (directory / "single.html").as_uri() if mode == "single" else origin + "/multi.html"
                        page.goto(url)
                        # Successful rendering clears status text; there is no
                        # persistent is-ok class. Wait for actual diagram DOM.
                        page.wait_for_function("document.querySelector('.markmap-box svg.markmap g') !== null && document.querySelector('.mermaid-box .visual-stage svg') !== null")
                        page.wait_for_timeout(5000)
                        assert page.locator(".katex").count() > 0, "math did not render"
                        assert page.locator(".markmap-box svg").count() > 0, "Markmap did not render"
                        assert page.locator(".render-status.is-error, .math-error").count() == 0, "render error"
                        for _ in range(3):
                            page.locator(".theme-toggle").click()
                            page.wait_for_timeout(1000)
                        assert not errors, "browser execution error: " + str(errors)
                        assert not external, "unexpected remote subresource request"
                        assert not failures, "failed static resource request"
                        identities.append(page.locator("#ai-docs-source-id").inner_text())
                        assert page.evaluate("new markmap.Transformer().md.options.typographer") is False
                        assert page.evaluate("new markmap.Transformer().md.options.linkify") is False
                        with page.expect_download() as download:
                            page.get_by_role("button", name="下载源 Markdown 文档", exact=True).click()
                        assert Path(download.value.path()).read_bytes() == (ROOT / "assets/full-example.md").read_bytes()
                        pdf = page.pdf(format="A4", print_background=True)
                        assert pdf.startswith(b"%PDF") and len(pdf) > 10000
                        results.append({"mode": mode, "svg_count": page.locator("svg").count(), "pdf_bytes": len(pdf),
                                        "page_errors": len(errors), "external_requests": len(external)})
                        page.close()
                    assert identities[0] == identities[1], "source identity differs by output mode"
                    print(json.dumps(results))
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
