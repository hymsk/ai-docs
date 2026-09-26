#!/usr/bin/env node
/**
 * preview.js - 为 AI Docs renderer 提供本地实时编辑预览。
 *
 * 预览页面本身只使用 Node.js 标准库；每次更新均委托 build.js 生成隔离
 * iframe 的完整成品，以保证预览与离线 renderer 使用同一条渲染路径。
 */

'use strict';

const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { promisify } = require('util');

const execFile = promisify(childProcess.execFile);
const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8000;
const MAX_MARKDOWN_BYTES = 4 * 1024 * 1024;
const MAX_BUILD_OUTPUT_BYTES = 32 * 1024 * 1024;

class RequestError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function isLoopbackHost(host) {
  const normalized = host.trim().toLowerCase().replace(/^\[|\]$/g, '');
  if (normalized === 'localhost' || normalized === '::1') return true;
  return /^127(?:\.\d{1,3}){3}$/.test(normalized);
}

function printUsage() {
  console.log(`用法:
  node preview.js --input <input.md> [选项]
  node preview.js <input.md> [选项]

启动仅监听本机的实时预览：左侧编辑 Markdown，右侧显示 AI Docs renderer 的结果。
每次预览均调用 build.js，预览与离线 HTML 使用相同的渲染器；只有点击“保存”才会写回输入文件。

选项:
  -i, --input <file>    输入 Markdown 文件
      --config <file>   复用 AI Docs JSON 配置中的页面选项
      --title <text>    覆盖右侧渲染文档标题
      --host <address>  监听地址（默认 ${DEFAULT_HOST}）；非本机地址会为所有接口启用
                        进程级随机访问令牌，访问地址自动携带 key 参数
  -p, --port <port>     监听端口；0 表示自动选择空闲端口（默认 ${DEFAULT_PORT}）
      --open            启动后打开默认浏览器
      --no-open         启动后不打开浏览器（默认）
  -h, --help            显示本帮助

示例:
  node preview.js --input document.md --open
  node build.js --preview --input document.md --port 0
  node preview.js document.md --config ai-docs.config.json`);
}

function fail(message) {
  throw new Error(message);
}

function optionValue(argv, index, flag) {
  if (index + 1 >= argv.length || argv[index + 1].startsWith('-')) fail(`${flag} 需要一个值。`);
  return argv[index + 1];
}

function parseArguments(argv) {
  const options = { input: '', config: '', title: '', host: DEFAULT_HOST, port: DEFAULT_PORT, open: false };
  const positionals = [];
  const valueOptions = new Map([
    ['--input', 'input'], ['-i', 'input'], ['--config', 'config'], ['--title', 'title'],
    ['--host', 'host'], ['--port', 'port'], ['-p', 'port']
  ]);

  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === '--') {
      positionals.push(...argv.slice(index + 1));
      break;
    }
    if (arg === '--help' || arg === '-h') {
      printUsage();
      process.exit(0);
    }
    if (arg === '--open') {
      options.open = true;
      continue;
    }
    if (arg === '--no-open') {
      options.open = false;
      continue;
    }
    if (valueOptions.has(arg)) {
      options[valueOptions.get(arg)] = optionValue(argv, index, arg);
      index++;
      continue;
    }

    const equals = arg.indexOf('=');
    const name = equals === -1 ? arg : arg.slice(0, equals);
    if (valueOptions.has(name)) {
      const value = equals === -1 ? '' : arg.slice(equals + 1);
      if (!value) fail(`${name} 需要一个值。`);
      options[valueOptions.get(name)] = value;
      continue;
    }
    if (arg.startsWith('-')) fail(`未知选项: ${arg}`);
    positionals.push(arg);
  }

  if (options.input && positionals.length) fail('不能同时通过 --input 和位置参数指定输入文件。');
  if (!options.input) options.input = positionals.shift() || '';
  if (positionals.length) fail('只接受一个输入 Markdown 文件。');
  if (!options.input) fail('缺少输入文件。使用 --input <file>，或运行 node preview.js <input.md>。');
  if (typeof options.host !== 'string' || !options.host.trim()) fail('--host 必须是非空地址。');
  options.host = options.host.trim();
  if (!/^\d+$/.test(String(options.port))) fail('--port 必须是 0 到 65535 之间的整数。');
  options.port = Number(options.port);
  if (!Number.isSafeInteger(options.port) || options.port < 0 || options.port > 65535) {
    fail('--port 必须是 0 到 65535 之间的整数。');
  }
  return options;
}

