#!/usr/bin/env node
/* eslint-disable no-console */
const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');

const toolDir = path.resolve(__dirname, '..');
const scriptsDir = path.join(toolDir, 'scripts');
const buildScript = path.join(scriptsDir, 'build.js');
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-docs-test-'));

function write(name, content) {
  const file = path.join(tempDir, name);
  fs.writeFileSync(file, content, 'utf8');
  return file;
}

function run(args) {
  return childProcess.spawnSync(process.execPath, [buildScript].concat(args), {
    cwd: toolDir,
    encoding: 'utf8'
  });
}

function assertSuccess(result, description) {
  assert.strictEqual(result.status, 0, `${description}\n${result.stderr || result.stdout}`);
}

function assertFailure(result, text, description) {
  assert.notStrictEqual(result.status, 0, description);
  assert.match(result.stderr, text, `${description}\n${result.stderr}`);
}

function renderClientMarkdown(html) {
  const script = Array.from(html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi), function(match) { return match[1]; }).at(-1);
  const stop = {};
  let rendered = '';
  function element() {
    return {
      style: { setProperty: function() {} },
      classList: { add: function() {}, remove: function() {}, toggle: function() { return false; }, contains: function() { return false; } },
      appendChild: function() {}, insertBefore: function() {}, setAttribute: function() {}, removeAttribute: function() {},
      addEventListener: function() {}, remove: function() {}, contains: function() { return false; },
      querySelector: function() { return null; }, querySelectorAll: function() { return []; }, getAttribute: function() { return null; }
    };
  }
  const content = element();
  Object.defineProperty(content, 'innerHTML', {
    get: function() { return rendered; },
    set: function(value) { rendered = value; throw stop; }
  });
  const controls = element();
  const toc = element();
  const tocContent = element();
  const document = {
    documentElement: { style: { setProperty: function() {} }, getAttribute: function() { return 'light'; }, setAttribute: function() {} },
    getElementById: function(id) { return id === 'content' ? content : id === 'viewer-controls' ? controls : id === 'toc-panel' ? toc : tocContent; },
    createElement: element,
    addEventListener: function() {}
  };
  const window = {
    markdownit: require(path.join(scriptsDir, 'vendor', 'markdown-it.min.js')),
    document,
    matchMedia: null,
    localStorage: { getItem: function() { return null; } },
    hljs: { getLanguage: function() { return false; } },
    katex: { renderToString: function(value) { return value; } }
  };
  try {
    new vm.Script(script).runInNewContext({
      window, document, console, Promise, Blob, Uint8Array, URL, Image: function Image() {}, XMLSerializer: function XMLSerializer() {},
      setTimeout: function() {}, clearTimeout: function() {}, getComputedStyle: function() { return { getPropertyValue: function() { return '460px'; } }; }
    });
  } catch (error) {
    if (error !== stop) throw error;
  }
  return rendered;
}

function assertColumnsRuntime(html) {
  const rendered = renderClientMarkdown(html);
  assert.match(rendered, /<div class="columns-layout" style="--column-count:2">/, '横向布局应生成两列容器');
  assert.match(rendered, /<section class="column-layout">/, '横向布局应生成受控列容器');
  return rendered;
}

function getVisualBlockDefinitions(html) {
  const script = Array.from(html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi), function(match) { return match[1]; }).at(-1);
  const stop = {};
  const instrumented = script.replace(
    'container.innerHTML = md.render(raw);',
    'container.innerHTML = md.render(raw); window.__visualBlockDefinitions = { mermaid: mermaidBlocks, markmap: markmapBlocks }; throw window.__visualBlockStop;'
  );
  assert.notStrictEqual(instrumented, script, '测试应能在图表定义完成后提取它们');
  function element() {
    return {
      style: { setProperty: function() {} },
      classList: { add: function() {}, remove: function() {}, toggle: function() { return false; }, contains: function() { return false; } },
      appendChild: function() {}, insertBefore: function() {}, setAttribute: function() {}, removeAttribute: function() {},
      addEventListener: function() {}, remove: function() {}, contains: function() { return false; },
      querySelector: function() { return null; }, querySelectorAll: function() { return []; }, getAttribute: function() { return null; }
    };
  }
  const content = element();
  const controls = element();
  const toc = element();
  const tocContent = element();
  const viewerLayout = element();
  const document = {
    documentElement: { style: { setProperty: function() {} }, getAttribute: function() { return 'light'; }, setAttribute: function() {} },
    getElementById: function(id) {
      if (id === 'content') return content;
      if (id === 'viewer-controls') return controls;
      if (id === 'toc-panel') return toc;
      if (id === 'toc-content') return tocContent;
      if (id === 'viewer-layout') return viewerLayout;
      return null;
    },
    createElement: element,
    addEventListener: function() {}
  };
  const window = {
    markdownit: require(path.join(scriptsDir, 'vendor', 'markdown-it.min.js')),
    document,
    matchMedia: function() { return { matches: false }; },
    localStorage: { getItem: function() { return null; } },
    hljs: { getLanguage: function() { return false; } },
    katex: { renderToString: function(value) { return value; } },
    __visualBlockStop: stop
  };
  try {
    new vm.Script(instrumented).runInNewContext({
      window, document, console, Promise, Blob, Uint8Array, URL, Image: function Image() {}, XMLSerializer: function XMLSerializer() {},
      setTimeout: function() {}, clearTimeout: function() {}, getComputedStyle: function() { return { getPropertyValue: function() { return '460px'; } }; }
    });
  } catch (error) {
    if (error !== stop) throw error;
  }
  return window.__visualBlockDefinitions;
}

