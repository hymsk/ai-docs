#!/usr/bin/env node
/* eslint-disable no-console */
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const vm = require('vm');

const skillDir = path.resolve(__dirname, '..');
const previewScript = path.join(skillDir, 'scripts', 'preview.js');
const buildScript = path.join(skillDir, 'scripts', 'build.js');
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-docs-preview-test-'));

function waitForUrl(child) {
  return new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`预览服务器启动超时\n${output}`)), 8000);
    function inspect(chunk) {
      output += chunk.toString();
      const match = output.match(/访问地址: (http:\/\/[^\s]+)/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    }
    child.stdout.on('data', inspect);
    child.stderr.on('data', inspect);
    child.once('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`预览服务器提前退出，状态 ${code}\n${output}`));
    });
  });
}

function request(url, method, body, headers) {
  return new Promise((resolve, reject) => {
    const data = body == null ? '' : JSON.stringify(body);
    const target = new URL(url);
    const requestOptions = {
      hostname: target.hostname,
      port: target.port,
      path: target.pathname + target.search,
      method,
      headers: Object.assign({}, headers || {}, body == null ? {} : {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data)
      })
    };
    const clientRequest = http.request(requestOptions, (response) => {
      let responseBody = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { responseBody += chunk; });
      response.on('end', () => resolve({ status: response.statusCode, body: responseBody, headers: response.headers }));
    });
    clientRequest.on('error', reject);
    if (body != null) clientRequest.write(data);
    clientRequest.end();
  });
}

function run(command, args) {
  return childProcess.spawnSync(command, args, { cwd: skillDir, encoding: 'utf8' });
}

