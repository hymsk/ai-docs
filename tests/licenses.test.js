#!/usr/bin/env node
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-docs-licenses-'));
try {
  const input = path.join(temporary, 'document.md');
  fs.writeFileSync(input, '# License smoke\n\nHello.\n');
  for (const mode of ['single', 'multi']) {
    const output = path.join(temporary, mode + '.html');
    const result = spawnSync(process.execPath, [path.join(root, 'scripts/build.js'),
      '--input', input, '--output', output, '--output-mode', mode], { encoding: 'utf8', cwd: temporary });
    assert.strictEqual(result.status, 0, result.stderr);
    const html = fs.readFileSync(output, 'utf8');
    assert.match(html, /id="ai-docs-licenses"/);
    assert.match(html, /GNU AFFERO GENERAL PUBLIC LICENSE/);
    assert.match(html, /Permission is hereby granted/);
    assert.match(html, /licenses\/echarts-5\.6\.0\/NOTICE/);
    assert.match(html, /licenses\/highlight\.js-11\.11\.1\/LICENSE/);
    const identity = html.match(/id="ai-docs-source-id">([a-f0-9]{64})</);
    assert.ok(identity, 'HTML must identify exact renderer materials');
    assert.ok(html.includes(fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim()));
    if (mode === 'single') fs.writeFileSync(path.join(temporary, 'identity'), identity[1]);
    else assert.strictEqual(identity[1], fs.readFileSync(path.join(temporary, 'identity'), 'utf8'));
  }
  console.log('License embedding tests passed (single and multi).');
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
