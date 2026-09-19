#!/usr/bin/env node
/**
 * Verify the generated component index and its query interface.
 */

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const skillDir = path.resolve(__dirname, '..');
const script = path.join(skillDir, 'scripts', 'build-component-index.js');
const indexPath = path.join(skillDir, 'references', 'components', 'index.json');

function run(args) {
  return childProcess.spawnSync(process.execPath, [script].concat(args), {
    cwd: skillDir,
    encoding: 'utf8'
  });
}

const check = run(['--check']);
assert.strictEqual(check.status, 0, check.stderr || check.stdout);

const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));
assert.deepStrictEqual(
  index.components.map((component) => component.component),
  ['echarts', 'katex', 'layouts', 'markmap', 'mermaid']
);
assert(index.components.every((component) => component.documents.length > 0));

const query = run(['--query', '依赖 拓扑']);
assert.strictEqual(query.status, 0, query.stderr || query.stdout);
assert.match(query.stdout, /mermaid/);
assert.match(query.stdout, /mermaid\/flowchart\.md/);
assert.doesNotMatch(query.stdout, /graphviz/);

console.log('ai-docs component index tests passed');
