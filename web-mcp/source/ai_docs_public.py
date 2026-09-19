"""Public docs: live rendering and raw serving of the library public/ directory.

The /docs endpoint is a real-time access layer over the library public/ tree:
publishing means writing a Markdown file there (MCP publish_document), and every
GET resolves the URL back to a source file and renders or serves it live.
Rendered pages are cached in a byte-bounded LRU keyed by the source digest plus
the renderer fingerprint, so edits take effect immediately without stale HTML.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import quote

from ai_docs_common import (
    MARKDOWN_SUFFIXES, PUBLIC_INDEX_FILE, ServiceError, json_compact,
    resolve_library_path, safe_relative_markdown_path, safe_relative_subdirectory,
)
from ai_docs_library import LibraryStore, render_markdown_document
from ai_docs_preview import PREVIEW_RENDER_CSP

# Bump when the injection or post-processing changes; part of the cache key.
PUBLIC_PROCESSING_VERSION = "public-v1"

# 公共访问面的统一失败页面：不存在、路径非法、渲染失败、过载等都返回它，
# 不向外泄露 JSON 错误码与内部细节；服务端仍通过 handler 日志记录真实原因。
# 纯静态说明页，不含任何导航链接（不承诺首页存在）。
PUBLIC_NOT_FOUND_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>404 · 页面不存在</title>
<style>
body { font-family: system-ui, -apple-system, sans-serif; display: flex; min-height: 100vh; align-items: center; justify-content: center; margin: 0; background: #f8fafc; color: #1e293b; }
main { text-align: center; }
h1 { font-size: 3rem; margin: 0 0 0.5rem; }
p { color: #64748b; margin: 0.25rem 0; }
</style>
</head>
<body>
<main>
<h1>404</h1>
<p>页面不存在或已下线。</p>
</main>
</body>
</html>
"""


def not_found_response() -> Tuple[int, Dict[str, str], bytes]:
    """Build the uniform public-surface failure response (status 404 + HTML page)."""
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": PREVIEW_RENDER_CSP,
    }
    return 404, headers, PUBLIC_NOT_FOUND_PAGE.encode("utf-8")

PUBLIC_LINK_HELPER_SCRIPT = """
<script>(function() {
  'use strict';
  var context = __PUBLIC_LINK_CONTEXT__;
  var baseParts = context.path.split('/').slice(0, -1);

  function resolveLibraryPath(raw) {
    // 与服务端 safe_relative_markdown_path 对齐：隐藏段拒绝，前导 / 从库根解析
    var parts = raw.charAt(0) === '/' ? [] : baseParts.slice();
    var segments = raw.split('/');
    for (var index = 0; index < segments.length; index++) {
      var segment = segments[index];
      if (!segment || segment === '.') continue;
      if (segment === '..') {
        if (!parts.length) return null;
        parts.pop();
        continue;
      }
      if (segment.charAt(0) === '.') return null;
      parts.push(segment);
    }
    return parts.length ? parts.join('/') : null;
  }

  function publicUrl(resolved) {
    // 与服务端 public_url_path 对齐：README.md → 目录、.md 省略后缀、其余原样
    var parts = resolved.split('/');
    var name = parts[parts.length - 1].toLowerCase();
    if (name === 'readme.md') {
      parts.pop();
      return context.docsBase + parts.map(encodeURIComponent).join('/') + (parts.length ? '/' : '');
    }
    if (/\.md$/i.test(name)) {
      var stem = resolved.slice(0, resolved.length - 3);
      return context.docsBase + stem.split('/').map(encodeURIComponent).join('/');
    }
    return context.docsBase + parts.map(encodeURIComponent).join('/');
  }

  function rewriteAnchor(anchor) {
    var raw = anchor.getAttribute('href');
    if (!raw || raw.charAt(0) === '#') return;
    if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(raw)) {
      if (!anchor.getAttribute('target')) {
        anchor.setAttribute('target', '_blank');
        anchor.setAttribute('rel', 'noopener noreferrer');
      }
      return;
    }
    var hashIndex = raw.indexOf('#');
    var hash = hashIndex >= 0 ? raw.slice(hashIndex) : '';
    var target = hashIndex >= 0 ? raw.slice(0, hashIndex) : raw;
    if (!/\.(md|markdown|txt)$/i.test(target)) return;
    var decoded;
    try { decoded = decodeURIComponent(target); } catch (error) { return; }
    var resolved = resolveLibraryPath(decoded);
    if (!resolved) return;
    if (resolved === context.path && hash) {
      // 当前文档内的锚点链接：转成纯页内锚点，避免同 URL 导航不触发滚动
      anchor.setAttribute('href', hash);
      return;
    }
    // 站内文档正常导航，不改 target
    anchor.setAttribute('href', publicUrl(resolved) + hash);
  }

  Array.prototype.forEach.call(document.querySelectorAll('a[href]'), rewriteAnchor);
}());</script>
"""