try {
  const source = write('fixture.md', `# 标题\n\n## 重复标题\n\n## 重复标题\n\n\`\`\`mermaid\nflowchart LR\n  GraphA --> GraphB\n\`\`\`\n\n\`\`\`echarts\n{"series":[{"type":"bar","data":[1,2]}],"xAxis":{"type":"category","data":["A","B"]},"yAxis":{"type":"value"}}\n\`\`\`\n\n\`\`\`mermaid\nflowchart LR\n  A --> B\n\`\`\`\n\n\`\`\`markmap\n# Root\n## Branch\n\`\`\`\n\n::: columns\n::: column\n左列内容\n\n\`\`\`mermaid\nflowchart LR\n  Left --> Right\n\`\`\`\n\n\`\`\`mermaid\nflowchart LR\n  ColumnA --> ColumnB\n\`\`\`\n\n    保持缩进的代码块\n\n\`\`\`text\n::: 保持为代码\n\`\`\`\n:::\n::: column\n右列内容\n\n\`\`\`echarts\n{"series":[{"type":"line","data":[2,3]}],"xAxis":{"type":"category","data":["A","B"]},"yAxis":{"type":"value"}}\n\`\`\`\n\n\`\`\`markmap\n# Column Root\n## Column Branch\n\`\`\`\n:::\n:::\n\n公式：$E = mc^2$。\n\n$$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$\n\n\`\`\`javascript\nconsole.log('hello');\nconst closingTag = '</script>';\n\`\`\`\n`);
  const output = path.join(tempDir, 'fixture.html');
  const build = run(['--input', source, '--output', output, '--theme', 'dark']);
  assertSuccess(build, '默认构建应成功');
  const html = fs.readFileSync(output, 'utf8');
  assert.match(html, /"toc":true/);
  assert.match(html, /"codeTools":true/);
  assert.match(html, /"codeCollapse":false/);
  assert.match(html, /"chartTools":true/);
  assert.match(html, /"chartExport":true/);
  assert.match(html, /"strict":true/);
  assert.match(html, /"theme":"dark"/);
  assert.match(html, /"contentWidth":80/);
  assert.match(html, /"markmapColors":\{"light":\["#0077b6"/);
  assert.match(html, /static-echarts-0/);
  assert.match(html, /downloadPngFromShell/);
  assert.match(html, /enhanceCodeBlocks/);
  assert.match(html, /buildToc/);
  assert.match(html, /staticSvgForTheme/);
  assert.match(html, /refreshStaticCharts/);
  assert.match(html, /markmapColorsForTheme/);
  assert.match(html, /setStaticZoom/);
  assert.match(html, /setMermaidZoom/);
  assert.match(html, /zoomType: 'mermaid'/);
  assert.match(html, /is-mermaid-zoomed/);
  assert.match(html, /fitVisualSize/);
  assert.match(html, /visualDefaultMaxWidth = settings\.visualWidth/);
  assert.match(html, /visualDefaultMaxHeight = settings\.visualHeight/);
  assert.match(html, /"tocLayout":"right"/);
  assert.match(html, /"tocWidth":20/);
  assert.match(html, /"visualWidth":960/);
  assert.match(html, /"visualHeight":520/);
  assert.match(html, /data-toc-layout/);
  assert.match(html, /toc-is-floating/);
  assert.match(html, /ResizeObserver/);
  assert.match(html, /min-width: 0/);
  assert.match(html, /fitMermaidDiagram/);
  assert.match(html, /prepareVisualsForPrint/);
  assert.match(html, /restoreVisualsAfterPrint/);
  assert.match(html, /columns-layout/);
  assert.match(html, /columns\.length < 2 \|\| columns\.length > 4/);
  assert.match(html, /::: 保持为代码/);
  assert.match(html, /保持缩进的代码块/);
  assert.match(html, /static-echarts-1/);
  assert.match(html, /function printDocument\(\)/);
  assert.match(html, /window\.print\(\)/);
  assert.match(html, /window\.addEventListener\('beforeprint', prepareVisualsForPrint\)/, '打印布局应在 beforeprint 中准备');
  assert.doesNotMatch(html, /prepareVisualsForPrint\(\);[\s\S]{0,160}window\.print\(\)/, '打印按钮不应在屏幕布局下预先计算图表尺寸');
  assert.match(html, /\.columns-layout \{ display: grid !important; grid-template-columns: repeat\(var\(--column-count\), minmax\(0, 1fr\)\) !important;/, '打印分栏应使用不会被图表固有宽度撑开的等宽网格');
  assert.match(html, /\.column-layout \{ width: auto; min-width: 0;/, '打印列应允许图表随列宽缩小');
  assert.match(html, /\.visual-stage-explicit \.diagram svg, \.visual-stage-explicit \.static-svg-image \{[^}]*max-width: 100% !important;[^}]*max-height: 100% !important;[^}]*height: auto !important;/, '打印时显式尺寸图表应在统一视口内等比适配');
  const unsizedMermaidPrintRule = html.match(/\.mermaid-box \.visual-stage:not\(\.visual-stage-explicit\) \.diagram svg \{[^}]*\}/);
  assert(unsizedMermaidPrintRule, '打印样式应覆盖未配置尺寸的 Mermaid');
  assert.match(unsizedMermaidPrintRule[0], /max-width: 100% !important; max-height: none !important; height: auto !important;/, '打印时未配置尺寸的 Mermaid 应保留自然宽度，只在超宽时缩小');
  assert(!/(?:^|[;{]\s*)width\s*:/.test(unsizedMermaidPrintRule[0]), '打印时未配置尺寸的 Mermaid 不应被放大到整页宽');
  const unsizedStaticPrintRule = html.match(/\.static-chart \.visual-stage:not\(\.visual-stage-explicit\) \.static-svg-image \{[^}]*\}/);
  assert(unsizedStaticPrintRule, '打印样式应覆盖未配置尺寸的静态图');
  assert(!/(?:^|[;{]\s*)width\s*:/.test(unsizedStaticPrintRule[0]), '打印时未配置尺寸的 ECharts 不应被放大到整页宽');
  assert.match(html, /function setCodeCollapsed\(/);
  assert.match(html, /var copy = addIconButton\(toolbar, 'copy', '复制代码'/, '代码复制应使用图标按钮');
  assert.match(html, /var toggle = addIconButton\(toolbar, settings\.codeCollapse \? 'expand' : 'collapse'/, '代码展开/收起应使用图标按钮');
  assert.match(html, /button\.setAttribute\('aria-label', label\)/, '图标按钮应保留可访问名称');
  assert.match(html, /setCodeCollapsed\(wrapper, toggle, settings\.codeCollapse\)/, 'codeCollapse 应只控制初始状态');
  assert.match(html, /code-block\.is-collapsed pre/);
  assert.match(html, /print-color-adjust: exact/);
  assert.match(html, /max-height: none !important/);
  assert.match(html, /html\[data-theme="dark"\] \.hljs/);
  assert.match(html, /math-overflow/);
  assert.match(html, /addButton\(actions, '下载 MD', '下载源 Markdown 文档', downloadSourceMarkdown\)/, '页面应提供源 Markdown 下载按钮');
  assert.match(html, /new Blob\(\[sourceMarkdown\], \{ type: 'text\/markdown;charset=utf-8' \}\)/, '源 Markdown 应以 text/markdown 下载');
  assert.match(html, /"fixture\.md"/, '下载文件名应保留 Markdown 输入文件名');
  const embeddedSource = JSON.stringify(fs.readFileSync(source, 'utf8')).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026');
  assert(html.includes(embeddedSource), '下载功能应逐字内嵌原始 Markdown');
  assert.match(html, /closingTag = '\\u003c\/script\\u003e';/, '源 Markdown 中的 script 结束标签必须安全内嵌');
  assert(!html.includes("closingTag = '</script>';"), '源 Markdown 不能以原始 script 结束标签写入 HTML');
  assert.match(html, /tocToggle\.textContent = open \? '收起目录' : '打开目录'/, '关闭状态目录按钮应显示打开目录');
  assert.match(html, /tocToggle = addButton\(actions, '打开目录', '打开目录'/, '目录按钮初始文案应为打开目录');
  assert.match(html, /static-svg-image/);
  assert.match(html, /"static-echarts-0":\{/);
  assert.match(html, /"darkSvg":"\\u003csvg class=\\"static-svg/);
  assert.match(html, /static-svg/);
  assert.match(html, /\\u003csvg class=\\"static-svg/);
  const echartsSvgPair = html.match(/"static-echarts-0":\{[\s\S]*?"svg":"((?:\\.|[^"\\])*)","darkSvg":"((?:\\.|[^"\\])*)","error":""\}/);
  assert(echartsSvgPair, 'ECharts 静态块应同时包含亮色和暗色 SVG');
  assert.notStrictEqual(echartsSvgPair[1], echartsSvgPair[2], 'ECharts 的亮暗主题 SVG 应不同');
  assert(!html.includes('runSearch'), '生成页面不应包含自定义页内搜索逻辑');
  assert(!html.includes('search-control'), '生成页面不应包含自定义搜索控件样式');
  assert(!html.includes('MARKMAP_THEMES'), '生成页面不应包含 Markmap 多配色主题');
  assert(!html.includes('渲染校验通过'), '正常渲染不应显示校验通过状态');
  assert(!html.includes('图表校验中'), '正常渲染不应显示校验中状态');
  assert(!html.includes('globalThis.Viz='), '生成页面不应包含浏览器端 Viz 运行时');
  assert(!html.includes('echarts.init(chartDiv'), '生成页面不应包含浏览器端 ECharts 初始化');
  assert(!/<(?:script|link|img|iframe|object|embed|source|video|audio)\b[^>]*(?:src|href)\s*=\s*["'](?:https?:)?\/\//i.test(html), '生成页面不应引用外部资源');
  const scripts = Array.from(html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi), function(match) { return match[1]; });
  scripts.forEach(function(script, index) { new vm.Script(script, { filename: `generated-${index}.js` }); });
  const renderedColumns = assertColumnsRuntime(html);
  assert.match(renderedColumns, /id="static-echarts-1"/, '列内 ECharts 应注册为静态图表');
  assert.match(renderedColumns, /id="mermaid-2"/, '列内依赖图应注册为 Mermaid 动态图表');
  assert.match(renderedColumns, /id="mermaid-3"/, '列内流程图应注册为 Mermaid 动态图表');
  assert.match(renderedColumns, /id="markmap-1"/, '列内 Markmap 应注册为动态图表');
  assert.match(renderedColumns, /<pre><code>保持缩进的代码块/, '列内 Markdown 缩进必须保留');
  assert.match(html, /stage\.classList\.add\('visual-stage-explicit'\)/, '显式尺寸图表应使用统一等比视口');
  assert.match(html, /stage\.style\.aspectRatio = shell\.dimensions\.width \+ ' \/ ' \+ shell\.dimensions\.height/, '显式尺寸图表应保持声明比例');
  assert.match(html, /\.visual-stage-explicit \{[^}]*display: grid;[^}]*grid-template-columns: minmax\(0, 1fr\);[^}]*grid-template-rows: minmax\(0, 1fr\);[^}]*padding: 0 !important;/, '显式尺寸视口应固定比例且不被图表固有尺寸撑开');
  assert.match(html, /\.visual-stage-explicit > \.visual-canvas \{[^}]*grid-area: 1 \/ 1;[^}]*min-width: 0;[^}]*min-height: 0;/, '图表画布应在正常流的固定比例视口内完整显示');
  assert.doesNotMatch(html, /\.visual-stage-explicit > \.diagram[^}]*position: absolute;/, '显式尺寸图表不应以绝对定位覆盖工具栏');
  assert.match(html, /var fitted = fitVisualSize\(shell\.stage, naturalWidth, naturalHeight, shell\);\s*shell\.staticBaseWidth = fitted\.width;/, 'ECharts 应以自然尺寸适配后的宽度作为 100%');
  assert.match(html, /var fitted = fitVisualSize\(shell\.stage, size\.width, size\.height, shell\);\s*svg\.style\.display = 'block';\s*shell\.mermaidBaseWidth = fitted\.width;/, 'Mermaid 应以自然尺寸适配后的宽度作为 100%');
  assert.match(html, /var contentScale = Math\.min\(1, limits\.width \/ safeWidth, limits\.height \/ safeHeight\);\s*var viewportScale = Math\.min\(1, availableWidth \/ limits\.width, availableHeight \/ limits\.height\);\s*scale = contentScale \* viewportScale;/, '显式尺寸图表内容应随视口一起等比例缩小但不自动放大');
  assert.match(html, /else if \(printing\) \{\s*scale = Math\.min\(1, availableWidth \/ safeWidth\);/, '打印未配置尺寸图表时应只按页面宽度缩小，不受屏幕高度上限影响');
  assert.doesNotMatch(html, /shell\.staticBaseWidth = shell\.stage\.clientWidth \|\| shell\.dimensions\.width/, '显式尺寸静态图不能自动铺满视口');
  assert.doesNotMatch(html, /shell\.mermaidBaseWidth = shell\.stage\.clientWidth \|\| shell\.dimensions\.width/, '显式尺寸 Mermaid 不能自动铺满视口');
  assert.match(html, /function normalizeVisualZoom\(zoom\)[\s\S]*?Math\.max\(0\.01, Math\.min\(10,/, '图表缩放范围应为 1% 到 1000%');
  assert.match(html, /addButton\(group, '-', '缩小图表'/, '图表缩小控件应使用减号');
  assert.match(html, /input\.min = '1';\s*input\.max = '1000';\s*input\.step = '1';\s*input\.value = '100';/, '图表缩放应显示可输入的百分比数字');
  assert.match(html, /\.visual-zoom-input \{[^}]*width: 2\.75rem;[^}]*text-align: center;/, '缩放输入框应保持紧凑并居中显示百分比');
  assert.match(html, /addButton\(group, '\+', '放大图表'/, '图表放大控件应使用加号');
  assert.match(html, /if \(shell\.zoomType === 'markmap'\) setMarkmapZoom\(shell, zoom\)/, 'Markmap 应使用统一缩放控件');
  assert.match(html, /map\.rescale\(next \/ previous\)/, 'Markmap 缩放应改变内容比例而不是视口高度');
  assert.match(html, /map\.zoom\.on\('zoom\.aidocs',[\s\S]*?shell\.markmapZoom = normalizeVisualZoom\(transform\.k \/ shell\.markmapBaseScale\)/, 'Markmap 原生缩放应同步百分比控件');
  assert.match(html, /map\.zoom\.scaleExtent\(\[shell\.markmapBaseScale \* 0\.01, shell\.markmapBaseScale \* 10\]\)/, 'Markmap 原生缩放的真实范围应限制为 1% 到 1000%');
  assert.match(html, /function markmapFitScale\(shell, map\)[\s\S]*?var contentScale = Math\.min\(1,[\s\S]*?var viewportScale = Math\.min\(1,[\s\S]*?return Math\.max\(0\.0001, contentScale \* viewportScale\)/, '显式尺寸 Markmap 应随声明视口缩小且不自动放大');
  assert.match(html, /map\.fit\(markmapFitScale\(shell, map\)\)/, 'Markmap 应使用统一的视口适配上限');
  assert.doesNotMatch(html, /shell\.dimensions\.height = next/, '图表缩放不应改变声明的视口比例');
  assert.match(html, /clone\.style\.removeProperty\(property\)/, 'Mermaid 导出应移除仅用于屏幕缩放的根 SVG 样式');
  assert.match(html, /'flex-shrink'/, 'Mermaid 导出应移除仅用于高倍率显示的 flex 样式');
  assert.match(html, /if \(shell && shell\.zoomType === 'markmap' && shell\.element\._markmap\)[\s\S]*?clone\.setAttribute\('viewBox',[\s\S]*?group\.removeAttribute\('transform'\)/, 'Markmap 导出应使用完整内容边界并清除屏幕平移缩放');
  assert.match(html, /return \{ markup: serializeSvg\(svg, shell\), svg: null \};/, '动态图表 PNG 应按清理后的 SVG 尺寸导出');
  assert.match(html, /var viewportWidth = Math\.max\(1, Math\.round\(Math\.min\(shell\.viewportBaseWidth \* next, pageWidth\)\)\);\s*var viewportHeight = Math\.max\(1, Math\.round\(Math\.min\(shell\.viewportBaseHeight \* next, pageHeight\)\)\);/, '图表框宽高应分别增长到各自页面上限，避免高度提前限制最大宽度');
  assert.match(html, /var parentPadding = \(Number\.parseFloat\(parentStyle\.paddingLeft\) \|\| 0\) \+ \(Number\.parseFloat\(parentStyle\.paddingRight\) \|\| 0\);\s*parentWidth = Math\.max\(1, parent\.clientWidth - parentPadding\);/, '图表最大宽度应使用父容器内容区，不包含分栏内边距');
  assert.match(html, /shell\.element\.style\.width = viewportWidth \+ 'px';\s*shell\.stage\.style\.setProperty\('height', viewportHeight \+ 'px', 'important'\)/, '缩放应同步扩大图表框的宽高');
  assert.match(html, /function centerVisualViewport\(shell\)[\s\S]*?shell\.stage\.scrollLeft = Math\.max\(0, \(shell\.stage\.scrollWidth - shell\.stage\.clientWidth\) \/ 2\)/, '达到页面上限后图表应在框内居中滚动');
  assert.match(html, /function centerVisualViewport\(shell\)[\s\S]*?shell\.stage\.scrollTop = Math\.max\(0, \(shell\.stage\.scrollHeight - shell\.stage\.clientHeight\) \/ 2\)/, '缩放后的图表应滚动到垂直中心');
  assert.match(html, /if \(document\.documentElement\.getAttribute\('data-printing'\) !== 'true'\) \{\s*centerVisualViewport\(shell\);\s*window\.requestAnimationFrame\(function\(\) \{[\s\S]*?centerVisualViewport\(shell\);/, '屏幕图表应同步居中并在下一帧再次校正');
  assert.match(html, /if \(document\.documentElement\.getAttribute\('data-printing'\) !== 'true'\) centerVisualViewport\(shell\);/, '打印状态下不应由延迟的屏幕居中再次改变滚动位置');
  assert.match(html, /function prepareVisualViewportForPrint\(shell\)[\s\S]*?shell\.stage\.scrollLeft = 0;\s*shell\.stage\.scrollTop = 0;/, '打印前应归零图表滚动位置，避免与打印定位叠加偏移');
  assert.match(html, /function restoreVisualViewportAfterPrint\(shell\)[\s\S]*?shell\.stage\.scrollLeft = saved\.left;\s*shell\.stage\.scrollTop = saved\.top;/, '打印后应恢复屏幕中的图表滚动位置');
  assert.match(html, /diagram\.className = 'diagram mermaid visual-canvas';/, 'Mermaid 应使用可居中的滚动画布');
  assert.doesNotMatch(html, /\.mermaid-box\.is-mermaid-zoomed \.diagram \{[^}]*justify-content: flex-start;/, '放大的 Mermaid 不应切换为左对齐');
  assert.match(html, /svg\.style\.flexShrink = next > 1 \? '0' : '';/, '放大的 Mermaid 不应被 flex 布局压回容器宽度');
  assert.match(html, /canvas\.className = 'visual-canvas';[\s\S]*?canvas\.appendChild\(image\);/, '静态图应使用可居中的滚动画布');
  assert.match(html, /\.visual-box\.is-visual-contained \.visual-stage \{ overflow: auto; \}/, '只有图表内容超过最大框时才应在框内滚动');
  assert.match(html, /\.mermaid-box \.visual-stage:not\(\.visual-stage-explicit\), \.static-chart \.visual-stage:not\(\.visual-stage-explicit\) \{ overflow: hidden !important; \}/, '打印时未声明尺寸的图表也应限制在最大视口内');
  assert.match(html, /\.visual-box\.is-visual-zoomed \.visual-stage-explicit \{ place-items: start; overflow: auto; \}/, '显式尺寸图表放大后应由视口统一滚动');
  assert.doesNotMatch(html, /\.static-chart\.is-static-zoomed \.static-svg-image \{[^}]*margin: 0;/, '放大的静态图不应切换为左对齐');
  assert.match(html, /element\._printZoom = shell\.staticZoom;[\s\S]*?setStaticZoom\(shell, element\._printZoom\)/, '打印静态图时应保留当前缩放比例');
  assert.match(html, /element\._printZoom = shell\.mermaidZoom;[\s\S]*?setMermaidZoom\(shell, element\._printZoom\)/, '打印 Mermaid 时应保留当前缩放比例');
  assert.match(html, /var printZoom = element\._markmapShell \? normalizeVisualZoom\(element\._markmapShell\.markmapZoom\) : 1;[\s\S]*?Math\.round\(printZoom \* 100\) \+ '%'/, '打印 Markmap 时应保留当前缩放比例');
  assert.match(html, /\.visual-box \{ width: 100% !important; max-width: 100% !important; overflow: visible; margin: 1\.2em 0 !important; \}/, '打印图表外框应占满所在页面或分栏的内容宽度');
  assert.match(html, /\.visual-stage \{ position: relative !important; display: grid !important; grid-template-columns: minmax\(0, 1fr\) !important; grid-template-rows: minmax\(0, 1fr\) !important; align-items: unsafe center !important; justify-items: center !important; overflow: hidden !important; \}/, '打印图表视口应使用固定网格从中心裁剪内容');
  assert.match(html, /\.visual-stage > \.visual-canvas, \.markmap-box \.visual-stage > svg \{ position: static !important; grid-area: 1 \/ 1 !important; align-self: unsafe center !important; justify-self: center !important; margin: 0 auto !important; max-width: 100% !important; min-width: 0 !important; transform: none !important; \}/, '打印图表内容应强制从中心溢出且不使用位移补偿');
  assert.doesNotMatch(html, /@media print \{[\s\S]*?\.visual-stage > \.visual-canvas[^}]*translate\(/, '打印居中不应使用 translate 位移');
  assert.match(html, /\.mermaid-box\.is-mermaid-zoomed \.visual-stage \.diagram svg, \.static-chart\.is-static-zoomed \.visual-stage \.static-svg-image \{ max-width: none !important; max-height: none !important; \}/, '打印时不应把放大的 Mermaid 和静态图压回页面宽度');
  assert.match(html, /element\._printBaseWidth = shell\.staticBaseWidth;/, '打印前应保存静态图的屏幕基准宽度');
  assert.match(html, /shell\.staticBaseWidth = element\._printBaseWidth;[\s\S]*?setStaticZoom\(shell, element\._printZoom\)/, '打印后应恢复静态图的屏幕尺寸与缩放');
  assert.match(html, /element\._printBaseWidth = shell\.mermaidBaseWidth;/, '打印前应保存 Mermaid 的屏幕基准宽度');
  assert.match(html, /shell\.mermaidBaseWidth = element\._printBaseWidth;[\s\S]*?setMermaidZoom\(shell, element\._printZoom\)/, '打印后应恢复 Mermaid 的屏幕尺寸与缩放');
  assert.match(html, /window\.requestAnimationFrame\(function\(\) \{\s*resizeStaticCharts\(\);\s*resizeMermaids\(\);/, '打印结束后应按屏幕容器重新测量图表');
  assert.match(html, /var previousZoom = visualZoomState\[block\.id\] \|\| \(element\._mermaidShell \? element\._mermaidShell\.mermaidZoom : 1\)/, '主题切换重绘 Mermaid 时应从独立状态继承缩放比例');
  assert.match(html, /var previousZoom = visualZoomState\[block\.id\] \|\| \(element\._markmapShell \? element\._markmapShell\.markmapZoom : 1\)/, '主题切换重绘 Markmap 时应从独立状态继承缩放比例');
  assert.match(html, /\.column-layout \.visual-box \{[^}]*min-width: 0;[^}]*max-width: 100%;/, '分栏图表不得以固有宽度撑开列');
  assert.match(html, /\.column-layout \.visual-toolbar \{ display: grid;/, '分栏图表工具栏应使用稳定的两行布局');
  assert.match(html, /\.column-layout \.visual-actions \{[^}]*overflow-x: auto;/, '分栏操作按钮受挤压时应横向滚动而不改变图表对齐');
  assert.match(html, /@media screen and \(max-width: 760px\)/, '移动端单列规则不得覆盖打印分栏');
  assert.match(html, /img \{[^}]*display: block;[^}]*width: auto;[^}]*margin: 1\.2em auto;/, '普通图片应按自然宽度居中显示');
  assert.match(html, /table \{[^}]*width: max-content;[^}]*max-width: 100%;[^}]*margin: 1\.4em auto;/, '表格应按内容宽度居中并保留窄屏滚动');

  const config = write('config.json', JSON.stringify({
    toc: false,
    chartTools: false,
    codeCollapse: true,
    theme: 'light',
    contentWidth: '65%',
    tocLayout: 'left',
    tocWidth: 25,
    visualWidth: 720,
    visualHeight: 400,
    markmapColors: { light: ['#123456', '#abcdef'], dark: ['#654321', '#fedcba'] }
  }));
  const configuredOutput = path.join(tempDir, 'configured.html');
  const configured = run(['--input', source, '--output', configuredOutput, '--config', config]);
  assertSuccess(configured, '配置文件构建应成功');
  const configuredHtml = fs.readFileSync(configuredOutput, 'utf8');
  assert.match(configuredHtml, /"toc":false/);
  assert.match(configuredHtml, /"chartTools":false/);
  assert.match(configuredHtml, /"codeCollapse":true/);
  assert.match(configuredHtml, /"theme":"light"/);
  assert.match(configuredHtml, /"contentWidth":65/);
  assert.match(configuredHtml, /"tocLayout":"left"/);
  assert.match(configuredHtml, /"tocWidth":25/);
  assert.match(configuredHtml, /"visualWidth":720/);
  assert.match(configuredHtml, /"visualHeight":400/);
  assert.match(configuredHtml, /"markmapColors":\{"light":\["#123456","#abcdef"\],"dark":\["#654321","#fedcba"\]\}/);
  assert.match(configuredHtml, /if \(!settings\.toc\) return self\.renderToken/);
  assert.match(configuredHtml, /var hasToolbar = settings\.chartTools;/);
  assert.match(configuredHtml, /codeCollapse: viewerOptions\.codeCollapse === true/);
  const expandedCodeOutput = path.join(tempDir, 'expanded-code.html');
  assertSuccess(run(['--input', source, '--output', expandedCodeOutput, '--config', config, '--no-code-collapse']), 'CLI 应能覆盖代码块收起配置');
  assert.match(fs.readFileSync(expandedCodeOutput, 'utf8'), /"codeCollapse":false/);
  assertFailure(run(['--input', source, '--output', path.join(tempDir, 'obsolete-search.html'), '--no-search']), /未知选项/, '已移除自定义页内搜索开关');
  assertFailure(run(['--input', source, '--output', path.join(tempDir, 'narrow.html'), '--content-width', '49']), /contentWidth 必须在 50 到 100 之间/, '正文宽度不得小于 50%');
  assertFailure(run(['--input', source, '--output', path.join(tempDir, 'wide.html'), '--content-width=101%']), /contentWidth 必须在 50 到 100 之间/, '正文宽度不得大于 100%');
  assertFailure(run(['--input', source, '--output', path.join(tempDir, 'bad-toc-layout.html'), '--toc-layout', 'bottom']), /tocLayout 必须是 left、right 或 float/, '目录布局必须受限');
  assertFailure(run(['--input', source, '--output', path.join(tempDir, 'bad-toc-width.html'), '--toc-width', '9']), /tocWidth 必须在 10 到 40 之间/, '目录宽度必须受限');
  assertFailure(run(['--input', source, '--output', path.join(tempDir, 'bad-visual-width.html'), '--visual-width', '239']), /visualWidth 必须在 240 到 2400 之间/, '图表宽度必须受限');
  assertFailure(run(['--input', source, '--output', path.join(tempDir, 'bad-visual-height.html'), '--visual-height', '159']), /visualHeight 必须在 160 到 1600 之间/, '图表高度必须受限');

  const sizedVisuals = write('sized-visuals.md', '# Sizes\n\n```mermaid size=640x360\nflowchart LR\n  A --> B\n```\n\n```markmap size=720x420\n# Root\n## Branch\n```\n\n```echarts size=800x400\n{"series":[{"type":"bar","data":[1,2]}],"xAxis":{"type":"category","data":["A","B"]},"yAxis":{"type":"value"}}\n```\n');
  const sizedVisualsOutput = path.join(tempDir, 'sized-visuals.html');
  assertSuccess(run(['--input', sizedVisuals, '--output', sizedVisualsOutput]), '单图尺寸应成功构建');
  const sizedVisualsHtml = fs.readFileSync(sizedVisualsOutput, 'utf8');
  const visualDefinitions = getVisualBlockDefinitions(sizedVisualsHtml);
  assert.strictEqual(JSON.stringify(visualDefinitions.mermaid[0].dimensions), JSON.stringify({ width: 640, height: 360 }), 'Mermaid 应保留单图尺寸');
  assert.strictEqual(JSON.stringify(visualDefinitions.markmap[0].dimensions), JSON.stringify({ width: 720, height: 420 }), 'Markmap 应保留单图尺寸');
  assert.match(sizedVisualsHtml, /"dimensions":\{"width":800,"height":400\}[\s\S]*?"svg":"/, '静态图应保留单图尺寸');
  const invalidVisualSize = write('invalid-visual-size.md', '```mermaid size=bad\nflowchart LR\n  A --> B\n```\n');
  const invalidVisualSizeOutput = path.join(tempDir, 'invalid-visual-size.html');
  const invalidSizeBuild = run(['--input', invalidVisualSize, '--output', invalidVisualSizeOutput]);
  assertSuccess(invalidSizeBuild, '非法尺寸标记应降级为代码块而不是让构建失败');
  assert.match(invalidSizeBuild.stderr, /图表代码块只支持 size=<宽>x<高> 参数/, '非法尺寸必须给出明确警告');
  assert.match(renderClientMarkdown(fs.readFileSync(invalidVisualSizeOutput, 'utf8')), /data-visual-error="invalid-visual-size\.md:1: 图表代码块只支持/, '非法尺寸 fence 应带降级属性');

  const sampleMarkdown = fs.readFileSync(path.join(toolDir, 'assets', 'full-example.md'), 'utf8');
  const columnsSample = sampleMarkdown.match(/## 10\. 分栏内图表\n\n([\s\S]*?)\n## 11\./);
  assert(columnsSample, '示例应保留分栏图表章节');
  const columnSizes = Array.from(columnsSample[1].matchAll(/^```(?:mermaid|echarts|markmap) size=(\d+x\d+)$/gm), function(match) { return match[1]; });
  assert.deepStrictEqual(columnSizes, ['640x360', '640x360', '640x360', '640x360'], '分栏示例的左右两行图表尺寸应一致');
  const dependencySample = sampleMarkdown.match(/## 7\. Mermaid 依赖图\n\n```mermaid\n([\s\S]*?)\n```/);
  assert(dependencySample, '示例应使用 Mermaid 表达依赖图');
  assert.match(dependencySample[1], /flowchart TB/);

  const invalidColumns = write('invalid-columns.md', '::: columns\n::: column\n只有一列\n:::\n:::\n');
  const invalidColumnsOutput = path.join(tempDir, 'invalid-columns.html');
  assertSuccess(run(['--input', invalidColumns, '--output', invalidColumnsOutput]), '无效横向布局应作为普通 Markdown 输出');
  assert.match(fs.readFileSync(invalidColumnsOutput, 'utf8'), /只有一列/, '无效横向布局源码应保留给普通 Markdown 渲染');

  const unsupportedDot = write('unsupported-dot.md', '# Graph\n\n```dot\ndigraph G { A -> B }\n```\n');
  const unsupportedDotOutput = path.join(tempDir, 'unsupported-dot.html');
  const dotBuild = run(['--input', unsupportedDot, '--output', unsupportedDotOutput]);
  assertSuccess(dotBuild, 'dot fence 应降级为代码块而不是让构建失败');
  assert.match(dotBuild.stderr, /unsupported-dot\.md:3: 不支持 dot\/graphviz 图表代码块；AI Docs 不再内置 Graphviz[\s\S]*（已降级为代码块展示）/, 'dot 降级必须打印明确警告');
  const unsupportedDotHtml = fs.readFileSync(unsupportedDotOutput, 'utf8');
  assert.match(unsupportedDotHtml, /"3":\{"language":"dot","message":"unsupported-dot\.md:3: 不支持 dot\/graphviz 图表代码块/, '输出应内嵌降级原因供悬浮提示使用');
  assert.match(unsupportedDotHtml, /code-chart-badge/, '输出应包含表头警示标识逻辑');
  const dotRendered = renderClientMarkdown(unsupportedDotHtml);
  assert.match(dotRendered, /<code data-visual-error="unsupported-dot\.md:3: 不支持 dot\/graphviz 图表代码块[^"]*"/, '客户端渲染应把 dot fence 输出为带错误属性的代码块');
  assert.doesNotMatch(dotRendered, /<div class="visual-box/, 'dot fence 不应生成图表容器');

  assertSuccess(run(['--input', unsupportedDot, '--output', path.join(tempDir, 'unsupported-dot-loose.html'), '--no-strict']), 'dot 降级与 --no-strict 无关');
  const unsupportedGraphviz = write('unsupported-graphviz.md', '```graphviz\ndigraph G { A -> B }\n```\n');
  const graphvizOutput = path.join(tempDir, 'unsupported-graphviz.html');
  const graphvizBuild = run(['--input', unsupportedGraphviz, '--output', graphvizOutput]);
  assertSuccess(graphvizBuild, 'graphviz fence 别名同样降级为代码块');
  assert.match(graphvizBuild.stderr, /unsupported-graphviz\.md:1: 不支持 dot\/graphviz 图表代码块/, 'graphviz 降级必须打印明确警告');
  assert.match(renderClientMarkdown(fs.readFileSync(graphvizOutput, 'utf8')), /data-visual-error="unsupported-graphviz\.md:1:/, 'graphviz fence 应带降级属性');

  const invalidChart = write('invalid-chart.md', '# Error\n\n```echarts\n{invalid}\n```\n');
  assertFailure(run(['--input', invalidChart, '--output', path.join(tempDir, 'strict.html')]), /图表渲染校验失败/, '严格模式必须拒绝无效图表');
  const looseOutput = path.join(tempDir, 'loose.html');
  assertSuccess(run(['--input', invalidChart, '--output', looseOutput, '--no-strict']), '非严格模式应输出错误页');
  assert.match(fs.readFileSync(looseOutput, 'utf8'), /渲染校验失败/);

  const unsafeMarkmap = write('unsafe-markmap.md', '# Error\n\n```markmap\n# Root\n<img src=x onerror=alert(1)>\n```\n');
  const unsafeOutput = path.join(tempDir, 'unsafe.html');
  const unsafeBuild = run(['--input', unsafeMarkmap, '--output', unsafeOutput]);
  assertSuccess(unsafeBuild, '含原始 HTML 的 Markmap 应降级为代码块而不是让构建失败');
  assert.match(unsafeBuild.stderr, /unsafe-markmap\.md:3: Markmap 源码不能包含原始 HTML/, 'Markmap 降级必须给出明确警告');
  const unsafeRendered = renderClientMarkdown(fs.readFileSync(unsafeOutput, 'utf8'));
  assert.match(unsafeRendered, /data-visual-error="unsafe-markmap\.md:3: Markmap 源码不能包含原始 HTML/, 'Markmap 应带降级属性');
  assert.doesNotMatch(unsafeRendered, /markmap-box/, '不安全 Markmap 不应生成思维导图容器');

  // 带引号属性值可合法包含 < >，曾绕过属性段不允许尖括号的正则校验。
  const bypassMarkmap = write('bypass-markmap.md', '# Error\n\n```markmap\n# Root <img data-x="<" src=x onerror="pwned">\n```\n');
  const bypassOutput = path.join(tempDir, 'bypass.html');
  const bypassBuild = run(['--input', bypassMarkmap, '--output', bypassOutput]);
  assertSuccess(bypassBuild, '带引号属性值中的尖括号同样只降级不失败');
  assert.match(bypassBuild.stderr, /bypass-markmap\.md:3: Markmap 源码不能包含原始 HTML/, '绕过写法必须给出明确警告');
  assert.match(renderClientMarkdown(fs.readFileSync(bypassOutput, 'utf8')), /data-visual-error="bypass-markmap\.md:3: Markmap 源码不能包含原始 HTML/, '绕过写法应带降级属性');

  // 合法 autolink 与含 < 的普通文本不是原始 HTML，不得误伤。
  const autolinkMarkmap = write('autolink-markmap.md', '# OK\n\n```markmap\n# Root <https://example.com>\n## a < b\n```\n');
  assertSuccess(run(['--input', autolinkMarkmap, '--output', path.join(tempDir, 'autolink.html')]), 'Markmap autolink 与普通小于号应正常构建');

  // 输出为输入文件的硬链接时必须拒绝，且源文件内容保持完整。
  const hardlinkSource = write('hardlink-source.md', '# 硬链接源\n');
  const hardlinkOutput = path.join(tempDir, 'hardlink-output.html');
  fs.linkSync(hardlinkSource, hardlinkOutput);
  assertFailure(run(['--input', hardlinkSource, '--output', hardlinkOutput]), /不能是硬链接|不能覆盖输入文件/, '输出为输入硬链接时必须拒绝');
  assert.strictEqual(fs.readFileSync(hardlinkSource, 'utf8'), '# 硬链接源\n', '拒绝后源文件内容必须保持完整');
  // 输出为其他文件的硬链接时同样拒绝，避免截断无辜文件。
  const bystander = write('bystander.md', '# 无关文件\n');
  const bystanderLink = path.join(tempDir, 'bystander-link.html');
  fs.linkSync(bystander, bystanderLink);
  assertFailure(run(['--input', hardlinkSource, '--output', bystanderLink]), /不能是硬链接/, '输出为其他文件硬链接时必须拒绝');
  assert.strictEqual(fs.readFileSync(bystander, 'utf8'), '# 无关文件\n', '无关硬链接文件内容必须保持完整');

  assertFailure(run(['--input', source, '--output', source]), /输出文件不能覆盖输入文件/, '输出文件不能覆盖输入文件');

  const symlink = path.join(tempDir, 'source-link.html');
  fs.symlinkSync(source, symlink);
  if (fs.lstatSync(symlink).isSymbolicLink()) {
    assertFailure(run(['--input', source, '--output', symlink]), /输出文件不能覆盖输入文件/, '输出软链接不能覆盖输入文件');
  } else {
    console.warn('skip: 当前环境无法创建真实软链接（Windows 无开发者模式/权限时会降级为复制），跳过软链接覆盖断言');
  }

  console.log('ai-docs build tests passed');
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}
