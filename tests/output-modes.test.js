#!/usr/bin/env node
/* eslint-disable no-console */
const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const skillDir = path.resolve(__dirname, '..');
const buildScript = path.join(skillDir, 'scripts', 'build.js');
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-docs-output-test-'));

function write(relativePath, content) {
  const file = path.join(tempDir, relativePath);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content, 'utf8');
  return file;
}

function run(args, cwd) {
  return childProcess.spawnSync(process.execPath, [buildScript].concat(args), {
    cwd: cwd || tempDir,
    encoding: 'utf8'
  });
}

function assertSuccess(result, description) {
  assert.strictEqual(result.status, 0, `${description}\n${result.stderr || result.stdout}`);
}

function assertFailure(result, pattern, description) {
  assert.notStrictEqual(result.status, 0, description);
  assert.match(result.stderr, pattern, `${description}\n${result.stderr}`);
}

// License banners are retained as escaped attribution text, not executable code.
function executableScripts(html) {
  return Array.from(html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi), match => match[1]).join('\n');
}

try {
  const plain = write('plain.md', '# Plain\n\nOnly text.\n');
  const plainOutput = path.join(tempDir, 'plain.html');
  assertSuccess(run(['--input', plain, '--output', plainOutput]), '纯文本单文件应成功构建');
  const plainHtml = fs.readFileSync(plainOutput, 'utf8');
  assert.match(executableScripts(plainHtml), /markdown-it 14\.3\.2/, '基础 Markdown 解析器应内联');
  assert.doesNotMatch(executableScripts(plainHtml), /Highlight\.js v11\.11\.1/, '未使用代码块时不应内联 Highlight.js');
  assert.doesNotMatch(plainHtml, /__esbuild_esm_mermaid/, '未使用 Mermaid 时不应内联 Mermaid');
  assert.doesNotMatch(plainHtml, /transformerVersions/, '未使用 Markmap 时不应内联 Markmap Lib');
  assert.doesNotMatch(plainHtml, /KaTeX parse error/, '未使用公式时不应内联 KaTeX');

  const code = write('code.md', '# Code\n\n```javascript\nconsole.log(1);\n```\n');
  const codeOutput = path.join(tempDir, 'code.html');
  assertSuccess(run(['--input', code, '--output', codeOutput]), '代码单文件应成功构建');
  const codeHtml = fs.readFileSync(codeOutput, 'utf8');
  assert.match(executableScripts(codeHtml), /Highlight\.js v11\.11\.1/, '普通代码块应加载 Highlight.js');
  assert.match(codeHtml, /Theme: GitHub/, '普通代码块应加载高亮样式');
  assert.doesNotMatch(codeHtml, /__esbuild_esm_mermaid/, '普通代码块不应加载 Mermaid');

  const features = write('features.md', '# Features\n\n$E = mc^2$\n\n```mermaid\nflowchart LR\n  A --> B\n```\n\n```markmap\n# Root\n## Child\n```\n');
  const featureOutput = path.join(tempDir, 'features.html');
  assertSuccess(run(['--input', features, '--output', featureOutput]), '功能单文件应成功构建');
  const featureHtml = fs.readFileSync(featureOutput, 'utf8');
  assert.match(featureHtml, /__esbuild_esm_mermaid/, 'Mermaid fence 应加载 Mermaid');
  assert.match(featureHtml, /https:\/\/d3js\.org v7\.8\.5/, 'Markmap 应加载 D3');
  assert.match(featureHtml, /"markmap-lib": "0\.17\.2"/, 'Markmap 应加载 Markmap Lib');
  assert.match(featureHtml, /this\.markmap = this\.markmap \|\| \{\}, d3/, 'Markmap 应加载 Markmap View');
  assert.match(featureHtml, /KaTeX parse error/, '公式和 Markmap 依赖应加载 KaTeX');

  const fenceVariants = write('fence-variants.md', '# Variants\n\n$ x + y $\n\n   ~~~~mermaid\nflowchart LR\n  A --> B\n   ~~~~\n\n~~~markmap\n# Root\n## Child\n~~~\n');
  const fenceVariantsOutput = path.join(tempDir, 'fence-variants.html');
  assertSuccess(run(['--input', fenceVariants, '--output', fenceVariantsOutput]), '缩进、波浪线和四 marker fence 应成功构建');
  const fenceVariantsHtml = fs.readFileSync(fenceVariantsOutput, 'utf8');
  assert.match(fenceVariantsHtml, /__esbuild_esm_mermaid/, '缩进四 marker Mermaid 应加载 Mermaid');
  assert.match(fenceVariantsHtml, /"markmap-lib": "0\.17\.2"/, '波浪线 Markmap 应加载 Markmap');
  assert.match(fenceVariantsHtml, /KaTeX parse error/, '含空白的公式应加载 KaTeX');
  const unsupportedTildeDot = write('unsupported-tilde-dot.md', '~~~dot\ndigraph G { A -> B }\n~~~\n');
  assertFailure(run(['--input', unsupportedTildeDot, '--output', path.join(tempDir, 'unsupported-tilde-dot.html')]), /unsupported-tilde-dot\.md:1: 不支持 dot\/graphviz 图表代码块/, '波浪线 dot fence 必须明确失败');

  const unsafeTildeMarkmap = write('unsafe-tilde-markmap.md', '~~~markmap\n# Root\n<img src=x onerror=alert(1)>\n~~~\n');
  assertFailure(run(['--input', unsafeTildeMarkmap, '--output', path.join(tempDir, 'unsafe-tilde.html')]), /Markmap 源码不能包含原始 HTML/, '波浪线 Markmap 不能绕过原始 HTML 校验');

  const nestedFences = write('nested-fences.md', '# Nested\n\n> ~~~mermaid\n> flowchart LR\n>   A --> B\n> ~~~\n\n- Item\n\n  ~~~javascript\n  console.log(1);\n  ~~~\n');
  const nestedFencesOutput = path.join(tempDir, 'nested-fences.html');
  assertSuccess(run(['--input', nestedFences, '--output', nestedFencesOutput]), '容器内 fence 应成功构建');
  const nestedFencesHtml = fs.readFileSync(nestedFencesOutput, 'utf8');
  assert.match(nestedFencesHtml, /__esbuild_esm_mermaid/, 'blockquote Mermaid 应加载 Mermaid');
  assert.match(nestedFencesHtml, /Highlight\.js v11\.11\.1/, '列表内普通代码 fence 应加载 Highlight.js');
  const unsupportedQuotedGraphviz = write('unsupported-quoted-graphviz.md', '# Nested\n\n> ~~~graphviz\n> digraph Nested { A -> B }\n> ~~~\n');
  assertFailure(run(['--input', unsupportedQuotedGraphviz, '--output', path.join(tempDir, 'unsupported-quoted-graphviz.html')]), /unsupported-quoted-graphviz\.md:3: 不支持 dot\/graphviz 图表代码块/, 'blockquote graphviz fence 必须明确失败');

  const unsafeQuotedMarkmap = write('unsafe-quoted-markmap.md', '> ~~~markmap\n> # Root <img src=x onerror=alert(1)>\n> ~~~\n');
  assertFailure(run(['--input', unsafeQuotedMarkmap, '--output', path.join(tempDir, 'unsafe-quoted.html')]), /Markmap 源码不能包含原始 HTML/, 'blockquote Markmap 不能绕过原始 HTML 校验');

  const multiOutputDir = path.join(tempDir, 'multi');
  assertSuccess(run([
    '--input', features,
    '--output-mode', 'multi',
    '--output-dir', multiOutputDir,
    '--output-name', 'index.html',
    '--static-dir', 'assets/vendor',
    '--public-path', '/docs/assets/vendor/'
  ]), '多文件本地模式应成功构建');
  const multiOutput = path.join(multiOutputDir, 'index.html');
  const multiHtml = fs.readFileSync(multiOutput, 'utf8');
  assert.match(multiHtml, /<script src="\/docs\/assets\/vendor\/markdown-it\.min\.js"><\/script>/);
  assert.match(multiHtml, /<link rel="stylesheet" href="\/docs\/assets\/vendor\/katex\.min\.css">/);
  assert.doesNotMatch(executableScripts(multiHtml), /markdown-it 14\.3\.2/, '多文件 HTML 不应内联 vendor 源码');
  const emittedResources = fs.readdirSync(path.join(multiOutputDir, 'assets', 'vendor')).sort();
  assert.deepStrictEqual(emittedResources, [
    'd3.min.js', 'katex.min.css', 'katex.min.js', 'markdown-it.min.js',
    'markmap-lib.browser.js', 'markmap-view.browser.js', 'mermaid.min.js'
  ]);
  const mermaidSource = fs.readFileSync(path.join(multiOutputDir, 'assets', 'vendor', 'mermaid.min.js'), 'utf8');
  const mermaidContext = require('vm').createContext({ console, setTimeout, clearTimeout });
  require('vm').runInContext(mermaidSource, mermaidContext, { timeout: 10000 });
  assert.strictEqual(typeof mermaidContext.mermaid.initialize, 'function', '外置 Mermaid 应导出浏览器初始化 API');
  assert.strictEqual(typeof mermaidContext.mermaid.render, 'function', '外置 Mermaid 应导出浏览器渲染 API');
  assert.match(fs.readFileSync(path.join(multiOutputDir, 'assets', 'vendor', 'd3.min.js'), 'utf8'), /var d3=globalThis\.d3;/, '外置 D3 应提供 Markmap 需要的全局变量');
  assert.doesNotMatch(fs.readFileSync(path.join(multiOutputDir, 'assets', 'vendor', 'katex.min.css'), 'utf8'), /@font-face/, '外置 KaTeX CSS 应保持当前无字体包行为');

  const configDir = path.join(tempDir, 'config-project');
  const configuredSource = write('config-project/document.md', '# Configured\n');
  const config = write('config-project/ai-docs.json', JSON.stringify({
    output: { mode: 'multi', directory: './public/docs', fileName: 'index.html' },
    resources: { directory: 'static', publicPath: './static/' },
    server: { directory: './public/docs', host: '127.0.0.1', port: 0, open: false }
  }));
  assertSuccess(run(['--input', configuredSource, '--config', config], path.dirname(tempDir)), '配置相对路径应以配置文件目录为准');
  const configuredHtml = fs.readFileSync(path.join(configDir, 'public', 'docs', 'index.html'), 'utf8');
  assert.match(configuredHtml, /<script src="\.\/static\/markdown-it\.min\.js"><\/script>/);
  assert(fs.existsSync(path.join(configDir, 'public', 'docs', 'static', 'markdown-it.min.js')));

  assertFailure(run(['--input', plain, '--output', path.join(tempDir, 'invalid.html'), '--output-mode', 'remote']), /output\.mode 必须是 single 或 multi/, '未知输出模式必须失败');
  assertFailure(run(['--input', plain, '--output-mode', 'multi', '--output-dir', tempDir, '--output-name', 'bad/name.html']), /只能是文件名/, '输出文件名不能包含目录');
  assertFailure(run(['--input', plain, '--output-mode', 'multi', '--output-dir', tempDir, '--static-dir', '../outside']), /必须是输出目录内的相对目录/, '静态目录不能越过输出目录');
  assertFailure(run(['--input', plain, '--output-mode', 'multi', '--output-dir', tempDir, '--public-path', 'https://example.com/static/']), /只接受本地 URL 路径/, '本地多文件模式不能配置远程 URL');
  assertFailure(run(['--input', plain, '--output-mode', 'multi', '--output-dir', tempDir, '--public-path', '/docs/static?v=1']), /包含不安全字符/, '本地资源 URL 不能包含 query');

  const symlinkOutput = path.join(tempDir, 'symlink-output');
  const outsideStatic = path.join(tempDir, 'outside-static');
  fs.mkdirSync(symlinkOutput);
  fs.mkdirSync(outsideStatic);
  fs.symlinkSync(outsideStatic, path.join(symlinkOutput, 'static'));
  assertFailure(run([
    '--input', plain,
    '--output-mode', 'multi',
    '--output-dir', symlinkOutput,
    '--output-name', 'index.html'
  ]), /不能包含软链接/, '静态目录软链接不能越过输出目录');

  const nestedSymlinkOutput = path.join(tempDir, 'nested-symlink-output');
  const nestedOutside = path.join(tempDir, 'nested-outside');
  fs.mkdirSync(nestedSymlinkOutput);
  fs.mkdirSync(nestedOutside);
  fs.symlinkSync(nestedOutside, path.join(nestedSymlinkOutput, 'assets'));
  assertFailure(run([
    '--input', plain,
    '--output-mode', 'multi',
    '--output-dir', nestedSymlinkOutput,
    '--output-name', 'index.html',
    '--static-dir', 'assets/vendor'
  ]), /不能包含软链接/, '静态目录中间组件不能通过软链接越界');
  assert(!fs.existsSync(path.join(nestedOutside, 'vendor')), '失败构建不能在输出边界外创建目录');

  const danglingOutput = path.join(tempDir, 'dangling-output');
  const danglingStatic = path.join(danglingOutput, 'static');
  const danglingTarget = path.join(tempDir, 'dangling-target.js');
  fs.mkdirSync(danglingStatic, { recursive: true });
  fs.symlinkSync(danglingTarget, path.join(danglingStatic, 'markdown-it.min.js'));
  assertFailure(run([
    '--input', plain,
    '--output-mode', 'multi',
    '--output-dir', danglingOutput,
    '--output-name', 'index.html'
  ]), /资源输出目标必须是普通文件/, '悬空资源目标软链接必须被拒绝');
  assert(!fs.existsSync(danglingTarget), '悬空软链接不能在输出目录外创建资源文件');

  const lateFailureOutput = path.join(tempDir, 'late-failure-output');
  const lateStatic = path.join(lateFailureOutput, 'static');
  fs.mkdirSync(lateStatic, { recursive: true });
  const preservedMarkdownIt = 'preserve existing markdown runtime';
  fs.writeFileSync(path.join(lateStatic, 'markdown-it.min.js'), preservedMarkdownIt, 'utf8');
  fs.symlinkSync(path.join(tempDir, 'late-dangling.js'), path.join(lateStatic, 'markmap-view.browser.js'));
  assertFailure(run([
    '--input', features,
    '--output-mode', 'multi',
    '--output-dir', lateFailureOutput,
    '--output-name', 'index.html'
  ]), /资源输出目标必须是普通文件/, '较晚资源目标失败时也必须在任何写入前退出');
  assert.strictEqual(fs.readFileSync(path.join(lateStatic, 'markdown-it.min.js'), 'utf8'), preservedMarkdownIt, '晚序预检失败不能覆盖前序已有资源');

  const hardLinkOutput = path.join(tempDir, 'hard-link-output');
  const hardLinkStatic = path.join(hardLinkOutput, 'static');
  fs.mkdirSync(hardLinkStatic, { recursive: true });
  const hardLinkOutside = path.join(tempDir, 'hard-link-outside.js');
  const hardLinkContent = 'preserve hard-linked file';
  fs.writeFileSync(hardLinkOutside, hardLinkContent, 'utf8');
  fs.linkSync(hardLinkOutside, path.join(hardLinkStatic, 'markdown-it.min.js'));
  assertFailure(run([
    '--input', plain,
    '--output-mode', 'multi',
    '--output-dir', hardLinkOutput,
    '--output-name', 'index.html'
  ]), /不能是硬链接/, '资源输出目标不能通过硬链接改写其他文件');
  assert.strictEqual(fs.readFileSync(hardLinkOutside, 'utf8'), hardLinkContent, '拒绝硬链接目标时不能改写其内容');

  const configRealDir = path.join(tempDir, 'config-real');
  const configLinkDir = path.join(tempDir, 'config-link');
  fs.mkdirSync(configRealDir);
  fs.mkdirSync(configLinkDir);
  const realConfig = path.join(configRealDir, 'ai-docs.json');
  fs.writeFileSync(realConfig, JSON.stringify({ output: { mode: 'multi', directory: './public', fileName: 'index.html' } }), 'utf8');
  const linkedConfig = path.join(configLinkDir, 'ai-docs.json');
  fs.symlinkSync(realConfig, linkedConfig);
  assertSuccess(run(['--input', plain, '--config', linkedConfig]), '配置软链接应按用户传入路径解析相对目录');
  assert(fs.existsSync(path.join(configLinkDir, 'public', 'index.html')), '构建器应以配置软链接所在目录解析相对输出路径');

  console.log('ai-docs output mode tests passed');
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}
