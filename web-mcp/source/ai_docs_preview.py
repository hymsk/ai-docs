"""Preview session crypto, page templates, and client-side link rewriting."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import html
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from ai_docs_common import (
    PREVIEW_SESSION_CLOCK_SKEW, PREVIEW_SESSION_MAX_AGE, ServiceError,
    human_readable_size, json_compact, safe_relative_markdown_path,
)


def preview_session_token(secret: str, expires_at: int) -> str:
    return hmac.new(secret.encode("utf-8"), str(expires_at).encode("ascii"), hashlib.sha256).hexdigest()


def preview_session_value(secret: str, max_age: int = PREVIEW_SESSION_MAX_AGE) -> str:
    expires_at = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + max_age
    return "{}.{}".format(expires_at, preview_session_token(secret, expires_at))


def valid_preview_session(secret: Any, value: Any, max_age: int = PREVIEW_SESSION_MAX_AGE) -> bool:
    if not isinstance(secret, str) or not secret or not isinstance(value, str):
        return False
    expires_raw, separator, signature = value.partition(".")
    if not separator or not expires_raw.isdigit() or len(expires_raw) > 12 or len(signature) != 64:
        return False
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    expires_at = int(expires_raw)
    if type(max_age) is not int or max_age < 1:
        return False
    if expires_at + PREVIEW_SESSION_CLOCK_SKEW < now or expires_at > now + max_age + PREVIEW_SESSION_CLOCK_SKEW:
        return False
    return hmac.compare_digest(signature, preview_session_token(secret, expires_at))


PREVIEW_STYLE = """
:root { color-scheme: light dark; --bg: #ffffff; --panel: #fafafa; --text: #171717; --muted: #737373; --border: #e5e5e5; --accent: #2563eb; --accent-strong: #1d4ed8; --accent-fg: #ffffff; --accent-bg: rgba(37, 99, 235, 0.08); --error: #dc2626; --radius: 10px; --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04); --shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 4px 16px rgba(0, 0, 0, 0.05); }
@media (prefers-color-scheme: dark) { :root { --bg: #0a0a0a; --panel: #141414; --text: #fafafa; --muted: #a3a3a3; --border: #262626; --accent: #60a5fa; --accent-strong: #93c5fd; --accent-fg: #0a0a0a; --accent-bg: rgba(96, 165, 250, 0.12); --error: #f87171; --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4); --shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 4px 16px rgba(0, 0, 0, 0.35); } }
* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; color: var(--text); background: var(--bg); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; transition: background-color 160ms ease, color 160ms ease; }
::selection { background: var(--accent-bg); color: var(--accent-strong); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border: 2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }
a { color: var(--accent); text-decoration: none; text-underline-offset: .18em; }
a:hover { text-decoration: underline; }
.toolbar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: .65rem; min-height: 3.4rem; padding: .5rem 1rem; border-bottom: 1px solid var(--border); background: color-mix(in srgb, var(--bg) 92%, transparent); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); flex-wrap: wrap; }
.brand { display: inline-flex; align-items: center; gap: .55rem; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 650; font-size: .95rem; letter-spacing: -0.01em; }
.toolbar-actions { margin-left: auto; display: flex; align-items: center; gap: .35rem; flex-wrap: wrap; }
.reader-layout { height: 100vh; height: 100dvh; display: flex; flex-direction: column; }
.reader-layout > .toolbar { flex-shrink: 0; }
.reader-layout .brand { flex: 1 1 12rem; }
.reader-layout > iframe { flex: 1; min-height: 0; width: 100%; border: 0; display: block; background: var(--bg); }
button, .button { min-height: 2rem; padding: .25rem .7rem; color: var(--muted); background: transparent; border: 1px solid transparent; border-radius: 0; cursor: pointer; font: inherit; font-size: .84rem; text-decoration: none; display: inline-flex; align-items: center; transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease; }
button:hover, .button:hover { background: var(--panel); color: var(--text); text-decoration: none; }
button:disabled { cursor: default; opacity: .55; }
button.primary, .button.primary { background: var(--accent); color: var(--accent-fg); border-color: transparent; font-weight: 600; box-shadow: var(--shadow-sm); }
button.primary:hover, .button.primary:hover { background: var(--accent-strong); color: var(--accent-fg); }
input, select { min-height: 2.1rem; padding: .3rem .6rem; color: var(--text); background: var(--bg); border: 1px solid var(--border); border-radius: 0; font: inherit; font-size: .88rem; }
input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: 1px; border-color: var(--accent); }
.status { color: var(--muted); font-size: .78rem; }
.status.is-error { color: var(--error); }
.page { padding: 2rem clamp(1rem, 4vw, 2.5rem) 3rem; max-width: 60rem; margin: 0 auto; }
.page h1 { font-size: 1.5rem; font-weight: 650; letter-spacing: -0.02em; margin: 0; }
.page p { color: var(--muted); }
.page > label { display: inline-flex; align-items: center; gap: .45rem; margin: 0 1rem .9rem 0; color: var(--muted); font-size: .84rem; }
#library-count { color: var(--muted); font-size: .8rem; }
table { width: 100%; border-collapse: separate; border-spacing: 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); box-shadow: var(--shadow-sm); overflow: hidden; }
th, td { padding: .6rem .8rem; border-bottom: 1px solid var(--border); text-align: left; font-size: .9rem; }
th { color: var(--muted); font-weight: 650; font-size: .78rem; letter-spacing: .05em; text-transform: uppercase; border-bottom-width: 2px; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:nth-child(even) td { background: var(--panel); }
tbody tr:hover td { background: var(--accent-bg); }
td a { margin-right: .8rem; font-weight: 550; }
td a:last-child { margin-right: 0; }
td.size, th.size { text-align: right; white-space: nowrap; color: var(--muted); font-variant-numeric: tabular-nums; }
.empty { padding: 3rem 1rem; color: var(--muted); text-align: center; font-size: .88rem; }
.library-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem 1.5rem; flex-wrap: wrap; margin-bottom: 1.4rem; }
.library-title { min-width: 0; }
.library-sub { margin: .3rem 0 0; color: var(--muted); font-size: .84rem; }
.library-tools { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.library-search { position: relative; display: inline-flex; align-items: center; }
.library-search svg { position: absolute; left: .55rem; width: .9rem; height: .9rem; color: var(--muted); fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; pointer-events: none; }
.library-search input { width: min(17rem, 60vw); padding-left: 1.85rem; }
.breadcrumbs { display: flex; align-items: center; gap: .35rem; flex-wrap: wrap; font-size: 1.15rem; font-weight: 650; letter-spacing: -0.02em; }
.breadcrumbs a { color: var(--muted); text-decoration: none; }
.breadcrumbs a:hover { color: var(--accent); text-decoration: none; }
.breadcrumbs .crumb-sep { color: var(--muted); opacity: .55; }
.breadcrumbs [aria-current="page"] { color: var(--text); }
.brand-crumbs { display: inline-flex; align-items: center; gap: .3rem; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.brand-crumbs a { color: var(--muted); text-decoration: none; }
.brand-crumbs a:hover { color: var(--accent); text-decoration: none; }
.brand-crumbs .crumb-sep { color: var(--muted); opacity: .55; }
.brand-crumbs [aria-current="page"] { color: var(--text); }
.file-list { border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); box-shadow: var(--shadow-sm); overflow: hidden; animation: library-in 240ms ease both; }
@keyframes library-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .file-list { animation: none; } }
.file-list-head { display: flex; align-items: center; gap: .5rem; padding: .5rem 1rem; background: var(--panel); border-bottom: 1px solid var(--border); color: var(--muted); font-size: .78rem; }
.file-row { display: flex; align-items: center; gap: .7rem; padding: .68rem 1rem; border-bottom: 1px solid var(--border); transition: background-color 100ms ease; }
.file-row:last-child { border-bottom: 0; }
.file-row:hover, .file-row:focus-within { background: var(--panel); }
.file-open { display: flex; align-items: center; gap: .65rem; flex: 1 1 auto; min-width: 0; color: inherit; text-decoration: none; }
.file-open:hover { text-decoration: none; }
.file-icon { flex: 0 0 auto; display: inline-flex; color: var(--muted); transition: color 100ms ease; }
.file-icon svg { width: 1.05rem; height: 1.05rem; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.file-open:hover .file-icon { color: var(--accent); }
.folder-row .file-icon { color: var(--accent); }
.file-main { min-width: 0; display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; }
.file-name { font-weight: 550; color: var(--text); overflow-wrap: anywhere; }
.file-open:hover .file-name { color: var(--accent); }
.file-meta { flex: 0 0 auto; width: 4.5rem; text-align: right; color: var(--muted); font-size: .78rem; font-variant-numeric: tabular-nums; }
.file-time { flex: 0 0 auto; width: 6.5rem; text-align: right; color: var(--muted); font-size: .78rem; font-variant-numeric: tabular-nums; }
.file-edit { flex: 0 0 auto; padding: .14rem .6rem; color: var(--muted); border: 1px solid var(--border); font-size: .78rem; text-decoration: none; opacity: 0; transition: opacity 120ms ease, color 120ms ease, border-color 120ms ease; }
.file-row:hover .file-edit, .file-row:focus-within .file-edit, .file-edit:focus-visible { opacity: 1; }
.file-edit:hover { color: var(--accent); border-color: var(--accent); text-decoration: none; }
#library-empty { padding: 1.2rem 0; color: var(--muted); font-size: .86rem; text-align: center; }
@media (max-width: 760px) { .file-time { display: none; } .file-meta { width: auto; } .file-edit { opacity: 1; } }
.login-card { max-width: 24rem; margin: 10vh auto; padding: 1.8rem 1.8rem 1.6rem; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); box-shadow: var(--shadow); }
.login-card h1 { font-size: 1.35rem; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 .5rem; }
.login-card p { color: var(--muted); font-size: .84rem; margin: 0 0 1.2rem; }
.login-card label { display: block; color: var(--muted); font-size: .8rem; font-weight: 650; margin-bottom: .4rem; }
.login-card input { display: block; width: 100%; margin: 0 0 1.1rem; padding: .55rem .65rem; }
.login-card .status { margin-left: .5rem; }
"""


PREVIEW_EDITOR_SCRIPT = """
(function() {
  'use strict';
  var editor = document.getElementById('editor');
  var preview = document.getElementById('preview');
  var status = document.getElementById('status');
  var renderButton = document.getElementById('render');
  var saveButton = document.getElementById('save');
  var workspace = document.getElementById('workspace');
  var splitter = document.getElementById('splitter');
  var path = editor.getAttribute('data-path');
  var base = editor.getAttribute('data-base');
  var renderTimer = 0;
  var latestRequest = 0;
  var dragging = false;
  var previewScrollState = null;
  var restoreToken = 0;
  var editorSyncTarget = null;

  function setStatus(message, error) {
    status.textContent = message;
    status.classList.toggle('is-error', Boolean(error));
  }

  function request(url, payload) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function(response) {
      return response.json().catch(function() { return {}; }).then(function(body) {
        if (!response.ok) throw new Error((body.error && body.error.message) || '请求失败（HTTP ' + response.status + '）。');
        return body;
      });
    });
  }

  function render() {
    window.clearTimeout(renderTimer);
    var requestId = ++latestRequest;
    setStatus('正在使用 AI Docs renderer 渲染…');
    renderButton.disabled = true;
    request(base + 'api/render', { path: path, markdown: editor.value }).then(function(result) {
      if (requestId !== latestRequest) return;
      restoreToken++;
      preview.style.visibility = 'hidden';
      preview.srcdoc = result.html;
      var token = restoreToken;
      window.setTimeout(function() { if (restoreToken === token) preview.style.visibility = ''; }, 8500);
      setStatus('渲染完成');
    }).catch(function(error) {
      if (requestId !== latestRequest) return;
      setStatus(error.message || '渲染失败。', true);
    }).then(function() {
      if (requestId === latestRequest) renderButton.disabled = false;
    });
  }

  function scheduleRender() {
    window.clearTimeout(renderTimer);
    renderTimer = window.setTimeout(render, 350);
  }

  function save() {
    saveButton.disabled = true;
    setStatus('正在保存 Markdown…');
    request(base + 'api/save', { path: path, markdown: editor.value }).then(function() {
      setStatus('已保存到库文件');
    }).catch(function(error) {
      setStatus(error.message || '保存失败。', true);
    }).then(function() {
      saveButton.disabled = false;
    });
  }

  function setEditorWidth(next) {
    var width = Math.max(25, Math.min(75, next));
    workspace.style.setProperty('--editor-width', width + '%');
    splitter.setAttribute('aria-valuenow', String(Math.round(width)));
  }

  function widthFromPointer(clientX) {
    var rect = workspace.getBoundingClientRect();
    return ((clientX - rect.left) / rect.width) * 100;
  }

  splitter.addEventListener('pointerdown', function(event) {
    if (window.matchMedia('(max-width: 860px)').matches) return;
    dragging = true;
    splitter.classList.add('is-dragging');
    splitter.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  splitter.addEventListener('pointermove', function(event) {
    if (dragging) setEditorWidth(widthFromPointer(event.clientX));
  });
  splitter.addEventListener('pointerup', function(event) {
    dragging = false;
    splitter.classList.remove('is-dragging');
    if (splitter.hasPointerCapture(event.pointerId)) splitter.releasePointerCapture(event.pointerId);
  });
  splitter.addEventListener('keydown', function(event) {
    var current = Number(splitter.getAttribute('aria-valuenow')) || 50;
    if (event.key === 'ArrowLeft') { setEditorWidth(current - 5); event.preventDefault(); }
    if (event.key === 'ArrowRight') { setEditorWidth(current + 5); event.preventDefault(); }
    if (event.key === 'Home') { setEditorWidth(25); event.preventDefault(); }
    if (event.key === 'End') { setEditorWidth(75); event.preventDefault(); }
  });

  editor.addEventListener('input', scheduleRender);
  renderButton.addEventListener('click', render);
  saveButton.addEventListener('click', save);
  document.addEventListener('keydown', function(event) {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key.toLowerCase() === 's') { event.preventDefault(); save(); }
    if (event.key === 'Enter') { event.preventDefault(); render(); }
  });
  // 双向按进度同步手动滚动；重渲染则优先恢复原可见标题及其视口偏移。
  editor.addEventListener('scroll', function() {
    if (editorSyncTarget !== null && Math.abs(editor.scrollTop - editorSyncTarget) < 2) {
      editorSyncTarget = null;
      return;
    }
    editorSyncTarget = null;
    var max = Math.max(0, editor.scrollHeight - editor.clientHeight);
    var ratio = max ? editor.scrollTop / max : 0;
    if (preview.style.visibility === 'hidden') previewScrollState = { ratio: ratio, id: '', offset: 0 };
    else try { preview.contentWindow.postMessage({ type: 'ai-docs-scroll-sync', ratio: ratio }, '*'); } catch (error) {}
  }, { passive: true });
  window.addEventListener('message', function(event) {
    if (event.source !== preview.contentWindow) return;
    var data = event.data;
    if (data && data.type === 'ai-docs-scroll-restored' && data.token === restoreToken) {
      preview.style.visibility = '';
    }
    if (data && data.type === 'ai-docs-scroll-state' && typeof data.ratio === 'number' && preview.style.visibility !== 'hidden') {
      previewScrollState = data;
      if (!data.sync) {
        var top = Math.max(0, editor.scrollHeight - editor.clientHeight) * Math.max(0, Math.min(1, data.ratio));
        if (Math.abs(editor.scrollTop - top) > 1) {
          editorSyncTarget = top;
          editor.scrollTop = top;
        }
      }
    }
  });
  preview.addEventListener('load', function() {
    if (!previewScrollState) { preview.style.visibility = ''; return; }
    try {
      preview.contentWindow.postMessage({ type: 'ai-docs-scroll-restore', ratio: previewScrollState.ratio,
        id: previewScrollState.id, offset: previewScrollState.offset, token: restoreToken }, '*');
    } catch (error) {}
  });
  render();
}());
"""


PREVIEW_EDITOR_STYLE = """
.workspace { --editor-width: 50%; min-height: calc(100vh - 3.5rem); display: grid; grid-template-columns: minmax(18rem, var(--editor-width)) .55rem minmax(0, 1fr); }
.panel { min-width: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); }
.panel-label { display: flex; align-items: center; min-height: 2.25rem; padding: .35rem .9rem; color: var(--muted); background: var(--panel); border-bottom: 1px solid var(--border); font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.editor-panel { border-right: 1px solid var(--border); }
#editor { width: 100%; height: 100%; resize: none; padding: 1.1rem 1.2rem; color: var(--text); background: var(--bg); border: 0; outline: 0; caret-color: var(--accent); font: .88rem/1.65 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace; tab-size: 2; }
#preview { width: 100%; height: 100%; min-height: calc(100vh - 6rem); border: 0; background: var(--bg); }
#splitter { z-index: 2; margin-left: -1px; background: var(--panel); border-right: 1px solid var(--border); cursor: col-resize; touch-action: none; transition: background-color 120ms ease; }
#splitter:hover, #splitter.is-dragging { background: var(--accent); }
@media (max-width: 860px) { .workspace { min-height: 0; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(19rem, 48vh) minmax(19rem, 52vh); } #splitter { display: none; } .editor-panel { border-right: 0; border-bottom: 1px solid var(--border); } #editor, #preview { min-height: 0; } }
"""


PREVIEW_RENDER_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' 'self'; style-src 'unsafe-inline' 'self'; "
    "img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; "
    "object-src 'none'; frame-src 'none'; worker-src blob:; base-uri 'none'; form-action 'none'"
)


PREVIEW_LINK_HELPER_SCRIPT = """
<script>(function() {
  'use strict';
  var context = __PREVIEW_LINK_CONTEXT__;
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

  function rewriteAnchor(anchor) {
    var raw = anchor.getAttribute('href');
    if (!raw || raw.charAt(0) === '#') return;
    if (/^(?:[a-z][a-z0-9+.-]*:|\\/\\/)/i.test(raw)) {
      if (!anchor.getAttribute('target')) {
        anchor.setAttribute('target', '_blank');
        anchor.setAttribute('rel', 'noopener noreferrer');
      }
      return;
    }
    var hashIndex = raw.indexOf('#');
    var hash = hashIndex >= 0 ? raw.slice(hashIndex) : '';
    var target = hashIndex >= 0 ? raw.slice(0, hashIndex) : raw;
    if (!/\\.(md|markdown|txt)$/i.test(target)) return;
    var decoded;
    try { decoded = decodeURIComponent(target); } catch (error) { return; }
    var resolved = resolveLibraryPath(decoded);
    if (!resolved) return;
    if (resolved === context.path && hash) {
      // 当前文档内的锚点链接：转成纯页内锚点，避免同 URL 的 _top 导航不触发刷新
      anchor.setAttribute('href', hash);
      return;
    }
    anchor.setAttribute('href', context.viewBase + encodeURIComponent(resolved) + hash);
    anchor.setAttribute('target', context.target);
  }

  Array.prototype.forEach.call(document.querySelectorAll('a[href]'), rewriteAnchor);

  // srcdoc 文档的 base URL 继承父页面地址：页内锚点点击会把 iframe 导航到
  // 父页面 URL 而非页内滚动。统一拦截为页内滚动（history API 在 sandbox
  // opaque origin 下不可用，不同步地址栏 hash）。
  document.addEventListener('click', function(event) {
    var anchor = event.target && event.target.closest ? event.target.closest('a[href^="#"]') : null;
    if (!anchor) return;
    var raw = anchor.getAttribute('href') || '';
    if (raw.length < 2) return;
    var id;
    try { id = decodeURIComponent(raw.slice(1)); } catch (error) { return; }
    var target = document.getElementById(id) || document.getElementsByName(id)[0];
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView();
  });

  window.addEventListener('message', function(event) {
    var data = event.data;
    if (!data || data.type !== 'ai-docs-scroll' || typeof data.id !== 'string') return;
    var target = document.getElementById(data.id);
    if (target) target.scrollIntoView();
  });

  // sandbox iframe 跨源；上报滚动进度和当前可见标题，供编辑器同步和刷新恢复。
  var syncTarget = null;
  function scrollState() {
    var y = window.scrollY || window.pageYOffset || 0;
    var max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    var headings = document.querySelectorAll('h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]');
    var heading = null;
    for (var i = 0; i < headings.length; i++) {
      if (headings[i].getBoundingClientRect().top > 80) break;
      heading = headings[i];
    }
    parent.postMessage({ type: 'ai-docs-scroll-state', ratio: max ? y / max : 0,
      id: heading ? heading.id : '', offset: heading ? heading.getBoundingClientRect().top : 0,
      sync: syncTarget !== null && Math.abs(y - syncTarget) < 2 }, '*');
    syncTarget = null;
  }
  window.addEventListener('scroll', scrollState, { passive: true });
  window.addEventListener('load', scrollState);
  window.addEventListener('message', function(event) {
    var data = event.data;
    if (!data) return;
    if (data.type === 'ai-docs-scroll-sync' && typeof data.ratio === 'number') {
      var top = Math.max(0, document.documentElement.scrollHeight - window.innerHeight) * Math.max(0, Math.min(1, data.ratio));
      if (Math.abs((window.scrollY || 0) - top) > 1) {
        syncTarget = top;
        window.scrollTo({ top: top, behavior: 'instant' });
      }
      return;
    }
    if (data.type === 'ai-docs-scroll-restore') restoreScroll(data);
  });
  // 图表渲染是异步的：load 时占位壳可能尚无高度，立即滚动会被钳制。
  // 等 clientRuntime 的渲染完成信号，超时兜底直接滚。
  function restoreScroll(state) {
    function apply() {
      var heading = state.id && document.getElementById(state.id);
      var max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      var top = heading ? (window.scrollY || 0) + heading.getBoundingClientRect().top - state.offset : max * Math.max(0, Math.min(1, state.ratio || 0));
      if (Math.abs((window.scrollY || 0) - top) > 1) {
        syncTarget = top;
        window.scrollTo({ top: top, behavior: 'instant' });
      }
      parent.postMessage({ type: 'ai-docs-scroll-restored', token: state.token }, '*');
    }
    if (document.documentElement.getAttribute('data-dynamic-visuals') === 'done') {
      apply();
      return;
    }
    var finished = false;
    var observer = new MutationObserver(function() {
      if (document.documentElement.getAttribute('data-dynamic-visuals') !== 'done') return;
      finished = true;
      observer.disconnect();
      apply();
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-dynamic-visuals'] });
    setTimeout(function() {
      if (finished) return;
      observer.disconnect();
      apply();
    }, 8000);
  }
}());</script>
"""


def prepare_preview_html(
    rendered: str, current_path: str, preview_prefix: str, link_target: str, editor_preview: bool = False,
) -> str:
    """Constrain srcdoc automatic loads and inject the client-side link helper."""
    marker = "<head>"
    if marker not in rendered:
        raise ServiceError(500, "render_failed", "renderer output has no head element")
    policy = '<meta http-equiv="Content-Security-Policy" content="{}">'.format(html.escape(PREVIEW_RENDER_CSP, quote=True))
    result = rendered.replace(marker, marker + policy, 1)
    if editor_preview:
        # 编辑器每次渲染都会替换 iframe，仅关闭编辑预览的入场动画和滚动过渡。
        style = '<style>html { scroll-behavior: auto; } .container { animation: none; }</style>'
        head_end = result.rfind('</head>')
        if head_end == -1:
            raise ServiceError(500, "render_failed", "renderer output has no head closing tag")
        result = result[:head_end] + style + result[head_end:]
    context = json_compact({
        "path": safe_relative_markdown_path(current_path),
        "viewBase": preview_prefix + "view?path=",
        "target": link_target,
    }).replace("<", "\\u003c")
    script = PREVIEW_LINK_HELPER_SCRIPT.replace("__PREVIEW_LINK_CONTEXT__", context)
    # 必须锚定文档末尾真正的 </body>：渲染产物内联的 vendor 脚本可能含有
    # "</body></html>" 之类的字符串（如 DOMPurify），按首个匹配注入会把脚本
    # 插进 JS 字符串字面量，造成语法错误并拖垮整个渲染器。
    body_marker = "</body>"
    body_index = result.rfind(body_marker)
    if body_index == -1:
        raise ServiceError(500, "render_failed", "renderer output has no body element")
    return result[:body_index] + script + result[body_index:]


def preview_document(title: str, body: str, extra_style: str = "") -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>%(style)s%(extra_style)s</style>
</head>
<body>
%(body)s
</body>
</html>
""" % {"title": html.escape(title), "style": PREVIEW_STYLE, "extra_style": extra_style, "body": body}


FILE_ICON_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2.5h8.2L19.5 8v13a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 21V4A1.5 1.5 0 0 1 6 2.5z"></path><path d="M14 2.8V8h5.2"></path></svg>'


FOLDER_ICON_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6A1.5 1.5 0 0 1 5 4.5h4.2L11.5 7H19a1.5 1.5 0 0 1 1.5 1.5V18a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 18z"></path></svg>'


def preview_index_page(entries: List[Dict[str, Any]], preview_path: str, write_back: bool, truncated: bool = False, current_dir: str = "", pinned_dirs: Iterable[str] = ()) -> str:
    """Render the library index as a folder browser rooted at *current_dir*."""
    base = html.escape(preview_path + "/", quote=True)
    # 合法目录集合（末尾带 /）主要由文件路径推导，同时挡住路径穿越等非法值
    all_dirs = set()
    for entry in entries:
        parts = entry["path"].split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            all_dirs.add("/".join(parts[:depth]) + "/")
    # 固定功能目录（如公开区 public/）纳入合法目录集合：公开区是编辑器的发布
    # 目标，即使为空也要可进入、可浏览，空库时“看不到 public/”会让用户误以为
    # 不能发布。校验 ?dir= 与下方空目录显示都基于该集合。
    for pinned in pinned_dirs:
        parts = [part for part in pinned.split("/") if part]
        for depth in range(1, len(parts) + 1):
            all_dirs.add("/".join(parts[:depth]) + "/")
    # 不做有损空白规范化：合法目录名可含前导/尾随空白，strip 会让
    # “ notes/”之类的目录被改写成不存在的“notes/”而误报 400。
    current_dir = current_dir.lstrip("/")
    if current_dir and not current_dir.endswith("/"):
        current_dir += "/"
    if current_dir and current_dir not in all_dirs:
        raise ServiceError(400, "invalid_directory", "directory was not found in the library")

    subdirs: Dict[str, int] = {}
    files = []
    for entry in entries:
        path = entry["path"]
        if not path.startswith(current_dir):
            continue
        rest = path[len(current_dir):]
        if "/" in rest:
            name = rest.split("/", 1)[0]
            subdirs[name] = subdirs.get(name, 0) + 1
        else:
            files.append(entry)
    # 固定功能目录（经 pinned_dirs 进入 all_dirs）即使没有任何文件也显示为
    # 可进入的空目录，计数为 0；已有文件计数的目录不受影响。
    for directory in all_dirs:
        if not directory.startswith(current_dir):
            continue
        rest = directory[len(current_dir):]
        if rest.count("/") == 1:
            subdirs.setdefault(rest[:-1], 0)

    rows = []
    for name in sorted(subdirs, key=str.lower):
        sub_path = current_dir + name + "/"
        rows.append(
            '<div class="file-row folder-row" data-document="%(label)s">'
            '<a class="file-open" href="%(base)s?dir=%(encoded)s">'
            '<span class="file-icon">%(icon)s</span>'
            '<span class="file-main"><span class="file-name">%(name)s</span></span></a>'
            '<span class="file-meta">%(count)d 项</span>'
            '</div>' % {
                "base": base,
                "encoded": html.escape(quote(sub_path, safe=""), quote=True),
                "label": html.escape(name, quote=True),
                "icon": FOLDER_ICON_SVG,
                "name": html.escape(name),
                "count": subdirs[name],
            }
        )
    for entry in files:
        encoded = quote(entry["path"], safe="")
        rows.append(
            '<div class="file-row" data-document="%(label)s">'
            '<a class="file-open" href="%(base)sview?path=%(encoded)s">'
            '<span class="file-icon">%(icon)s</span>'
            '<span class="file-main"><span class="file-name">%(name)s</span></span></a>'
            '<span class="file-meta">%(size)s</span>'
            '<span class="file-time" data-time="%(modified)s">%(modified)s</span>'
            '<a class="file-edit" href="%(base)sedit?path=%(encoded)s" aria-label="编辑 %(label)s">编辑</a>'
            '</div>' % {
                "base": base,
                "encoded": html.escape(encoded, quote=True),
                "label": html.escape(entry["path"], quote=True),
                "icon": FILE_ICON_SVG,
                "name": html.escape(entry["path"][len(current_dir):]),
                "size": html.escape(human_readable_size(entry["size_bytes"])),
                "modified": html.escape(entry["modified_at"], quote=True),
            }
        )

    if current_dir:
        crumbs = ['<a href="%s">文档库</a>' % base]
        parts = [part for part in current_dir.split("/") if part]
        acc = ""
        for index, part in enumerate(parts):
            acc += part + "/"
            if index == len(parts) - 1:
                crumbs.append('<span aria-current="page">%s</span>' % html.escape(part))
            else:
                href = base + "?dir=" + html.escape(quote(acc, safe=""), quote=True)
                crumbs.append('<a href="%s">%s</a>' % (href, html.escape(part)))
    else:
        crumbs = ['<span aria-current="page">文档库</span>']
    breadcrumb = (
        '<nav class="breadcrumbs" aria-label="目录路径">'
        + '<span class="crumb-sep" aria-hidden="true">/</span>'.join(crumbs)
        + '</nav>'
    )

    summary = []
    if subdirs:
        summary.append("%d 个文件夹" % len(subdirs))
    summary.append("%d 个文件" % len(files))
    summary.append("可编辑并写回" if write_back else "只读")

    listing = (
        '<div class="file-list">'
        '<div class="file-list-head"><span id="library-count" role="status" aria-live="polite"></span></div>'
        "%s"
        "</div>"
    ) % ("".join(rows) if rows else (
        '<p class="empty">此文件夹为空。</p>' if current_dir else '<p class="empty">库目录中还没有 Markdown 文件。</p>'
    ))
    note = '<p class="status is-error">列表因读取错误未完整显示。</p>' if truncated else ""
    body = (
        '<header class="toolbar"><strong class="brand">AI Docs Markdown 预览库</strong></header>'
        '<main class="page">'
        '<div class="library-head"><div class="library-title">%s'
        '<p class="library-sub">%s</p></div>'
        '<div class="library-tools">'
        '<span class="library-search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.8-3.8"></path></svg>'
        '<input id="library-search" type="search" placeholder="筛选当前目录" aria-label="筛选当前目录"></span>'
        '</div></div>'
        '%s%s'
        '<p id="library-empty" hidden>没有匹配的条目。</p></main>'
    ) % (
        breadcrumb,
        html.escape(" · ".join(summary)),
        note,
        listing,
    )
    body += '''<script>(function(){"use strict";
var rows=Array.from(document.querySelectorAll(".file-row[data-document]")),search=document.getElementById("library-search");
function rel(iso){var t=Date.parse(iso);if(!t)return iso;var s=(Date.now()-t)/1000;if(s<60)return"刚刚";if(s<3600)return Math.floor(s/60)+" 分钟前";if(s<86400)return Math.floor(s/3600)+" 小时前";if(s<86400*30)return Math.floor(s/86400)+" 天前";var d=new Date(t);function p(n){return String(n).padStart(2,"0");}return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate());}
document.querySelectorAll(".file-time[data-time]").forEach(function(el){el.textContent=rel(el.getAttribute("data-time"));el.title=el.getAttribute("data-time");});
function filter(){var term=search.value.toLocaleLowerCase(),count=0;rows.forEach(function(row){var label=row.dataset.document;row.hidden=!label.toLocaleLowerCase().includes(term);if(!row.hidden)count++;});document.getElementById("library-count").textContent=count+" / "+rows.length+" 项";document.getElementById("library-empty").hidden=count!==0;}
search.addEventListener("input",filter);filter();})();</script>'''
    return preview_document("AI Docs Markdown 预览库", body)


PREVIEW_READER_SANDBOX = (
    "allow-scripts allow-downloads allow-modals allow-popups allow-popups-to-escape-sandbox "
    "allow-top-navigation-by-user-activation"
)


PREVIEW_EDITOR_SANDBOX = "allow-scripts allow-downloads allow-modals allow-popups allow-popups-to-escape-sandbox"


PREVIEW_READER_HASH_SCRIPT = (
    "<script>(function(){"
    "var frame=document.getElementById('reader-frame');"
    "frame.addEventListener('load',function(){"
    "var hash=window.location.hash.slice(1);"
    "if(!hash)return;"
    "try{hash=decodeURIComponent(hash);}catch(error){return;}"
    "frame.contentWindow.postMessage({type:'ai-docs-scroll',id:hash},'*');"
    "});"
    "}());</script>"
)


def preview_reader_page(
    relative: str, rendered: str, preview_path: str, entries: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Read the latest library document inside an isolated, non-published frame."""
    base = html.escape(preview_path + "/", quote=True)
    encoded = html.escape(quote(relative, safe=""), quote=True)
    directory = relative.rpartition("/")[0]
    siblings = [entry["path"] for entry in (entries or [])
                if entry["path"].rpartition("/")[0] == directory]
    previous = following = None
    if relative in siblings:
        index = siblings.index(relative)
        previous = siblings[index - 1] if index else None
        following = siblings[index + 1] if index + 1 < len(siblings) else None

    def navigation(target: Optional[str], relation: str, label: str) -> str:
        if target is None:
            return '<button type="button" disabled aria-label="%s">%s</button>' % (label, label)
        return '<a class="button" rel="%s" href="%sview?path=%s" title="%s" aria-label="%s">%s</a>' % (
            relation, base, html.escape(quote(target, safe=""), quote=True),
            html.escape(target.rsplit("/", 1)[-1], quote=True), label, label,
        )

    # 标题以可点击的“文档库”根链接开头，文件夹段逐级跳转到对应预览文件夹；
    # 文件名保持为当前页文本。库根目录下的文档同样带根链接，保证始终能回到库根。
    crumbs = ['<a href="%s">文档库</a>' % base]
    acc = ""
    for part in [part for part in directory.split("/") if part]:
        acc += part + "/"
        href = base + "?dir=" + html.escape(quote(acc, safe=""), quote=True)
        crumbs.append('<a href="%s">%s</a>' % (href, html.escape(part)))
    crumbs.append('<span aria-current="page">%s</span>' % html.escape(relative.rsplit("/", 1)[-1]))
    brand = '<span class="brand-crumbs">%s</span>' % (
        '<span class="crumb-sep" aria-hidden="true">/</span>'.join(crumbs)
    )

    body = (
        '<div class="reader-layout">'
        '<header class="toolbar"><strong class="brand">%s</strong> '
        '<div class="toolbar-actions">'
        '%s %s '
        '<a class="button" href="%s">文档库</a> '
        '<a class="button" href="%sedit?path=%s">编辑</a></div></header>'
        '<iframe id="reader-frame" title="Markdown 阅读页面" '
        'sandbox="%s" srcdoc="%s"></iframe></div>%s'
    ) % (
        brand, navigation(previous, "prev", "上一篇"),
        navigation(following, "next", "下一篇"), base, base, encoded,
        PREVIEW_READER_SANDBOX, html.escape(rendered, quote=True), PREVIEW_READER_HASH_SCRIPT,
    )
    return preview_document("AI Docs 阅读 · " + relative, body)


def preview_login_page(preview_path: str, login_mode: str = "token") -> str:
    if login_mode == "proxy":
        body = '<main class="page"><section class="login-card"><h1>正在登录</h1><p id="status" role="status">正在通过受保护的代理建立会话…</p></section></main>'
        body += ('<script>fetch(%s,{method:"POST",credentials:"same-origin"}).then(function(r){'
                 'if(!r.ok)throw new Error("登录失败（HTTP "+r.status+"）");location.replace(%s);'
                 '}).catch(function(e){document.getElementById("status").textContent=e.message+"，请刷新重试或联系管理员。";});</script>') % (
                     json.dumps(preview_path + "/session"), json.dumps(preview_path + "/"))
        return preview_document("AI Docs 代理登录", body)
    body = (
        '<main class="page"><section class="login-card">'
        '<h1>AI Docs 预览登录</h1>'
        '<p>Token 仅通过当前页面的请求头发送，不进入 URL、浏览器历史或代理 query 日志。</p>'
        '<label for="token">API Token</label>'
        '<input id="token" type="password" autocomplete="current-password">'
        '<button id="login" type="button" class="primary">登录</button> '
        '<span id="status" class="status" role="status" aria-live="polite"></span>'
        '</section></main>'
        '<script>(function(){"use strict";var b=document.getElementById("login"),t=document.getElementById("token"),s=document.getElementById("status");'
        'function login(){var value=t.value;b.disabled=true;s.textContent="正在登录…";fetch(%(session)s,{method:"POST",credentials:"same-origin",headers:{Authorization:"Bearer "+value}})'
        '.then(function(r){if(!r.ok)throw new Error("登录失败（HTTP "+r.status+"）");location.replace(%(index)s);})'
        '.catch(function(e){s.textContent=e.message||"登录失败";s.classList.add("is-error");b.disabled=false;t.select();});}'
        'b.addEventListener("click",login);t.addEventListener("keydown",function(e){if(e.key==="Enter")login();});}());</script>'
    ) % {
        "session": json.dumps(preview_path + "/session"),
        "index": json.dumps(preview_path + "/"),
    }
    return preview_document("AI Docs 预览登录", body)


def preview_editor_page(relative: str, markdown: str, preview_path: str, write_back: bool) -> str:
    save_button = '<button id="save" type="button" class="primary" title="保存到库文件（Ctrl/⌘ + S）">保存</button>' if write_back else ""
    body = (
        '<main class="app">'
        '<header class="toolbar">'
        '<strong class="brand">%(label)s</strong>'
        '<div class="toolbar-actions">'
        '<a class="button" href="%(view)s" title="退出编辑并查看渲染页面">退出编辑</a>'
        '<a class="button" href="%(index)s">返回列表</a>'
        '<button id="render" type="button" title="立即渲染（Ctrl/⌘ + Enter）">立即渲染</button>'
        '%(save)s'
        '</div>'
        '<span id="status" class="status" role="status" aria-live="polite">准备就绪</span>'
        '</header>'
        '<section id="workspace" class="workspace">'
        '<section class="panel editor-panel" aria-label="Markdown 编辑器">'
        '<div class="panel-label">Markdown 编辑器</div>'
        '<textarea id="editor" data-path="%(path)s" data-base="%(base)s" aria-label="Markdown 编辑器" spellcheck="false">%(markdown)s</textarea>'
        '</section>'
        '<div id="splitter" role="separator" aria-label="调整编辑器与预览区域宽度" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow="50" tabindex="0"></div>'
        '<section class="panel" aria-label="渲染结果">'
        '<div class="panel-label">渲染结果</div>'
        '<iframe id="preview" title="AI Docs 渲染结果" sandbox="%(sandbox)s"></iframe>'
        '</section>'
        '</section>'
        '</main>'
        '<script>%(script)s</script>'
    ) % {
        "label": html.escape(relative),
        "index": html.escape(preview_path + "/", quote=True),
        "view": html.escape(preview_path + "/view?path=" + quote(relative, safe=""), quote=True),
        "save": save_button,
        "path": html.escape(relative, quote=True),
        "base": html.escape(preview_path + "/", quote=True),
        "markdown": html.escape(markdown),
        "script": PREVIEW_EDITOR_SCRIPT,
        "sandbox": PREVIEW_EDITOR_SANDBOX,
    }
    return preview_document("AI Docs 预览 · {}".format(relative), body, PREVIEW_EDITOR_STYLE)