@dataclass(frozen=True)
class CacheEntry:
    body: bytes
    etag: str


class RenderCache:
    """Byte-bounded in-process LRU for rendered public pages."""

    def __init__(self, max_bytes: int, max_entries: int, max_entry_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.max_entry_bytes = max_entry_bytes
        self._entries: "OrderedDict[Tuple[str, str, str, str], CacheEntry]" = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: Tuple[str, str, str, str]) -> Optional[CacheEntry]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
            return entry

    def put(self, key: Tuple[str, str, str, str], entry: CacheEntry) -> None:
        size = len(entry.body)
        if size > self.max_entry_bytes:
            return
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= len(old.body)
            while self._entries and (
                self._bytes + size > self.max_bytes or len(self._entries) + 1 > self.max_entries
            ):
                unused_key, evicted = self._entries.popitem(last=False)
                self._bytes -= len(evicted.body)
            self._entries[key] = entry
            self._bytes += size

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(frozen=True)
class PublicResolution:
    kind: str        # "redirect" | "render" | "raw"
    source: str = ""     # public-root-relative Markdown path
    location: str = ""   # redirect Location header value


class PublicDocs:
    """Resolve /docs URLs onto the public root and serve them live."""

    def __init__(self, config, library: LibraryStore) -> None:
        self.config = config
        self.library = library
        self.capacity = threading.BoundedSemaphore(config.public_max_concurrent_renders)
        self.cache = RenderCache(config.cache_max_bytes, config.cache_max_entries, config.cache_max_entry_bytes)
        self.renderer_fingerprint = self._renderer_fingerprint(config)
        self.inflight: Dict[Tuple[str, str, str, str], threading.Lock] = {}
        self.inflight_lock = threading.Lock()

    @staticmethod
    def _renderer_fingerprint(config) -> str:
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

    # ------------------------------------------------------------ resolution

    def resolve(self, relative: str) -> PublicResolution:
        """Map a decoded /docs-relative URL path to a render, raw file, or redirect."""
        if relative == "":
            return PublicResolution("render", source=PUBLIC_INDEX_FILE)
        if relative.endswith("/"):
            directory = relative[:-1]
            if directory:
                safe_relative_subdirectory(directory, "path")
            return PublicResolution("render", source=(directory + "/" if directory else "") + PUBLIC_INDEX_FILE)
        if relative.lower().endswith(MARKDOWN_SUFFIXES):
            return PublicResolution("raw", source=safe_relative_markdown_path(relative))
        candidate = safe_relative_markdown_path(relative + ".md")
        if self._source_path(candidate) is not None:
            return PublicResolution("render", source=candidate)
        try:
            safe_relative_subdirectory(relative, "path")
        except ServiceError:
            raise ServiceError(404, "not_found", "document was not found")
        index = relative + "/" + PUBLIC_INDEX_FILE
        if self._source_path(index) is not None:
            location = self.config.documents_prefix + "/".join(quote(part) for part in relative.split("/")) + "/"
            return PublicResolution("redirect", location=location)
        raise ServiceError(404, "not_found", "document was not found")

    # ---------------------------------------------------------------- serving

    def serve(self, relative: str, if_none_match: Optional[str]) -> Tuple[int, Dict[str, str], bytes]:
        resolution = self.resolve(relative)
        if resolution.kind == "redirect":
            return 308, {"Location": resolution.location, "Cache-Control": "no-store"}, b""
        source_path = self._source_path(resolution.source)
        if source_path is None:
            raise ServiceError(404, "not_found", "document was not found")
        try:
            content = source_path.read_bytes()
        except OSError as error:
            raise ServiceError(500, "io_error", "cannot read the document") from error
        source_sha256 = hashlib.sha256(content).hexdigest()
        headers = self._base_headers()
        if resolution.kind == "raw":
            etag = '"{}"'.format(source_sha256)
            headers["ETag"] = etag
            if self._etag_matches(if_none_match, etag):
                return 304, headers, b""
            if resolution.source.lower().endswith(".txt"):
                headers["Content-Type"] = "text/plain; charset=utf-8"
            else:
                headers["Content-Type"] = "text/markdown; charset=utf-8"
            return 200, headers, content
        key = (resolution.source, source_sha256, self.renderer_fingerprint, PUBLIC_PROCESSING_VERSION)
        entry = self.cache.get(key)
        if entry is None:
            entry = self._render_single_flight(key, resolution.source, content)
        headers["ETag"] = entry.etag
        headers["Content-Security-Policy"] = PREVIEW_RENDER_CSP
        if self._etag_matches(if_none_match, entry.etag):
            return 304, headers, b""
        headers["Content-Type"] = "text/html; charset=utf-8"
        return 200, headers, entry.body

    @staticmethod
    def _base_headers() -> Dict[str, str]:
        # private 阻止共享缓存（站点前面的 CDN）按自己的 TTL 规则缓存公开页，
        # 否则编辑/删除在 CDN 窗口期内对外不可见；浏览器侧 ETag 协商不受影响。
        return {
            "Cache-Control": "private, max-age=0, must-revalidate",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }

    @staticmethod
    def _etag_matches(if_none_match: Optional[str], etag: str) -> bool:
        if not if_none_match:
            return False
        for token in if_none_match.split(","):
            token = token.strip()
            if token == "*" or token == etag or token == "W/" + etag:
                return True
        return False

    # -------------------------------------------------------------- rendering

    def _render_single_flight(self, key: Tuple[str, str, str, str], source: str, content: bytes) -> CacheEntry:
        with self.inflight_lock:
            lock = self.inflight.get(key)
            owner = lock is None
            if owner:
                lock = threading.Lock()
                self.inflight[key] = lock
        with lock:
            try:
                entry = self.cache.get(key)
                if entry is None:
                    rendered = render_markdown_document(
                        self.config, self.capacity, Path(source).name, content,
                        self.config.public_render_timeout_seconds, ".ai-docs-public-",
                    )
                    body = self._inject_helper(rendered, source).encode("utf-8")
                    entry = CacheEntry(body=body, etag='"{}"'.format(hashlib.sha256(body).hexdigest()))
                    self.cache.put(key, entry)
                return entry
            finally:
                if owner:
                    with self.inflight_lock:
                        self.inflight.pop(key, None)

    def _inject_helper(self, rendered: str, source: str) -> str:
        context = json_compact({
            "path": source,
            "docsBase": self.config.documents_prefix,
        }).replace("<", "\\u003c")
        script = PUBLIC_LINK_HELPER_SCRIPT.replace("__PUBLIC_LINK_CONTEXT__", context)
        # 与 preview 相同的原因：必须锚定文档末尾真正的 </body>，不能按首个匹配注入。
        body_marker = "</body>"
        body_index = rendered.rfind(body_marker)
        if body_index == -1:
            raise ServiceError(500, "render_failed", "renderer output has no body element")
        return rendered[:body_index] + script + rendered[body_index:]

    # ---------------------------------------------------------------- helpers

    def _source_path(self, relative: str) -> Optional[Path]:
        try:
            target = resolve_library_path(self.config.public_root, relative)
        except ServiceError:
            return None
        if not target.is_file():
            return None
        return target
