#!/usr/bin/env node
/* eslint-disable no-console */
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');

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

    const changedMarkdown = '# 新标题\n\n```mermaid\nflowchart LR\n  A --> B\n```\n';
    const render = await request(new URL('render', baseUrl).toString(), 'POST', { markdown: changedMarkdown });
    assert.strictEqual(render.status, 200, render.body);
    const rendered = JSON.parse(render.body);
    assert.match(rendered.html, /新标题/);
    assert.match(rendered.html, /mermaid/);
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