function assertScrollProtocol(rendered) {
  const script = rendered.match(/<script>\(function\(\) \{\n  'use strict';\n  var syncTarget = null;([\s\S]*?)<\/script>/);
  assert.ok(script, '预览应注入 iframe 滚动协议');
  const listeners = {};
  const sent = [];
  let headingTop = 560;
  const heading = { id: 'section-b', getBoundingClientRect: () => ({ top: headingTop - y }) };
  let y = 600;
  const doc = {
    documentElement: { scrollHeight: 2000, getAttribute: () => 'done' },
    querySelectorAll: () => [heading],
    getElementById: (id) => id === heading.id ? heading : null,
    addEventListener: () => {}
  };
  const win = {
    innerHeight: 1000,
    get scrollY() { return y; },
    addEventListener: (type, fn) => { listeners[type] = fn; },
    scrollTo: ({ top }) => { y = Math.max(0, Math.min(1000, top)); }
  };
  vm.runInNewContext(script[0].slice(8, -9), {
    window: win, document: doc, parent: { postMessage: (message) => sent.push(message) }, setTimeout: () => {}
  });
  listeners.scroll();
  assert.strictEqual(sent.at(-1).id, 'section-b');
  assert.strictEqual(sent.at(-1).ratio, .6);
  assert.strictEqual(sent.at(-1).offset, -40);
  listeners.message({ data: { type: 'ai-docs-scroll-sync', ratio: .25 } });
  assert.strictEqual(y, 250, '编辑区滚动应同步到预览区');
  listeners.scroll();
  assert.strictEqual(sent.at(-1).sync, true, '同步滚动不能再次驱动编辑区');
  headingTop = 760;
  listeners.message({ data: { type: 'ai-docs-scroll-restore', id: 'section-b', offset: -40, ratio: .6, token: 1 } });
  assert.strictEqual(y, 800, '前方内容增加后标题应保持原来的视口位置，而非旧像素高度');
  assert.strictEqual(sent.at(-1).type, 'ai-docs-scroll-restored');
  assert.strictEqual(sent.at(-1).token, 1);
  listeners.message({ data: { type: 'ai-docs-scroll-restore', id: 'missing', offset: 0, ratio: .5, token: 2 } });
  assert.strictEqual(y, 500, '锚点消失时回退到比例位置');
}

function assertWebScrollProtocol(script) {
  const start = script.indexOf('  var syncTarget = null;');
  const end = script.indexOf('}());</script>', start);
  assert.ok(start !== -1 && end > start, 'Web 编辑预览应包含滚动同步协议');
  const listeners = {};
  const sent = [];
  let y = 600;
  let headingTop = 560;
  const heading = { id: 'section-b', getBoundingClientRect: () => ({ top: headingTop - y }) };
  const document = {
    documentElement: { scrollHeight: 2000, getAttribute: () => 'done' },
    querySelectorAll: () => [heading],
    getElementById: (id) => id === heading.id ? heading : null
  };
  const window = {
    innerHeight: 1000,
    get scrollY() { return y; },
    addEventListener: (name, callback) => { listeners[name] = callback; },
    scrollTo: ({ top }) => { y = Math.max(0, Math.min(1000, top)); }
  };
  vm.runInNewContext(script.slice(start, end), {
    window, document, parent: { postMessage: (message) => sent.push(message) }, setTimeout: () => {}
  });
  listeners.scroll();
  assert.strictEqual(sent.at(-1).id, 'section-b');
  listeners.message({ data: { type: 'ai-docs-scroll-sync', ratio: .25 } });
  assert.strictEqual(y, 250);
  listeners.scroll();
  assert.strictEqual(sent.at(-1).sync, true);
  headingTop = 760;
  listeners.message({ data: { type: 'ai-docs-scroll-restore', id: 'section-b', offset: -40, ratio: .6, token: 3 } });
  assert.strictEqual(y, 800);
  assert.strictEqual(sent.at(-1).token, 3);
}

function assertEditorScrollProtocol(page) {
  const script = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).at(-1)[1];
  const listeners = {};
  const editorListeners = {};
  const frameListeners = {};
  const posted = [];
  const frame = { postMessage: (message) => posted.push(message) };
  const editor = {
    value: '', scrollTop: 0, scrollHeight: 2000, clientHeight: 1000,
    addEventListener: (type, callback) => { editorListeners[type] = callback; }
  };
  const preview = { style: {}, contentWindow: frame, addEventListener: (type, callback) => { frameListeners[type] = callback; } };
  const element = { disabled: false, classList: { toggle: () => {} }, addEventListener: () => {}, setAttribute: () => {}, getAttribute: () => '50' };
  const elements = { editor, preview, status: { ...element }, render: { ...element }, save: { ...element }, workspace: { ...element }, splitter: { ...element } };
  let resolveRender;
  const context = {
    document: { getElementById: (id) => elements[id], addEventListener: (type, callback) => { listeners[type] = callback; } },
    window: { location: { search: '' }, clearTimeout: () => {}, setTimeout: () => 1,
      addEventListener: (type, callback) => { listeners[type] = callback; } },
    URLSearchParams, fetch: () => new Promise((resolve) => { resolveRender = resolve; })
  };
  vm.runInNewContext(script, context);
  editor.scrollTop = 400;
  editorListeners.scroll();
  assert.strictEqual(posted.at(-1).type, 'ai-docs-scroll-sync');
  assert.strictEqual(posted.at(-1).ratio, .4);
  listeners.message({ source: frame, data: { type: 'ai-docs-scroll-state', ratio: .7, id: 'section-b', offset: -40, sync: false } });
  assert.strictEqual(editor.scrollTop, 700, '手动滚动预览应带动编辑器');
  editorListeners.scroll();
  assert.strictEqual(posted.length, 1, '程序同步不能反向回弹');
  resolveRender({ ok: true, json: () => Promise.resolve({ html: '<html></html>' }) });
  return new Promise((resolve) => setImmediate(resolve)).then(() => {
    assert.strictEqual(preview.style.visibility, 'hidden', '刷新前应遮住 iframe 的初始滚动位置');
    frameListeners.load();
    assert.strictEqual(posted.at(-1).type, 'ai-docs-scroll-restore');
    assert.strictEqual(posted.at(-1).id, 'section-b');
    assert.strictEqual(posted.at(-1).offset, -40);
    listeners.message({ source: frame, data: { type: 'ai-docs-scroll-restored', token: posted.at(-1).token } });
    assert.strictEqual(preview.style.visibility, '', '锚点恢复后再显示预览');
  });
}

async function close(child) {
  if (child.exitCode != null || child.signalCode != null) return;
  child.kill('SIGTERM');
  await new Promise((resolve) => child.once('exit', resolve));
}

async function main() {
  const source = path.join(tempDir, 'draft.md');
  fs.writeFileSync(source, '# 初始标题\n\n初始正文。\n', 'utf8');
  const child = childProcess.spawn(process.execPath, [previewScript, '--input', source, '--port', '0'], {
    cwd: skillDir,
    stdio: ['ignore', 'pipe', 'pipe']
  });

  try {
    const baseUrl = await waitForUrl(child);
    const page = await request(baseUrl, 'GET');
    assert.strictEqual(page.status, 200);
    assert.match(page.headers['content-type'], /^text\/html/);
    assert.match(page.body, /Markdown 编辑器/);
    assert.match(page.body, /渲染结果/);
    assert.match(page.body, /sandbox="allow-scripts allow-downloads allow-modals"/);
    assert.match(page.body, /AI Docs renderer/);
    assert.match(page.body, /初始标题/);
    await assertEditorScrollProtocol(page.body);

    const changedMarkdown = '# 新标题\n\n```mermaid\nflowchart LR\n  A --> B\n```\n';
    const render = await request(new URL('render', baseUrl).toString(), 'POST', { markdown: changedMarkdown });
    assert.strictEqual(render.status, 200, render.body);
    const rendered = JSON.parse(render.body);
    assert.match(rendered.html, /新标题/);
    assert.match(rendered.html, /mermaid/);
    assert.match(rendered.html, /html \{ scroll-behavior: auto; \} \.container \{ animation: none; \}/, '编辑预览应关闭重渲染的下滑动效');
    assert.ok(rendered.html.indexOf('.container { animation: none; }') > rendered.html.indexOf('animation: viewer-in 260ms'), '预览覆盖样式应在 renderer 样式之后');
    assert.ok(rendered.html.indexOf('.container { animation: none; }') < rendered.html.indexOf('</head>'), '预览覆盖样式应留在 head 内');
    assertScrollProtocol(rendered.html);
    const webPreviewSource = fs.readFileSync(path.join(skillDir, 'web-mcp', 'source', 'ai_docs_preview.py'), 'utf8');
    assertWebScrollProtocol(webPreviewSource);
    assert.strictEqual(fs.readFileSync(source, 'utf8'), '# 初始标题\n\n初始正文。\n', '预览渲染不能自动修改源文件');

    const save = await request(new URL('save', baseUrl).toString(), 'POST', { markdown: changedMarkdown });
    assert.strictEqual(save.status, 200, save.body);
    assert.strictEqual(JSON.parse(save.body).saved, true);
    assert.strictEqual(fs.readFileSync(source, 'utf8'), changedMarkdown, '保存 API 应写回 Markdown 源文件');

    const invalidRender = await request(new URL('render', baseUrl).toString(), 'POST', { markdown: '```dot\ndigraph G { A -> B }\n```\n' });
    assert.strictEqual(invalidRender.status, 422);
    assert.match(JSON.parse(invalidRender.body).error, /不支持 dot\/graphviz/);

    const forbidden = await request(new URL('secret.txt', baseUrl).toString(), 'GET');
    assert.strictEqual(forbidden.status, 404, '预览服务器不应提供任意本地文件');
  } finally {
    await close(child);
  }

  const shortcutSource = path.join(tempDir, 'shortcut.md');
  fs.writeFileSync(shortcutSource, '# 快捷入口\n', 'utf8');
  const shortcut = childProcess.spawn(process.execPath, [buildScript, '--preview', '--input', shortcutSource, '--port', '0'], {
    cwd: skillDir,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  try {
    const shortcutUrl = await waitForUrl(shortcut);
    const shortcutPage = await request(shortcutUrl, 'GET');
    assert.strictEqual(shortcutPage.status, 200);
    assert.match(shortcutPage.body, /快捷入口/);
  } finally {
    await close(shortcut);
  }

  // 非 loopback 监听必须为页面和写接口启用访问令牌。
  const remoteSource = path.join(tempDir, 'remote.md');
  fs.writeFileSync(remoteSource, '# 远程预览\n', 'utf8');
  const remote = childProcess.spawn(process.execPath, [previewScript, '--input', remoteSource, '--host', '0.0.0.0', '--port', '0'], {
    cwd: skillDir,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  try {
    const remoteUrl = await waitForUrl(remote);
    assert.match(remoteUrl, /\?key=/, '非 loopback 预览地址应携带访问令牌');
    const parsed = new URL(remoteUrl);
    const accessKey = parsed.searchParams.get('key');
    const plainBase = `http://${parsed.hostname}:${parsed.port}/`;

    const deniedPage = await request(plainBase, 'GET');
    assert.strictEqual(deniedPage.status, 401, '无令牌页面请求必须被拒绝');
    const deniedSave = await request(new URL('save', plainBase).toString(), 'POST', { markdown: '# 篡改\n' });
    assert.strictEqual(deniedSave.status, 401, '无令牌保存必须被拒绝');
    assert.strictEqual(fs.readFileSync(remoteSource, 'utf8'), '# 远程预览\n', '未授权保存不得修改源文件');
    const wrongKey = await request(`${plainBase}?key=wrong-token`, 'GET');
    assert.strictEqual(wrongKey.status, 401, '错误令牌必须被拒绝');

    const page = await request(remoteUrl, 'GET');
    assert.strictEqual(page.status, 200, '带 key 的页面请求应成功');
    const saved = await request(new URL('save', plainBase).toString(), 'POST', { markdown: '# 授权保存\n' }, { Authorization: `Bearer ${accessKey}` });
    assert.strictEqual(saved.status, 200, saved.body);
    assert.strictEqual(fs.readFileSync(remoteSource, 'utf8'), '# 授权保存\n', '授权保存应写回源文件');
  } finally {
    await close(remote);
  }

  const invalid = run(process.execPath, [previewScript, '--input', source, '--port', 'invalid']);
  assert.notStrictEqual(invalid.status, 0);
  assert.match(invalid.stderr, /--port 必须是 0 到 65535 之间的整数/);
  fs.rmSync(tempDir, { recursive: true, force: true });
  console.log('ai-docs preview tests passed');
}

main().catch((error) => {
  fs.rmSync(tempDir, { recursive: true, force: true });
  console.error(error.stack || error);
  process.exit(1);
});