function ensureRegularFile(file, label) {
  let stat;
  try {
    stat = fs.statSync(file);
  } catch (error) {
    fail(`${label}不存在或无法访问: ${file}: ${error.message}`);
  }
  if (!stat.isFile()) fail(`${label}必须是普通文件: ${file}`);
}

function escapeHtml(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function scriptJson(value) {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

// 注入渲染产物的滚动保持脚本：sandbox iframe 跨源，父子页面只能 postMessage 通信。
// 与 web-mcp PREVIEW_LINK_HELPER_SCRIPT 的滚动段保持同一消息协议。
const SCROLL_KEEPER_SCRIPT = `<script>(function() {
  'use strict';
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
  // srcdoc 文档的 base URL 继承父页面地址：页内锚点点击会把 iframe 导航到
  // 父页面 URL 而非页内滚动。统一拦截为页内滚动（与 web-mcp 预览同一行为）。
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
}());</script>`;

function injectScrollKeeper(rendered) {
  // 编辑时每次更新都会重建 iframe；只在预览产物中关闭入场及平滑滚动，
  // 避免重渲染和恢复滚动位置时反复出现下滑动画，不影响离线成品。
  const style = '<style>html { scroll-behavior: auto; } .container { animation: none; }</style>';
  const headEnd = rendered.lastIndexOf('</head>');
  if (headEnd !== -1) rendered = rendered.slice(0, headEnd) + style + rendered.slice(headEnd);
  // 锚定文档末尾真正的 </body>：内联 vendor 脚本字符串里也可能出现该片段
  const index = rendered.lastIndexOf('</body>');
  if (index === -1) return rendered + SCROLL_KEEPER_SCRIPT;
  return rendered.slice(0, index) + SCROLL_KEEPER_SCRIPT + rendered.slice(index);
}

function previewPage({ initialMarkdown, fileName }) {
  const pageTitle = `AI Docs 实时预览 · ${fileName}`;
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(pageTitle)}</title>
<style>
:root { color-scheme: light dark; --bg: #ffffff; --panel: #fafafa; --text: #171717; --muted: #737373; --border: #e5e5e5; --accent: #2563eb; --accent-strong: #1d4ed8; --accent-fg: #ffffff; --accent-bg: rgba(37, 99, 235, 0.08); --error: #dc2626; --radius-sm: 6px; --radius: 10px; --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04); --shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 4px 16px rgba(0, 0, 0, 0.05); }
@media (prefers-color-scheme: dark) { :root { --bg: #0a0a0a; --panel: #141414; --text: #fafafa; --muted: #a3a3a3; --border: #262626; --accent: #60a5fa; --accent-strong: #93c5fd; --accent-fg: #0a0a0a; --accent-bg: rgba(96, 165, 250, 0.12); --error: #f87171; --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4); --shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 4px 16px rgba(0, 0, 0, 0.35); } }
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body { min-width: 320px; overflow: hidden; color: var(--text); background: var(--bg); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; transition: background-color 160ms ease, color 160ms ease; }
::selection { background: var(--accent-bg); color: var(--accent-strong); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 5px; border: 2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }
button { font: inherit; }
.app { height: 100%; display: grid; grid-template-rows: auto minmax(0, 1fr); }
.toolbar { display: flex; align-items: center; gap: .65rem; min-height: 3.4rem; padding: .5rem 1rem; border-bottom: 1px solid var(--border); background: color-mix(in srgb, var(--bg) 92%, transparent); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
.brand { display: inline-flex; align-items: center; gap: .55rem; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 650; font-size: .95rem; letter-spacing: -0.01em; }
.toolbar-actions { margin-left: auto; display: flex; align-items: center; gap: .35rem; }
.toolbar button { min-height: 2rem; padding: .25rem .7rem; color: var(--muted); background: transparent; border: 1px solid transparent; border-radius: 0; cursor: pointer; font-size: .84rem; transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease; }
.toolbar button:hover { background: var(--panel); color: var(--text); }
.toolbar button:disabled { cursor: default; opacity: .55; }
.toolbar button.primary { background: var(--accent); color: var(--accent-fg); border-color: transparent; font-weight: 600; box-shadow: var(--shadow-sm); }
.toolbar button.primary:hover { background: var(--accent-strong); color: var(--accent-fg); }
.status { max-width: min(45vw, 34rem); overflow: hidden; color: var(--muted); font-size: .78rem; text-overflow: ellipsis; white-space: nowrap; }
.status.is-error { color: var(--error); }
.workspace { --editor-width: 50%; min-height: 0; display: grid; grid-template-columns: minmax(18rem, var(--editor-width)) .55rem minmax(0, 1fr); }
.panel { min-width: 0; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); }
.panel-label { display: flex; align-items: center; min-height: 2.25rem; padding: .35rem .9rem; color: var(--muted); background: var(--panel); border-bottom: 1px solid var(--border); font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.editor-panel { border-right: 1px solid var(--border); }
#editor { width: 100%; height: 100%; resize: none; padding: 1.1rem 1.2rem; color: var(--text); background: var(--bg); border: 0; outline: 0; caret-color: var(--accent); font: .88rem/1.65 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace; tab-size: 2; }
#preview { width: 100%; height: 100%; border: 0; background: var(--bg); }
#splitter { z-index: 2; margin-left: -1px; background: var(--panel); border-right: 1px solid var(--border); cursor: col-resize; touch-action: none; transition: background-color 120ms ease; }
#splitter:hover, #splitter.is-dragging { background: var(--accent); }
@media (max-width: 860px) { body { overflow: auto; } .app { min-height: 100%; height: auto; grid-template-rows: auto auto; } .toolbar { flex-wrap: wrap; } .toolbar-actions { margin-left: 0; } .status { order: 3; flex-basis: 100%; max-width: 100%; } .workspace { min-height: calc(100vh - 5.5rem); grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(19rem, 48vh) minmax(19rem, 52vh); } #splitter { display: none; } .editor-panel { border-right: 0; border-bottom: 1px solid var(--border); } }
</style>
</head>
<body>
<main class="app">
  <header class="toolbar">
    <strong class="brand">AI Docs 实时预览 · ${escapeHtml(fileName)}</strong>
    <div class="toolbar-actions">
      <button id="render" type="button" title="立即渲染（Ctrl/⌘ + Enter）">立即渲染</button>
      <button id="save" type="button" class="primary" title="保存到输入 Markdown 文件（Ctrl/⌘ + S）">保存</button>
    </div>
    <span id="status" class="status" role="status" aria-live="polite">准备就绪</span>
  </header>
  <section id="workspace" class="workspace">
    <section class="panel editor-panel" aria-label="Markdown 编辑器">
      <div class="panel-label">Markdown 编辑器</div>
      <textarea id="editor" aria-label="Markdown 编辑器" spellcheck="false"></textarea>
    </section>
    <div id="splitter" role="separator" aria-label="调整编辑器与预览区域宽度" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow="50" tabindex="0"></div>
    <section class="panel" aria-label="渲染结果">
      <div class="panel-label">渲染结果</div>
      <iframe id="preview" title="AI Docs 渲染结果" sandbox="allow-scripts allow-downloads allow-modals"></iframe>
    </section>
  </section>
</main>
<script>
(function() {
  'use strict';
  var initialMarkdown = ${scriptJson(initialMarkdown)};
  var editor = document.getElementById('editor');
  var preview = document.getElementById('preview');
  var status = document.getElementById('status');
  var renderButton = document.getElementById('render');
  var saveButton = document.getElementById('save');
  var workspace = document.getElementById('workspace');
  var splitter = document.getElementById('splitter');
  var renderTimer = 0;
  var latestRequest = 0;
  var dragging = false;
  var previewScrollState = null;
  var restoreToken = 0;
  var editorSyncTarget = null;
  var accessKey = new URLSearchParams(window.location.search).get('key') || '';

  editor.value = initialMarkdown;

  function setStatus(message, error) {
    status.textContent = message;
    status.classList.toggle('is-error', Boolean(error));
    status.title = message;
  }

  function request(path, payload) {
    var headers = { 'Content-Type': 'application/json' };
    if (accessKey) headers['Authorization'] = 'Bearer ' + accessKey;
    return fetch(path, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(payload)
    }).then(function(response) {
      return response.json().catch(function() { return {}; }).then(function(body) {
        if (!response.ok) throw new Error(body.error || '请求失败（HTTP ' + response.status + '）。');
        return body;
      });
    });
  }

  function render() {
    window.clearTimeout(renderTimer);
    var requestId = ++latestRequest;
    setStatus('正在使用 AI Docs renderer 渲染…');
    renderButton.disabled = true;
    request('/render', { markdown: editor.value }).then(function(result) {
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
    }).finally(function() {
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
    request('/save', { markdown: editor.value }).then(function() {
      setStatus('已保存到输入 Markdown 文件');
    }).catch(function(error) {
      setStatus(error.message || '保存失败。', true);
    }).finally(function() {
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
</script>
</body>
</html>`;
}

function openBrowser(url) {
  let command;
  let args;
  if (process.platform === 'darwin') {
    command = 'open';
    args = [url];
  } else if (process.platform === 'win32') {
    command = 'cmd';
    args = ['/c', 'start', '', url];
  } else {
    command = 'xdg-open';
    args = [url];
  }
  const child = childProcess.spawn(command, args, { detached: true, stdio: 'ignore' });
  child.unref();
}

function sendJson(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff'
  });
  response.end(body);
}

function sendHtml(response, body) {
  response.writeHead(200, {
    'Content-Type': 'text/html; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff'
  });
  response.end(body);
}

function readJsonBody(request) {
  return new Promise(function(resolve, reject) {
    const declaredSize = Number(request.headers['content-length']);
    if (Number.isFinite(declaredSize) && declaredSize > MAX_MARKDOWN_BYTES + 1024) {
      reject(new RequestError(413, `Markdown 不能超过 ${MAX_MARKDOWN_BYTES / (1024 * 1024)} MiB。`));
      return;
    }
    let received = 0;
    const chunks = [];
    let finished = false;
    function finish(callback, value) {
      if (finished) return;
      finished = true;
      callback(value);
    }
    request.on('data', function(chunk) {
      received += chunk.length;
      if (received > MAX_MARKDOWN_BYTES + 1024) {
        finish(reject, new RequestError(413, `Markdown 不能超过 ${MAX_MARKDOWN_BYTES / (1024 * 1024)} MiB。`));
        request.resume();
        return;
      }
      chunks.push(chunk);
    });
    request.on('error', function(error) { finish(reject, error); });
    request.on('end', function() {
      if (finished) return;
      let value;
      try {
        value = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      } catch (error) {
        finish(reject, new RequestError(400, '请求正文必须是有效 JSON。'));
        return;
      }
      if (!value || typeof value !== 'object' || Array.isArray(value) || typeof value.markdown !== 'string') {
        finish(reject, new RequestError(400, '请求正文必须包含 markdown 字符串。'));
        return;
      }
      if (Buffer.byteLength(value.markdown, 'utf8') > MAX_MARKDOWN_BYTES) {
        finish(reject, new RequestError(413, `Markdown 不能超过 ${MAX_MARKDOWN_BYTES / (1024 * 1024)} MiB。`));
        return;
      }
      finish(resolve, value);
    });
  });
}

function renderFailure(error) {
  const output = [error && error.stderr, error && error.stdout, error && error.message]
    .filter(Boolean).join('\n').trim();
  return output || 'AI Docs renderer 未返回错误详情。';
}

async function writeAtomically(target, content) {
  const stat = await fs.promises.stat(target);
  if (!stat.isFile()) throw new RequestError(409, '输入 Markdown 文件已不再是普通文件，无法保存。');
  const temporary = path.join(path.dirname(target), `.${path.basename(target)}.ai-docs-preview-${process.pid}-${Date.now()}`);
  try {
    await fs.promises.writeFile(temporary, content, { encoding: 'utf8', mode: stat.mode & 0o777 });
    await fs.promises.rename(temporary, target);
  } finally {
    await fs.promises.rm(temporary, { force: true }).catch(function() {});
  }
}

async function main() {
  let options;
  try {
    options = parseArguments(process.argv.slice(2));
  } catch (error) {
    console.error(`预览启动失败: ${error.message || error}`);
    return 1;
  }

  const buildScript = path.join(__dirname, 'build.js');
  const inputRequested = path.resolve(options.input);
  let inputFile;
  try {
    inputFile = fs.realpathSync(inputRequested);
    ensureRegularFile(inputFile, '输入文件');
    if (fs.statSync(inputFile).size > MAX_MARKDOWN_BYTES) {
      fail(`输入 Markdown 不能超过 ${MAX_MARKDOWN_BYTES / (1024 * 1024)} MiB。`);
    }
    if (options.config) {
      options.config = fs.realpathSync(path.resolve(options.config));
      ensureRegularFile(options.config, '配置文件');
    }
  } catch (error) {
    console.error(`预览启动失败: ${error.message || error}`);
    return 1;
  }

  let workspace;
  try {
    workspace = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'ai-docs-preview-'));
  } catch (error) {
    console.error(`预览启动失败: 无法创建临时工作区: ${error.message || error}`);
    return 1;
  }
  const temporaryInput = path.join(workspace, path.basename(inputFile));
  const temporaryOutput = path.join(workspace, 'preview.html');
  let page;
  try {
    page = previewPage({
      initialMarkdown: await fs.promises.readFile(inputFile, 'utf8'),
      fileName: path.basename(inputFile)
    });
  } catch (error) {
    await fs.promises.rm(workspace, { recursive: true, force: true });
    console.error(`预览启动失败: 无法读取输入 Markdown: ${error.message || error}`);
    return 1;
  }
  let renderTail = Promise.resolve();

  function renderMarkdown(markdown) {
    const job = renderTail.then(async function() {
      await fs.promises.writeFile(temporaryInput, markdown, 'utf8');
      const args = ['--input', temporaryInput, '--output', temporaryOutput, '--output-mode', 'single'];
      if (options.config) args.push('--config', options.config);
      if (options.title) args.push('--title', options.title);
      try {
        await execFile(process.execPath, [buildScript].concat(args), {
          cwd: path.dirname(buildScript),
          maxBuffer: MAX_BUILD_OUTPUT_BYTES
        });
      } catch (error) {
        throw new RequestError(422, renderFailure(error));
      }
      return injectScrollKeeper(await fs.promises.readFile(temporaryOutput, 'utf8'));
    });
    renderTail = job.catch(function() {});
    return job;
  }

  // 非 loopback 监听时所有接口都要求进程级随机访问令牌：预览页内嵌源文件内容，
  // /save 还会覆盖源文件，没有鉴权会让任何能连通端口的客户端改写本地 Markdown。
  const capability = isLoopbackHost(options.host) ? '' : crypto.randomBytes(24).toString('base64url');

  function tokenEquals(candidate) {
    if (typeof candidate !== 'string' || !capability) return false;
    const left = Buffer.from(candidate);
    const right = Buffer.from(capability);
    return left.length === right.length && crypto.timingSafeEqual(left, right);
  }

  function hasAccess(request) {
    if (!capability) return true;
    const header = request.headers['authorization'] || '';
    if (header.startsWith('Bearer ') && tokenEquals(header.slice(7))) return true;
    const key = new URL(request.url, 'http://127.0.0.1').searchParams.get('key') || '';
    return tokenEquals(key);
  }

  const server = http.createServer(async function(request, response) {
    const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
    try {
      if (!hasAccess(request)) {
        throw new RequestError(401, '预览需要有效的访问令牌：请使用启动时打印的带 key 参数的访问地址。');
      }
      if (request.method === 'GET' && pathname === '/') {
        sendHtml(response, page);
        return;
      }
      if (request.method === 'POST' && pathname === '/render') {
        const body = await readJsonBody(request);
        const html = await renderMarkdown(body.markdown);
        sendJson(response, 200, { html });
        return;
      }
      if (request.method === 'POST' && pathname === '/save') {
        const body = await readJsonBody(request);
        await writeAtomically(inputFile, body.markdown);
        sendJson(response, 200, { saved: true });
        return;
      }
      sendJson(response, 404, { error: '请求的预览资源不存在。' });
    } catch (error) {
      if (!response.headersSent) {
        sendJson(response, error instanceof RequestError ? error.status : 500, {
          error: error.message || '预览服务器发生未知错误。'
        });
      } else {
        response.destroy();
      }
    }
  });

  try {
    await new Promise(function(resolve, reject) {
      server.once('error', reject);
      server.listen(options.port, options.host, resolve);
    });
  } catch (error) {
    await fs.promises.rm(workspace, { recursive: true, force: true });
    console.error(`预览启动失败: 无法监听 ${options.host}:${options.port}: ${error.message || error}`);
    return 1;
  }

  const address = server.address();
  const browserHost = options.host === '0.0.0.0' || options.host === '::' ? '127.0.0.1' : options.host;
  const urlHost = browserHost.includes(':') && !browserHost.startsWith('[') ? `[${browserHost}]` : browserHost;
  const url = `http://${urlHost}:${address.port}/`;
  const accessUrl = capability ? `${url}?key=${encodeURIComponent(capability)}` : url;
  console.log(`预览文件: ${inputFile}`);
  console.log(`访问地址: ${accessUrl}`);
  if (capability) console.log('非 loopback 监听：页面与渲染/保存接口都需要上述地址中的访问令牌（key 参数）。');
  console.log('编辑器: 左侧 Markdown；右侧 AI Docs renderer 结果；点击“保存”才会写回源文件。');
  if (options.open) openBrowser(accessUrl);

  let shuttingDown = false;
  async function shutdown(signal) {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`\n预览服务器已停止（${signal}）。`);
    await new Promise(function(resolve) {
      if (!server.listening) {
        resolve();
        return;
      }
      server.close(resolve);
    });
    await fs.promises.rm(workspace, { recursive: true, force: true });
  }
  process.once('SIGINT', function() { shutdown('SIGINT').then(function() { process.exit(0); }); });
  process.once('SIGTERM', function() { shutdown('SIGTERM').then(function() { process.exit(0); }); });
  return new Promise(function(resolve) {
    server.once('close', function() { resolve(0); });
  });
}

main().then(function(code) {
  if (code) process.exitCode = code;
}).catch(function(error) {
  console.error(`预览启动失败: ${error.stack || error}`);
  process.exitCode = 1;
});
