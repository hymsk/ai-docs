#!/usr/bin/env node
/* eslint-disable no-console */
const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');

const skillDir = path.resolve(__dirname, '..');
const serveScript = path.join(skillDir, 'scripts', 'serve.py');
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-docs-serve-test-'));

function waitForUrl(child) {
  return new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`服务器启动超时\n${output}`)), 8000);
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
      reject(new Error(`服务器提前退出，状态 ${code}\n${output}`));
    });
  });
}

function request(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => resolve({ status: response.statusCode, body }));
    }).on('error', (error) => reject(new Error(`${url}: ${error.message}`)));
  });
}

function run(args) {
  return childProcess.spawnSync('python3', [serveScript].concat(args), {
    cwd: skillDir,
    encoding: 'utf8'
  });
}

async function main() {
  const root = path.join(tempDir, 'public');
  fs.mkdirSync(path.join(root, 'nested'), { recursive: true });
  fs.writeFileSync(path.join(root, 'report.html'), '<!doctype html><title>AI Docs server test</title>', 'utf8');
  fs.writeFileSync(path.join(root, 'nested', 'note.txt'), 'nested file', 'utf8');
  const outsideFile = path.join(tempDir, 'outside.txt');
  const outsideDirectory = path.join(tempDir, 'outside-directory');
  fs.writeFileSync(outsideFile, 'outside secret', 'utf8');
  fs.mkdirSync(outsideDirectory);
  fs.writeFileSync(path.join(outsideDirectory, 'secret.txt'), 'directory secret', 'utf8');
  fs.symlinkSync(outsideFile, path.join(root, 'outside-file.txt'));
  fs.symlinkSync(outsideDirectory, path.join(root, 'outside-directory'));
  const config = path.join(tempDir, 'ai-docs.json');
  fs.writeFileSync(config, JSON.stringify({
    output: { directory: './public' },
    server: { host: '127.0.0.1', port: 0, open: false }
  }), 'utf8');

  const child = childProcess.spawn('python3', [serveScript, '--config', config], {
    cwd: skillDir,
    stdio: ['ignore', 'pipe', 'pipe']
  });

  try {
    const baseUrl = await waitForUrl(child);
    const listing = await request(baseUrl);
    assert.strictEqual(listing.status, 200);
    assert.match(listing.body, /Directory listing for \/|目录列表/);
    assert.match(listing.body, /report\.html/);
    assert.match(listing.body, /nested\//);

    const report = await request(new URL('report.html', baseUrl).toString());
    assert.strictEqual(report.status, 200);
    assert.match(report.body, /AI Docs server test/);

    const nested = await request(new URL('nested/', baseUrl).toString());
    assert.strictEqual(nested.status, 200);
    assert.match(nested.body, /note\.txt/);

    const outsideFileResponse = await request(new URL('outside-file.txt', baseUrl).toString());
    assert.strictEqual(outsideFileResponse.status, 403, '服务器必须拒绝指向根目录外文件的软链接');
    const outsideDirectoryResponse = await request(new URL('outside-directory/secret.txt', baseUrl).toString());
    assert.strictEqual(outsideDirectoryResponse.status, 403, '服务器必须拒绝指向根目录外目录的软链接');
  } finally {
    child.kill('SIGTERM');
    await new Promise((resolve) => child.once('exit', resolve));
  }

  const invalidConfig = path.join(tempDir, 'invalid.json');
  fs.writeFileSync(invalidConfig, JSON.stringify({ server: { directory: './public', prot: 8000 } }), 'utf8');
  const invalid = run(['--config', invalidConfig]);
  assert.notStrictEqual(invalid.status, 0);
  assert.match(invalid.stderr, /server 包含未知字段: prot/);

  const realConfigDir = path.join(tempDir, 'real-config');
  const linkedConfigDir = path.join(tempDir, 'linked-config');
  fs.mkdirSync(realConfigDir);
  fs.mkdirSync(linkedConfigDir);
  const realConfig = path.join(realConfigDir, 'ai-docs.json');
  fs.writeFileSync(realConfig, JSON.stringify({ server: { directory: './public' } }), 'utf8');
  const linkedRoot = path.join(linkedConfigDir, 'public');
  fs.mkdirSync(linkedRoot);
  const linkedConfig = path.join(linkedConfigDir, 'ai-docs.json');
  fs.symlinkSync(realConfig, linkedConfig);
  const linkedChild = childProcess.spawn('python3', [serveScript, '--config', linkedConfig, '--port', '0'], {
    cwd: skillDir,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  try {
    const linkedBaseUrl = await waitForUrl(linkedChild);
    const linkedListing = await request(linkedBaseUrl);
    assert.strictEqual(linkedListing.status, 200, '配置软链接应以用户传入路径所在目录解析服务目录');
  } finally {
    linkedChild.kill('SIGTERM');
    await new Promise((resolve) => linkedChild.once('exit', resolve));
  }
  fs.rmSync(tempDir, { recursive: true, force: true });
  console.log('ai-docs serve tests passed');
}

main().catch((error) => {
  fs.rmSync(tempDir, { recursive: true, force: true });
  console.error(error.stack || error);
  process.exit(1);
});
