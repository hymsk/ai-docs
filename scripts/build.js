#!/usr/bin/env node
/**
 * build.js - 将 Markdown 转换为单文件或本地多文件 HTML
 *
 * 默认启用目录、主题控制、代码工具栏、图表源码切换、SVG/PNG 导出和打印优化。
 * 默认按需内联依赖；多文件模式把依赖写入可配置的本地静态目录。
 */

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const crypto = require('crypto');

const DEFAULT_MARKMAP_COLORS = Object.freeze({
  light: Object.freeze(['#0077b6', '#00b4d8', '#48cae4', '#90e0ef', '#023e8a', '#0096c7']),
  dark: Object.freeze(['#a78bfa', '#8b5cf6', '#c4b5fd', '#ddd6fe', '#6d28d9', '#7e22ce'])
});

const DEFAULT_OPTIONS = Object.freeze({
  toc: true,
  codeTools: true,
  codeCollapse: false,
  chartTools: true,
  sourceToggle: true,
  chartExport: true,
  chartMaximize: true,
  print: true,
  themeControl: true,
  theme: 'auto',
  contentWidth: 80,
  tocLayout: 'right',
  tocWidth: 20,
  visualWidth: 960,
  visualHeight: 520,
  markmapColors: DEFAULT_MARKMAP_COLORS,
  strict: true,
  mermaidSecurity: 'strict'
});

const DEFAULT_OUTPUT_OPTIONS = Object.freeze({
  mode: 'single',
  directory: '',
  fileName: ''
});

const DEFAULT_RESOURCE_OPTIONS = Object.freeze({
  directory: 'static',
  publicPath: ''
});

const RESOURCE_ORDER = Object.freeze([
  'markdownIt', 'highlightCss', 'katexCss', 'highlightJs', 'mermaid', 'd3', 'katexJs',
  'markmapLib', 'markmapView'
]);

const BOOLEAN_OPTION_NAMES = new Set([
  'toc', 'codeTools', 'codeCollapse', 'chartTools', 'sourceToggle', 'chartExport', 'chartMaximize',
  'print', 'themeControl', 'strict'
]);

function printUsage() {
  console.log(`用法:
  node build.js --input <input.md> [--output <output.html>] [选项]
  node build.js <input.md> [output.html] [选项]

默认生成按需内联依赖的单文件 HTML。CLI 选项优先于 --config 配置文件。

输入输出:
  -i, --input <file>              输入 Markdown 文件
  -o, --output <file>             输出 HTML 文件
      --preview                   启动带编辑器的实时预览网页（不写入 HTML 成品）
      --output-mode <single|multi>
                                  单文件或本地多文件输出（默认 single）
      --output-dir <directory>    输出目录；未指定时使用输入文件目录
      --output-name <file>        输出文件名；未指定时使用输入文件同名 HTML
      --title <text>              覆盖页面标题
      --config <file>             读取 JSON 配置文件

本地资源（multi 模式）:
      --static-dir <directory>    依赖写入目录，相对于输出 HTML（默认 static）
      --public-path <url-path>    HTML 中的资源 URL 前缀（默认由 static-dir 推导）

页面功能:
      --toc / --no-toc            启用/关闭目录和标题锚点（默认启用）
      --code-tools / --no-code-tools
                                  启用/关闭代码语言和复制工具栏（默认启用）
      --code-collapse / --no-code-collapse
                                  代码块初始收起/展开（默认展开）
      --chart-tools / --no-chart-tools
                                  启用/关闭图表工具栏、导出和源码切换（默认启用）
      --source-toggle / --no-source-toggle
                                  启用/关闭图表预览与源码切换（默认启用）
      --chart-export / --no-chart-export
                                  启用/关闭 SVG 和 PNG 图表导出（默认启用）
      --print / --no-print        启用/关闭打印按钮和打印优化（默认启用）
      --theme-control / --no-theme-control
                                  启用/关闭页面主题控制器（默认启用）
      --theme <auto|light|dark>   初始主题（默认 auto）
      --content-width <50-100>    正文宽度百分比（默认 80）
      --toc-layout <left|right|float>
                                  目录布局（默认 right）
      --toc-width <10-40>         停靠目录宽度百分比（默认 20）
      --visual-width <240-2400>   图表容器最大宽度，单位 px（默认 960）
      --visual-height <160-1600>  图表容器最大高度，单位 px（默认 520）

渲染校验:
      --strict / --no-strict      ECharts 预渲染失败时退出/保留错误页（默认 strict）
      --mermaid-security <strict|loose>
                                  Mermaid 安全级别（默认 strict）
  -h, --help                      显示本帮助

配置文件示例:
  {
    "output": {
      "mode": "multi",
      "directory": "./dist/docs",
      "fileName": "index.html"
    },
    "resources": {
      "directory": "static",
      "publicPath": "/docs/static/"
    },
    "theme": "dark",
    "toc": true,
    "contentWidth": 80,
    "tocLayout": "right",
    "tocWidth": 20,
    "visualWidth": 960,
    "visualHeight": 520,
    "codeCollapse": false,
    "markmapColors": {
      "light": ["#0077b6", "#00b4d8"],
      "dark": ["#a78bfa", "#8b5cf6"]
    },
    "chartExport": false,
    "strict": true,
    "mermaidSecurity": "strict",
    "server": {
      "host": "127.0.0.1",
      "port": 8000,
      "directory": "./dist/docs",
      "open": false
    }
  }`);
}

function writeFileAtomically(target, content) {
  // 同目录临时文件 + rename 原子替换：进程中断不留下截断产物，
  // 也不直接截断既有 inode（硬链接目标在调用前已被拒绝）。
  const temporary = path.join(
    path.dirname(target),
    `.${path.basename(target)}.${process.pid}.${Date.now()}.tmp`
  );
  try {
    fs.writeFileSync(temporary, content, 'utf-8');
    fs.renameSync(temporary, target);
  } catch (error) {
    try { fs.unlinkSync(temporary); } catch (cleanupError) { /* best effort */ }
    throw error;
  }
}

function fail(message) {
  throw new Error(message);
}

function runPreviewIfRequested(argv) {
  const previewIndex = argv.indexOf('--preview');
  if (previewIndex === -1) return false;
  if (argv.indexOf('--preview', previewIndex + 1) !== -1) fail('--preview 只能指定一次。');
  const previewScript = path.join(__dirname, 'preview.js');
  const previewArgs = argv.slice(0, previewIndex).concat(argv.slice(previewIndex + 1));
  const child = childProcess.spawn(process.execPath, [previewScript].concat(previewArgs), { stdio: 'inherit' });
  let forwardedSignal = false;
  function forwardSignal(signal) {
    forwardedSignal = true;
    child.kill(signal);
  }
  process.once('SIGINT', function() { forwardSignal('SIGINT'); });
  process.once('SIGTERM', function() { forwardSignal('SIGTERM'); });
  child.once('error', function(error) {
    console.error(`预览启动失败: ${error.message || error}`);
    process.exit(1);
  });
  child.once('exit', function(code, signal) {
    if (signal && !forwardedSignal) {
      console.error(`预览进程意外停止: ${signal}`);
      process.exit(1);
    }
    process.exit(typeof code === 'number' ? code : 0);
  });
  return true;
}

if (!runPreviewIfRequested(process.argv.slice(2))) {
  function getOptionValue(argv, index, flag) {
  if (index + 1 >= argv.length || argv[index + 1].startsWith('-')) {
    fail(`${flag} 需要一个值。`);
  }
  return argv[index + 1];
}

function parseRawArguments(argv) {
  const raw = {
    settings: {}, positionals: [], input: '', output: '', title: '', configPath: '',
    outputMode: '', outputDir: '', outputName: '', staticDir: '', publicPath: ''
  };
  const booleanFlags = {
    '--toc': ['toc', true], '--no-toc': ['toc', false],
    '--code-tools': ['codeTools', true], '--no-code-tools': ['codeTools', false],
    '--code-collapse': ['codeCollapse', true], '--no-code-collapse': ['codeCollapse', false],
    '--chart-tools': ['chartTools', true], '--no-chart-tools': ['chartTools', false],
    '--source-toggle': ['sourceToggle', true], '--no-source-toggle': ['sourceToggle', false],
    '--chart-export': ['chartExport', true], '--no-chart-export': ['chartExport', false],
    '--chart-maximize': ['chartMaximize', true], '--no-chart-maximize': ['chartMaximize', false],
    '--print': ['print', true], '--no-print': ['print', false],
    '--theme-control': ['themeControl', true], '--no-theme-control': ['themeControl', false],
    '--strict': ['strict', true], '--no-strict': ['strict', false]
  };

  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === '--') {
      raw.positionals.push(...argv.slice(index + 1));
      break;
    }
    if (arg === '-h' || arg === '--help') {
      printUsage();
      process.exit(0);
    }
    if (Object.prototype.hasOwnProperty.call(booleanFlags, arg)) {
      const [name, value] = booleanFlags[arg];
      raw.settings[name] = value;
      continue;
    }

    if (arg === '-i' || arg === '--input') {
      raw.input = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '-o' || arg === '--output') {
      raw.output = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--title') {
      raw.title = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--config') {
      raw.configPath = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--output-mode') {
      raw.outputMode = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--output-dir') {
      raw.outputDir = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--output-name') {
      raw.outputName = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--static-dir') {
      raw.staticDir = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--public-path') {
      raw.publicPath = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--theme') {
      raw.settings.theme = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--content-width') {
      raw.settings.contentWidth = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--toc-layout') {
      raw.settings.tocLayout = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--toc-width') {
      raw.settings.tocWidth = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--visual-width') {
      raw.settings.visualWidth = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--visual-height') {
      raw.settings.visualHeight = getOptionValue(argv, index, arg);
      index++;
      continue;
    }
    if (arg === '--mermaid-security') {
      raw.settings.mermaidSecurity = getOptionValue(argv, index, arg);
      index++;
      continue;
    }

    const equals = arg.indexOf('=');
    const name = equals === -1 ? arg : arg.slice(0, equals);
    const value = equals === -1 ? '' : arg.slice(equals + 1);
    if (name === '--input' || name === '--output' || name === '--title' || name === '--config' ||
        name === '--output-mode' || name === '--output-dir' || name === '--output-name' ||
        name === '--static-dir' || name === '--public-path' ||
        name === '--theme' || name === '--content-width' || name === '--toc-layout' || name === '--toc-width' ||
        name === '--visual-width' || name === '--visual-height' || name === '--mermaid-security') {
      if (!value) fail(`${name} 需要一个值。`);
      if (name === '--input') raw.input = value;
      if (name === '--output') raw.output = value;
      if (name === '--title') raw.title = value;
      if (name === '--config') raw.configPath = value;
      if (name === '--output-mode') raw.outputMode = value;
      if (name === '--output-dir') raw.outputDir = value;
      if (name === '--output-name') raw.outputName = value;
      if (name === '--static-dir') raw.staticDir = value;
      if (name === '--public-path') raw.publicPath = value;
      if (name === '--theme') raw.settings.theme = value;
      if (name === '--content-width') raw.settings.contentWidth = value;
      if (name === '--toc-layout') raw.settings.tocLayout = value;
      if (name === '--toc-width') raw.settings.tocWidth = value;
      if (name === '--visual-width') raw.settings.visualWidth = value;
      if (name === '--visual-height') raw.settings.visualHeight = value;
      if (name === '--mermaid-security') raw.settings.mermaidSecurity = value;
      continue;
    }
    if (arg.startsWith('-')) fail(`未知选项: ${arg}`);
    raw.positionals.push(arg);
  }
  return raw;
}

function normalizeContentWidth(value, source) {
  const raw = typeof value === 'number' ? String(value) : value;
  if (typeof raw !== 'string' || !/^\d+(?:\.\d+)?%?$/.test(raw.trim())) {
    fail(`${source} 的 contentWidth 必须是 50 到 100 之间的数字或百分比。`);
  }
  const width = Number(raw.trim().replace(/%$/, ''));
  if (!Number.isFinite(width) || width < 50 || width > 100) {
    fail(`${source} 的 contentWidth 必须在 50 到 100 之间。`);
  }
  return width;
}

function normalizePercentage(value, source, name, minimum, maximum) {
  const raw = typeof value === 'number' ? String(value) : value;
  if (typeof raw !== 'string' || !/^\d+(?:\.\d+)?%?$/.test(raw.trim())) {
    fail(`${source} 的 ${name} 必须是 ${minimum} 到 ${maximum} 之间的数字或百分比。`);
  }
  const number = Number(raw.trim().replace(/%$/, ''));
  if (!Number.isFinite(number) || number < minimum || number > maximum) {
    fail(`${source} 的 ${name} 必须在 ${minimum} 到 ${maximum} 之间。`);
  }
  return number;
}

function normalizePixelSize(value, source, name, minimum, maximum) {
  const raw = typeof value === 'number' ? String(value) : value;
  if (typeof raw !== 'string' || !/^\d+$/.test(raw.trim())) {
    fail(`${source} 的 ${name} 必须是 ${minimum} 到 ${maximum} 之间的整数像素值。`);
  }
  const number = Number(raw.trim());
  if (!Number.isSafeInteger(number) || number < minimum || number > maximum) {
    fail(`${source} 的 ${name} 必须在 ${minimum} 到 ${maximum} 之间。`);
  }
  return number;
}

function normalizeSettings(value, source) {
  if (value == null) return {};
  if (typeof value !== 'object' || Array.isArray(value)) {
    fail(`${source} 必须是 JSON 对象。`);
  }

  const normalized = {};
  for (const [name, setting] of Object.entries(value)) {
    if (BOOLEAN_OPTION_NAMES.has(name)) {
      if (typeof setting !== 'boolean') fail(`${source} 的 ${name} 必须是布尔值。`);
      normalized[name] = setting;
      continue;
    }
    if (name === 'theme') {
      if (!['auto', 'light', 'dark'].includes(setting)) {
        fail(`${source} 的 theme 必须是 auto、light 或 dark。`);
      }
      normalized.theme = setting;
      continue;
    }
    if (name === 'contentWidth') {
      normalized.contentWidth = normalizeContentWidth(setting, source);
      continue;
    }
    if (name === 'tocLayout') {
      if (!['left', 'right', 'float'].includes(setting)) {
        fail(`${source} 的 tocLayout 必须是 left、right 或 float。`);
      }
      normalized.tocLayout = setting;
      continue;
    }
    if (name === 'tocWidth') {
      normalized.tocWidth = normalizePercentage(setting, source, 'tocWidth', 10, 40);
      continue;
    }
    if (name === 'visualWidth') {
      normalized.visualWidth = normalizePixelSize(setting, source, 'visualWidth', 240, 2400);
      continue;
    }
    if (name === 'visualHeight') {
      normalized.visualHeight = normalizePixelSize(setting, source, 'visualHeight', 160, 1600);
      continue;
    }
    if (name === 'markmapColors') {
      if (!setting || typeof setting !== 'object' || Array.isArray(setting)) {
        fail(`${source} 的 markmapColors 必须是含 light 和 dark 数组的对象。`);
      }
      const colors = {};
      for (const mode of ['light', 'dark']) {
        if (!Array.isArray(setting[mode]) || !setting[mode].length ||
            setting[mode].some(function(color) { return typeof color !== 'string' || !/^#[0-9a-f]{3,8}$/i.test(color); })) {
          fail(`${source} 的 markmapColors.${mode} 必须是非空的十六进制颜色数组。`);
        }
        colors[mode] = setting[mode].slice();
      }
      normalized.markmapColors = colors;
      continue;
    }
    if (name === 'mermaidSecurity') {
      if (!['strict', 'loose'].includes(setting)) {
        fail(`${source} 的 mermaidSecurity 必须是 strict 或 loose。`);
      }
      normalized.mermaidSecurity = setting;
      continue;
    }
    if (name === 'title') {
      if (typeof setting !== 'string') fail(`${source} 的 title 必须是字符串。`);
      normalized.title = setting;
      continue;
    }
    fail(`${source} 包含未知配置项: ${name}`);
  }
  return normalized;
}

function normalizeOutputOptions(value, source) {
  if (value == null) return {};
  if (typeof value !== 'object' || Array.isArray(value)) fail(`${source} 的 output 必须是 JSON 对象。`);
  const normalized = {};
  for (const [name, setting] of Object.entries(value)) {
    if (name === 'mode') {
      if (!['single', 'multi'].includes(setting)) fail(`${source} 的 output.mode 必须是 single 或 multi。`);
      normalized.mode = setting;
      continue;
    }
    if (name === 'directory') {
      if (typeof setting !== 'string' || !setting.trim()) fail(`${source} 的 output.directory 必须是非空字符串。`);
      normalized.directory = setting;
      continue;
    }
    if (name === 'fileName') {
      if (typeof setting !== 'string' || !setting.trim()) fail(`${source} 的 output.fileName 必须是非空字符串。`);
      normalized.fileName = setting;
      continue;
    }
    fail(`${source} 的 output 包含未知配置项: ${name}`);
  }
  return normalized;
}

function normalizeResourceOptions(value, source) {
  if (value == null) return {};
  if (typeof value !== 'object' || Array.isArray(value)) fail(`${source} 的 resources 必须是 JSON 对象。`);
  const normalized = {};
  for (const [name, setting] of Object.entries(value)) {
    if (name === 'config' || name === 'directory' || name === 'publicPath') {
      if (typeof setting !== 'string' || !setting.trim()) fail(`${source} 的 resources.${name} 必须是非空字符串。`);
      normalized[name] = setting;
      continue;
    }
    fail(`${source} 的 resources 包含未知配置项: ${name}`);
  }
  return normalized;
}

function normalizeServerOptions(value, source) {
  if (value == null) return {};
  if (typeof value !== 'object' || Array.isArray(value)) fail(`${source} 的 server 必须是 JSON 对象。`);
  const normalized = {};
  for (const [name, setting] of Object.entries(value)) {
    if (name === 'host' || name === 'directory') {
      if (typeof setting !== 'string' || !setting.trim()) fail(`${source} 的 server.${name} 必须是非空字符串。`);
      normalized[name] = setting;
      continue;
    }
    if (name === 'port') {
      if (!Number.isSafeInteger(setting) || setting < 0 || setting > 65535) {
        fail(`${source} 的 server.port 必须是 0 到 65535 之间的整数。`);
      }
      normalized.port = setting;
      continue;
    }
    if (name === 'open') {
      if (typeof setting !== 'boolean') fail(`${source} 的 server.open 必须是布尔值。`);
      normalized.open = setting;
      continue;
    }
    fail(`${source} 的 server 包含未知配置项: ${name}`);
  }
  return normalized;
}

function readConfig(configPath) {
  const absolutePath = path.resolve(configPath);
  let text;
  try {
    text = fs.readFileSync(absolutePath, 'utf-8');
  } catch (error) {
    fail(`无法读取配置文件 ${absolutePath}: ${error.message}`);
  }
  try {
    const value = JSON.parse(text);
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      fail(`配置文件 ${absolutePath} 必须是 JSON 对象。`);
    }
    const settings = {};
    for (const [name, setting] of Object.entries(value)) {
      if (name === 'output' || name === 'resources' || name === 'server') continue;
      settings[name] = setting;
    }
    return {
      settings: normalizeSettings(settings, `配置文件 ${absolutePath}`),
      output: normalizeOutputOptions(value.output, `配置文件 ${absolutePath}`),
      resources: normalizeResourceOptions(value.resources, `配置文件 ${absolutePath}`),
      server: normalizeServerOptions(value.server, `配置文件 ${absolutePath}`),
      path: absolutePath,
      directory: path.dirname(absolutePath)
    };
  } catch (error) {
    if (error.message && error.message.startsWith('配置文件 ')) throw error;
    fail(`配置文件 ${absolutePath} 不是有效 JSON: ${error.message}`);
  }
}

function defaultOutputPath(inputFile) {
  const withoutExtension = inputFile.replace(/\.(md|markdown|txt)$/i, '');
  return (withoutExtension === inputFile ? inputFile : withoutExtension) + '.html';
}

function normalizeOutputFileName(value, source) {
  if (typeof value !== 'string' || !value.trim()) fail(`${source} 必须是非空文件名。`);
  const fileName = value.trim();
  if (fileName !== path.basename(fileName) || fileName === '.' || fileName === '..') {
    fail(`${source} 只能是文件名，不能包含目录。`);
  }
  if (!/\.html?$/i.test(fileName)) fail(`${source} 必须以 .html 或 .htm 结尾。`);
  return fileName;
}

function normalizeManagedDirectory(value, source) {
  if (typeof value !== 'string' || !value.trim()) fail(`${source} 必须是非空相对目录。`);
  const normalized = path.normalize(value.trim());
  if (path.isAbsolute(normalized) || normalized === '.' || normalized === '..' || normalized.startsWith(`..${path.sep}`)) {
    fail(`${source} 必须是输出目录内的相对目录。`);
  }
  return normalized;
}

function normalizePublicPath(value, source) {
  if (typeof value !== 'string' || !value.trim()) fail(`${source} 必须是非空 URL 路径。`);
  let publicPath = value.trim();
  if (/^[a-z][a-z0-9+.-]*:/i.test(publicPath) || publicPath.startsWith('//')) {
    fail(`${source} 只接受本地 URL 路径，不能使用 URL 协议或协议相对地址。`);
  }
  if (/[\\?\#\u0000-\u001f<>"']/.test(publicPath)) fail(`${source} 包含不安全字符。`);
  if (!publicPath.endsWith('/')) publicPath += '/';
  return publicPath;
}

function parseInvocation(argv) {
  const raw = parseRawArguments(argv);
  const fileConfig = raw.configPath ? readConfig(raw.configPath) : {
    settings: {}, output: {}, resources: {}, server: {}, path: '', directory: process.cwd()
  };
  const fileSettings = fileConfig.settings;
  const settings = Object.assign({}, DEFAULT_OPTIONS, fileSettings, normalizeSettings(raw.settings, '命令行选项'));
  const positionals = raw.positionals.slice();
  const input = raw.input || positionals.shift() || '';
  const positionalOutput = positionals.shift() || '';
  if (positionals.length) fail('只接受一个输入文件和一个可选输出文件。');
  if (!input) fail('缺少输入文件。使用 --input <file>，或运行 node build.js <input.md>。');
  if (raw.output && positionalOutput) fail('不能同时通过 --output 和位置参数指定输出文件。');
  if ((raw.output || positionalOutput) && (raw.outputDir || raw.outputName)) {
    fail('--output 不能与 --output-dir 或 --output-name 同时使用。');
  }

  const inputFile = path.resolve(input);
  if (!fs.existsSync(inputFile)) fail(`输入文件不存在: ${inputFile}`);
  const outputOptions = Object.assign({}, DEFAULT_OUTPUT_OPTIONS, fileConfig.output);
  if (raw.outputMode) outputOptions.mode = normalizeOutputOptions({ mode: raw.outputMode }, '命令行选项').mode;
  if (raw.outputDir) outputOptions.directory = raw.outputDir;
  if (raw.outputName) outputOptions.fileName = raw.outputName;

  const explicitOutput = raw.output || positionalOutput;
  let outputFile;
  if (explicitOutput) {
    outputFile = path.resolve(explicitOutput);
  } else {
    let outputDir = path.dirname(defaultOutputPath(inputFile));
    if (raw.outputDir) outputDir = path.resolve(raw.outputDir);
    else if (fileConfig.output.directory) outputDir = path.resolve(fileConfig.directory, fileConfig.output.directory);
    const outputName = outputOptions.fileName
      ? normalizeOutputFileName(outputOptions.fileName, 'output.fileName')
      : path.basename(defaultOutputPath(inputFile));
    outputFile = path.join(outputDir, outputName);
  }
  const outputDir = path.dirname(outputFile);
  fs.mkdirSync(outputDir, { recursive: true });
  const inputStat = fs.statSync(inputFile);
  if (fs.existsSync(outputFile)) {
    // realpath 字符串比较无法识别硬链接：不同目录项可指向同一 inode，
    // 直接覆盖会截断共享 inode，连带改写输入文件或其他硬链接文件。
    const outputStat = fs.statSync(outputFile);
    if (!outputStat.isFile() || outputStat.nlink > 1) {
      fail(`输出目标必须是普通文件且不能是硬链接: ${outputFile}`);
    }
    if (outputStat.dev === inputStat.dev && outputStat.ino === inputStat.ino) {
      fail('输出文件不能覆盖输入文件。');
    }
  }

  const resourceOptions = Object.assign({}, DEFAULT_RESOURCE_OPTIONS, fileConfig.resources);
  if (raw.staticDir) resourceOptions.directory = raw.staticDir;
  if (raw.publicPath) resourceOptions.publicPath = raw.publicPath;
  resourceOptions.directory = normalizeManagedDirectory(resourceOptions.directory, 'resources.directory');
  resourceOptions.publicPath = resourceOptions.publicPath
    ? normalizePublicPath(resourceOptions.publicPath, 'resources.publicPath')
    : './' + resourceOptions.directory.split(path.sep).map(encodeURIComponent).join('/') + '/';

  return {
    inputFile,
    outputFile,
    title: raw.title || fileSettings.title || path.basename(inputFile, path.extname(inputFile)),
    options: settings,
    output: { mode: outputOptions.mode },
    resources: resourceOptions
  };
}

let invocation;
try {
  invocation = parseInvocation(process.argv.slice(2));
} catch (error) {
  console.error(`生成失败: ${error.message || error}`);
  process.exit(1);
}

const vendorDir = path.join(__dirname, 'vendor');
const defaultResourceConfigPath = path.join(__dirname, '..', 'assets', 'default-resources.json');

const { inputFile, outputFile, title, options, output, resources } = invocation;
const sourceMarkdown = fs.readFileSync(inputFile, 'utf-8');
const sourceDownloadName = (function() {
  const basename = path.basename(inputFile);
  if (/\.(?:md|markdown)$/i.test(basename)) return basename;
  const stem = basename.replace(/\.[^.]+$/, '') || 'document';
  return stem + '.md';
})();

function readJsonObject(file, label) {
  let text;
  try {
    text = fs.readFileSync(file, 'utf-8');
  } catch (error) {
    fail(`无法读取${label} ${file}: ${error.message}`);
  }
  try {
    const value = JSON.parse(text);
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail(`${label} ${file} 必须是 JSON 对象。`);
    return value;
  } catch (error) {
    if (error.message && error.message.includes(label)) throw error;
    fail(`${label} ${file} 不是有效 JSON: ${error.message}`);
  }
}

function validateResourceFileName(value, source) {
  if (typeof value !== 'string' || !value.trim()) fail(`${source} 必须是非空文件名。`);
  const fileName = value.trim();
  if (fileName !== path.basename(fileName) || fileName === '.' || fileName === '..') {
    fail(`${source} 只能是文件名，不能包含目录。`);
  }
  return fileName;
}

function loadResourceManifest() {
  const defaultManifest = readJsonObject(defaultResourceConfigPath, '默认资源清单');
  const allowedNames = new Set(RESOURCE_ORDER);
  const manifest = {};
  const outputNames = new Map();
  RESOURCE_ORDER.forEach(function(name) {
    const base = defaultManifest[name];
    if (!base || typeof base !== 'object' || Array.isArray(base)) {
      fail(`默认资源清单缺少资源: ${name}`);
    }
    const item = Object.assign({}, base);
    if (!['script', 'style'].includes(item.type)) fail(`资源 ${name} 的 type 必须是 script 或 style。`);
    if (typeof item.source !== 'string' || !item.source.trim()) fail(`资源 ${name} 的 source 必须是非空字符串。`);
    if (!Array.isArray(item.dependencies) || item.dependencies.some(function(dependency) { return !allowedNames.has(dependency); })) {
      fail(`资源 ${name} 的 dependencies 包含未知资源。`);
    }
    const sourceBase = path.dirname(defaultResourceConfigPath);
    item.sourceFile = path.resolve(sourceBase, item.source);
    item.output = validateResourceFileName(item.output, `资源 ${name} 的 output`);
    let sourceStat;
    try {
      sourceStat = fs.lstatSync(item.sourceFile);
    } catch (error) {
      if (error.code === 'ENOENT') fail(`资源 ${name} 的源文件不存在: ${item.sourceFile}`);
      throw error;
    }
    if (!sourceStat.isFile()) fail(`资源 ${name} 的源文件必须是普通文件: ${item.sourceFile}`);
    const outputKey = item.output.toLowerCase();
    if (outputNames.has(outputKey)) {
      fail(`资源 ${name} 与 ${outputNames.get(outputKey)} 使用了重复的输出文件名: ${item.output}`);
    }
    outputNames.set(outputKey, name);
    manifest[name] = item;
  });
  return manifest;
}

function parseMarkdownTokens(markdown) {
  const markdownit = require(path.join(vendorDir, 'markdown-it.min.js'));
  const parser = markdownit({ html: false });
  return parser.parse(markdown, {});
}

function fenceTokens(tokens) {
  return tokens.filter(function(token) { return token.type === 'fence'; });
}

function visualFence(token) {
  const match = String(token.info || '').trim().match(/^(mermaid|markmap|mindmap|dot|graphviz|echarts)(?:[ \t]+(.+))?$/i);
  if (!match) return null;
  return { kind: match[1].toLowerCase(), option: (match[2] || '').trim() };
}

function markdownOutsideFenceLines(markdown, tokens) {
  const lines = markdown.split(/\r\n|\r|\n/);
  tokens.forEach(function(token) {
    if (!token.map) return;
    for (let line = token.map[0]; line < token.map[1]; line++) lines[line] = '';
  });
  return lines.join('\n');
}

function detectDocumentFeatures(markdown, tokens) {
  const fences = fenceTokens(tokens);
  const outside = markdownOutsideFenceLines(markdown, fences);
  const visuals = fences.map(visualFence);
  const hasMarkmap = visuals.some(function(item) { return item && (item.kind === 'markmap' || item.kind === 'mindmap'); });
  return {
    highlight: fences.some(function(fence, index) { return !!fence.info && !visuals[index]; }),
    math: hasMarkmap || /(^|[^\\])\$\$[\s\S]*?\$\$/m.test(outside) || /(^|[^\\])\$(?!\$)[^\r\n$]*\S[^\r\n$]*\$/m.test(outside),
    mermaid: visuals.some(function(item) { return item && item.kind === 'mermaid'; }),
    markmap: hasMarkmap,
    echarts: visuals.some(function(item) { return item && item.kind === 'echarts'; })
  };
}

function selectedResourceNames(features, manifest) {
  const selected = new Set(['markdownIt']);
  if (features.highlight) selected.add('highlightJs');
  if (features.math) selected.add('katexJs');
  if (features.mermaid) selected.add('mermaid');
  if (features.markmap) selected.add('markmapView');
  function includeDependencies(name) {
    if (!selected.has(name)) selected.add(name);
    manifest[name].dependencies.forEach(function(dependency) {
      if (!selected.has(dependency)) {
        selected.add(dependency);
        includeDependencies(dependency);
      }
    });
  }
  Array.from(selected).forEach(includeDependencies);
  return RESOURCE_ORDER.filter(function(name) { return selected.has(name); });
}

function resourceContent(name, item) {
  let content = fs.readFileSync(item.sourceFile, 'utf-8');
  if (name === 'mermaid') {
    content = content.replace(
      'globalThis.mermaid = globalThis.__esbuild_esm_mermaid.default;',
      'globalThis.mermaid = __esbuild_esm_mermaid.default;'
    );
  }
  if (name === 'd3') content += '\nvar d3=globalThis.d3;';
  if (name === 'katexCss') content = content.replace(/@font-face\{[^}]*\}/g, '');
  return stripIndentation(content);
}

function escAttribute(value) {
  return esc(value);
}

function buildResourceMarkup(selectedNames, manifest) {
  const styles = [];
  const scripts = [];
  if (output.mode === 'single') {
    selectedNames.forEach(function(name) {
      const item = manifest[name];
      const content = resourceContent(name, item);
      if (item.type === 'script' && /<\/script/i.test(content)) fail(`资源 ${name} 包含不能安全内联的 </script。`);
      if (item.type === 'style' && /<\/style/i.test(content)) fail(`资源 ${name} 包含不能安全内联的 </style。`);
      const markup = item.type === 'style'
        ? `<style>${content}</style>`
        : `<script>${content}</script>`;
      (item.type === 'style' ? styles : scripts).push(markup);
    });
    return { styles: styles.join('\n'), scripts: scripts.join('\n'), copied: [] };
  }

  const staticRoot = path.resolve(path.dirname(outputFile), resources.directory);
  const relativeStaticRoot = path.relative(path.dirname(outputFile), staticRoot);
  if (relativeStaticRoot === '..' || relativeStaticRoot.startsWith(`..${path.sep}`) || path.isAbsolute(relativeStaticRoot)) {
    fail('resources.directory 必须位于输出 HTML 所在目录内。');
  }
  let current = path.dirname(outputFile);
  for (const segment of resources.directory.split(path.sep)) {
    current = path.join(current, segment);
    let stat;
    try {
      stat = fs.lstatSync(current);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      fs.mkdirSync(current);
      stat = fs.lstatSync(current);
    }
    if (stat.isSymbolicLink()) fail(`resources.directory 不能包含软链接: ${current}`);
    if (!stat.isDirectory()) fail(`resources.directory 的路径组件必须是目录: ${current}`);
  }
  const pendingResources = selectedNames.map(function(name) {
    const item = manifest[name];
    const target = path.join(staticRoot, item.output);
    let targetStat = null;
    try {
      targetStat = fs.lstatSync(target);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    if (targetStat && (targetStat.isSymbolicLink() || !targetStat.isFile() || targetStat.nlink > 1)) {
      fail(`资源输出目标必须是普通文件且不能是硬链接: ${target}`);
    }
    const sourceRealPath = fs.realpathSync(item.sourceFile);
    const targetRealPath = targetStat ? fs.realpathSync(target) : path.join(fs.realpathSync(staticRoot), item.output);
    if (sourceRealPath === targetRealPath) fail(`资源 ${name} 的源文件不能与输出目标相同: ${target}`);
    return { name, item, target, content: resourceContent(name, item) };
  });

  const copied = [];
  pendingResources.forEach(function(pending) {
    const { item, target, content } = pending;
    const flags = fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_TRUNC |
      (fs.constants.O_NOFOLLOW || 0);
    let descriptor;
    try {
      descriptor = fs.openSync(target, flags, 0o644);
      fs.writeFileSync(descriptor, content, 'utf-8');
    } finally {
      if (descriptor != null) fs.closeSync(descriptor);
    }
    copied.push(target);
    const url = resources.publicPath + encodeURIComponent(item.output);
    const markup = item.type === 'style'
      ? `<link rel="stylesheet" href="${escAttribute(url)}">`
      : `<script src="${escAttribute(url)}"></script>`;
    (item.type === 'style' ? styles : scripts).push(markup);
  });
  return { styles: styles.join('\n'), scripts: scripts.join('\n'), copied };
}

const resourceManifest = loadResourceManifest();
const parsedMarkdownTokens = parseMarkdownTokens(sourceMarkdown);
const documentFeatures = detectDocumentFeatures(sourceMarkdown, parsedMarkdownTokens);
const selectedResources = selectedResourceNames(documentFeatures, resourceManifest);

function esc(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function licenseMarkup() {
  const root = path.resolve(__dirname, '..');
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'licenses', 'manifest.json'), 'utf8'));
  if (manifest.schema_version !== 1 || !Array.isArray(manifest.files) || !manifest.files.length) {
    throw new Error('无效的许可证清单。');
  }
  const names = ['LICENSE', 'THIRD_PARTY_NOTICES.md'].concat(manifest.files.map(function(entry) {
    if (typeof entry.file !== 'string' || !entry.file.startsWith('licenses/') ||
        entry.file.split('/').includes('..') || entry.file.includes('\\')) {
      throw new Error('许可证路径必须位于 licenses/。');
    }
    return entry.file;
  }));
  const text = names.map(function(name) {
    return name + '\n\n' + fs.readFileSync(path.join(root, name), 'utf8');
  }).join('\n\n--------------------\n\n');
  const version = fs.readFileSync(path.join(root, 'VERSION'), 'utf8').trim();
  if (!/^\d+\.\d+\.\d+(?:rc[1-9]\d*)?$/.test(version)) throw new Error('无效的源码版本。');
  // This content identity works in source archives and installed runtimes too.
  // It never labels a dirty checkout as an immutable published Git revision.
  const identityFiles = Array.from(new Set(names.concat([
    'VERSION', 'scripts/build.js', 'assets/default-resources.json', 'licenses/manifest.json'
  ], manifest.vendor_files.map(entry => entry.file)))).sort();
  const hashes = identityFiles.map(function(name) {
    if (!/^(?:scripts\/vendor\/[^/]+|licenses\/[^\\]+|VERSION|LICENSE|THIRD_PARTY_NOTICES\.md|scripts\/build\.js|assets\/default-resources\.json)$/.test(name) || name.split('/').includes('..')) {
      throw new Error('无效的源码标识路径。');
    }
    return crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex') + '  ' + name;
  }).join('\n') + '\n';
  const identity = crypto.createHash('sha256').update(hashes).digest('hex');
  return '<details id="ai-docs-licenses" style="margin:1rem;break-before:page">' +
    '<summary>AI Docs · Software licenses / 软件许可证</summary>' +
    '<p>Runtime source / 运行时源码：<a href="https://github.com/hymsk/ai-docs">hymsk/ai-docs</a> · AGPL-3.0-or-later. ' +
    'Document content remains subject to its own terms / 文档内容遵循其自身条款。</p>' +
    '<p>Source version / 源码版本：' + esc(version) + ' · Renderer identity (SHA-256): <code id="ai-docs-source-id">' + identity + '</code></p>' +
    '<p>Distributors must provide matching source, including modifications. This digest identifies renderer materials, not a published release or the document content. / 分发者须提供含修改的对应源码；摘要标识渲染材料，不代表已发布版本，也不包含用户文档。</p>' +
    '<details><summary>Source file checksums / 源码文件摘要</summary><pre>' + esc(hashes) + '</pre></details>' +
    '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(text) + '</pre></details>';
}

function stripIndentation(value) {
  return value.replace(/\r?\n[ \t]+/g, '\n').trim();
}

function scriptJson(value) {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

function cleanSvg(svg) {
  const cleaned = String(svg)
    .replace(/^<\?xml[^>]*\?>\s*/i, '')
    .replace(/^<!DOCTYPE[^>]*(?:\[[\s\S]*?\]\s*)?>\s*/i, '')
    .replace(/^(?:<!--[^]*?-->\s*)+/i, '')
    .trim();
  if (!/^<svg\b[\s\S]*<\/svg>$/i.test(cleaned)) {
    throw new Error('渲染结果不是有效 SVG。');
  }
  return cleaned.replace(/<svg\b([^>]*)>/i, '<svg class="static-svg"$1>');
}

let markmapProbeParser = null;

function markmapProbe() {
  if (!markmapProbeParser) {
    const markdownit = require(path.join(vendorDir, 'markdown-it.min.js'));
    markmapProbeParser = markdownit({ html: true, linkify: false });
  }
  return markmapProbeParser;
}

function markmapContainsRawHtml(source) {
  // 不能用正则模拟 HTML 语法：带引号的属性值可以合法包含 < >，
  // 例如 <img data-x="<" onerror=...> 会绕过属性段不允许尖括号的正则。
  // 改用与 Markmap 内置解析器一致的 Markdown 解析模型，拒绝全部 raw HTML token。
  const stack = markmapProbe().parse(source, {}).slice();
  while (stack.length) {
    const token = stack.pop();
    if (token.type === 'html_block' || token.type === 'html_inline') return true;
    if (token.children && token.children.length) stack.push(...token.children);
  }
  return false;
}

function assertSafeMarkmapSource(source) {
  if (markmapContainsRawHtml(source)) {
    throw new Error('Markmap 源码不能包含原始 HTML。');
  }
}

function visualDimensions(width, height, source) {
  if (width == null || height == null) return null;
  return {
    width: normalizePixelSize(width, source, '图表宽度', 240, 2400),
    height: normalizePixelSize(height, source, '图表高度', 160, 1600)
  };
}

// 内容级图表问题不再让整个文档构建失败：这些 fence 会降级为普通代码块，
// 并把原因交给客户端在代码块表头展示（警示标识 + 悬浮提示）。
// 输入/配置/资源等基础设施错误仍然 fail()，与图表降级互不影响。
function collectDegradedFences() {
  const degraded = {};
  const warnings = [];
  const lines = new Set();
  const name = path.basename(inputFile);

  const record = function(line, language, detail) {
    if (degraded[line]) return;
    const message = `${name}:${line}: ${detail}`;
    degraded[line] = { language, message };
    lines.add(line);
    warnings.push(`${message}（已降级为代码块展示）`);
  };

  fenceTokens(parsedMarkdownTokens).forEach(function(token) {
    const visual = visualFence(token);
    if (!visual) return;
    const line = token.map ? token.map[0] + 1 : 1;
    const context = `${name}:${line}`;

    if (visual.kind === 'dot' || visual.kind === 'graphviz') {
      record(line, visual.kind, '不支持 dot/graphviz 图表代码块；AI Docs 不再内置 Graphviz，请改用 Mermaid flowchart。');
      return;
    }

    if (visual.option) {
      const size = visual.option.match(/^size=(\d+)x(\d+)$/i);
      if (!size) {
        record(line, visual.kind, '图表代码块只支持 size=<宽>x<高> 参数。');
        return;
      }
      try {
        visualDimensions(size[1], size[2], context);
      } catch (error) {
        const raw = String((error && error.message) || error);
        const detail = raw.startsWith(context)
          ? raw.slice(context.length).replace(/^\s*的\s*/, '').replace(/^(图表宽度|图表高度)\s+/, '$1')
          : raw;
        record(line, visual.kind, detail);
        return;
      }
    }

    if (visual.kind === 'markmap' || visual.kind === 'mindmap') {
      try {
        assertSafeMarkmapSource(token.content);
      } catch (error) {
        record(line, visual.kind, String((error && error.message) || error));
      }
    }
  });

  return { degraded, warnings, lines };
}

async function preRenderStaticCharts(markdown, degradedLines) {
  let index = 0;
  let echartsRenderer = null;
  const blocks = {};
  const failures = [];
  const fences = fenceTokens(parsedMarkdownTokens).filter(function(token) {
    const visual = visualFence(token);
    if (!visual || visual.kind !== 'echarts') return false;
    return !degradedLines.has(token.map ? token.map[0] + 1 : 1);
  });

  for (const token of fences) {
    const visual = visualFence(token);
    const content = token.content;
    const line = token.map ? token.map[0] + 1 : 1;
    const size = visual.option ? visual.option.match(/^size=(\d+)x(\d+)$/i) : null;
    const dimensions = size ? visualDimensions(size[1], size[2], `${inputFile}:${line}`) : null;
    const visualWidth = dimensions ? dimensions.width : options.visualWidth;
    const visualHeight = dimensions ? dimensions.height : options.visualHeight;
    const id = `static-echarts-${index++}`;
    const label = 'ECharts 图表';
    const language = 'json';

    try {
      if (!echartsRenderer) echartsRenderer = require(path.join(vendorDir, 'echarts.min.js'));
      const chartOption = JSON.parse(content.trim());
      if (!chartOption || typeof chartOption !== 'object' || Array.isArray(chartOption)) {
        throw new Error('ECharts 配置必须是 JSON 对象。');
      }
      const renderEcharts = function(theme) {
        const themedOption = JSON.parse(JSON.stringify(chartOption));
        if (themedOption.backgroundColor == null) themedOption.backgroundColor = theme === 'dark' ? '#100c2a' : '#ffffff';
        let chart;
        try {
          chart = echartsRenderer.init(null, theme === 'dark' ? 'dark' : null, {
            renderer: 'svg', ssr: true, width: visualWidth, height: visualHeight
          });
          chart.setOption(themedOption);
          return chart.renderToSVGString();
        } finally {
          if (chart) chart.dispose();
        }
      };
      const svg = renderEcharts('light');
      const darkSvg = renderEcharts('dark');
      blocks[id] = {
        id, kind: 'echarts', label, language, source: content, dimensions, svg: cleanSvg(svg),
        darkSvg: cleanSvg(darkSvg), error: ''
      };
    } catch (error) {
      const message = `${inputFile}:${line}: ${label} 渲染校验失败: ${error.message || error}`;
      failures.push(message);
      blocks[id] = {
        id, kind: 'echarts', label, language, source: content,
        dimensions, svg: '', darkSvg: '', error: message
      };
    }

  }

  if (failures.length && options.strict) {
    throw new Error(`图表渲染校验失败:\n- ${failures.join('\n- ')}`);
  }
  return { markdown, blocks, warnings: failures };
}

function bootstrapTheme(configuredTheme) {
  var storageKey = 'ai-docs-theme';
  var theme = configuredTheme;
  try {
    var stored = window.localStorage.getItem(storageKey);
    if (stored === 'auto' || stored === 'light' || stored === 'dark') theme = stored;
  } catch (error) {}
  if (theme !== 'auto' && theme !== 'light' && theme !== 'dark') theme = 'auto';
  var dark = theme === 'dark' || (theme === 'auto' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme-preference', theme);
}

function clientRuntime(raw, sourceDownloadName, staticBlocks, viewerOptions, title, degradedFences) {
  'use strict';

  // 构建期预渲染不改动 Markdown 原文，渲染输入与下载源是同一份内容，
  // 只嵌入一次，避免大文档在 HTML 中重复占用体积。
  var sourceMarkdown = raw;
  var settings = {
    toc: viewerOptions.toc !== false,
    codeTools: viewerOptions.codeTools !== false,
    codeCollapse: viewerOptions.codeCollapse === true,
    chartTools: viewerOptions.chartTools !== false,
    sourceToggle: viewerOptions.sourceToggle !== false,
    chartExport: viewerOptions.chartExport !== false,
    chartMaximize: viewerOptions.chartMaximize !== false,
    print: viewerOptions.print !== false,
    themeControl: viewerOptions.themeControl !== false,
    theme: viewerOptions.theme || 'auto',
    contentWidth: Number(viewerOptions.contentWidth) || 80,
    tocLayout: viewerOptions.tocLayout === 'left' || viewerOptions.tocLayout === 'float' ? viewerOptions.tocLayout : 'right',
    tocWidth: Number(viewerOptions.tocWidth) || 20,
    visualWidth: Number(viewerOptions.visualWidth) || 960,
    visualHeight: Number(viewerOptions.visualHeight) || 520,
    markmapColors: viewerOptions.markmapColors || { light: ['#0077b6'], dark: ['#a78bfa'] },
    mermaidSecurity: viewerOptions.mermaidSecurity === 'loose' ? 'loose' : 'strict'
  };
  var storageKey = 'ai-docs-theme';
  var viewerLayout = document.getElementById('viewer-layout');
  var container = document.getElementById('content');
  var controls = document.getElementById('viewer-controls');
  var tocPanel = document.getElementById('toc-panel');
  var tocContent = document.getElementById('toc-content');
  var renderStatus = null;
  var tocToggle = null;
  var themeButton = null;
  var headingEntries = [];
  var headingCounts = Object.create(null);
  var mermaidBlocks = [];
  var markmapBlocks = [];
  var staticBlockQueue = Object.keys(staticBlocks).map(function(id) { return staticBlocks[id]; });
  var staticRenderErrors = [];
  var renderErrors = [];
  var renderGeneration = 0;
  var dynamicVisualsReady = Promise.resolve();
  var visualsStarted = false;
  var visualResizeFrame = 0;
  var allVisualShells = [];
  var visualZoomState = Object.create(null);
  var wasFloatingToc = null;
  var effectiveTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  var visualDefaultMaxWidth = settings.visualWidth;
  var visualDefaultMaxHeight = settings.visualHeight;

  document.documentElement.style.setProperty('--content-width', settings.contentWidth + '%');
  document.documentElement.style.setProperty('--toc-width', settings.tocWidth + '%');
  document.documentElement.style.setProperty('--visual-width', visualDefaultMaxWidth + 'px');
  document.documentElement.style.setProperty('--visual-height', visualDefaultMaxHeight + 'px');
  if (viewerLayout) viewerLayout.setAttribute('data-toc-layout', settings.tocLayout);

  function escapeHtml(value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function normalizeTheme(value) {
    return value === 'light' || value === 'dark' || value === 'auto' ? value : 'auto';
  }

  function getThemePreference() {
    try {
      var saved = window.localStorage.getItem(storageKey);
      if (saved === 'light' || saved === 'dark' || saved === 'auto') return saved;
    } catch (error) {}
    return normalizeTheme(settings.theme);
  }

  function resolveTheme(preference) {
    if (preference === 'dark') return 'dark';
    if (preference === 'light') return 'light';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyTheme(preference, persist) {
    var normalized = normalizeTheme(preference);
    effectiveTheme = resolveTheme(normalized);
    document.documentElement.setAttribute('data-theme', effectiveTheme);
    document.documentElement.setAttribute('data-theme-preference', normalized);
    updateThemeButton(normalized);
    if (persist) {
      try { window.localStorage.setItem(storageKey, normalized); } catch (error) {}
    }
    if (visualsStarted) {
      refreshStaticCharts();
      refreshDynamicVisuals();
    }
  }

  function addButton(parent, text, titleText, onClick, className) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = className || 'viewer-btn';
    button.textContent = text;
    button.title = titleText || text;
    button.setAttribute('aria-label', button.title);
    button.addEventListener('click', onClick);
    parent.appendChild(button);
    return button;
  }

  function iconSvg(name) {
    var icons = {
      copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2"></rect><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path></svg>',
      check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"></path></svg>',
      collapse: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 15 6-6 6 6"></path></svg>',
      expand: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>',
      maximize: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>',
      minimize: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3m8-5a2 2 0 0 1 2-2h3"></path></svg>',
      sun: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"></circle><path d="M12 2.5v2.2M12 19.3v2.2M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6"></path></svg>',
      moon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.6 14.2A8.6 8.6 0 0 1 9.8 3.4a8.6 8.6 0 1 0 10.8 10.8z"></path></svg>',
      themeAuto: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.6"></circle><path d="M12 3.4a8.6 8.6 0 0 1 0 17.2z" fill="currentColor" stroke="none"></path></svg>',
      warning: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4.2 21 19.8H3z"></path><path d="M12 10v4.1"></path><path d="M12 17.3h.01"></path></svg>'
    };
    return icons[name] || '';
  }

  var themeModes = [
    { value: 'auto', label: '跟随系统', icon: 'themeAuto' },
    { value: 'light', label: '亮色', icon: 'sun' },
    { value: 'dark', label: '暗色', icon: 'moon' }
  ];

  function themeModeFor(preference) {
    var normalized = normalizeTheme(preference);
    for (var index = 0; index < themeModes.length; index++) {
      if (themeModes[index].value === normalized) return themeModes[index];
    }
    return themeModes[0];
  }

  function updateThemeButton(preference) {
    if (!themeButton) return;
    var mode = themeModeFor(preference);
    themeButton.innerHTML = iconSvg(mode.icon) + '<span class="theme-toggle-label">' + mode.label + '</span>';
    themeButton.title = '页面主题：' + mode.label + '（点击切换）';
    themeButton.setAttribute('aria-label', themeButton.title);
  }

  function cycleTheme() {
    var current = getThemePreference();
    var index = themeModes.findIndex(function(mode) { return mode.value === current; });
    var next = themeModes[(index + 1 + themeModes.length) % themeModes.length];
    applyTheme(next.value, true);
  }

  function setIconButton(button, icon, label) {
    button.innerHTML = iconSvg(icon);
    button.title = label;
    button.setAttribute('aria-label', label);
  }

  function addIconButton(parent, icon, label, onClick, className) {
    var button = addButton(parent, '', label, onClick, (className || '') + ' icon-button');
    setIconButton(button, icon, label);
    return button;
  }

  function setRenderStatus(loading) {
    if (!renderStatus) return;
    renderStatus.classList.remove('is-ok', 'is-error', 'is-loading');
    if (loading) {
      renderStatus.hidden = true;
      renderStatus.textContent = '';
      renderStatus.title = '';
      return;
    }
    if (renderErrors.length) {
      renderStatus.hidden = false;
      renderStatus.classList.add('is-error');
      renderStatus.textContent = '渲染错误 ' + renderErrors.length;
      renderStatus.title = renderErrors.map(function(error) {
        return error.label + ': ' + error.message;
      }).join('\n');
      return;
    }
    renderStatus.hidden = true;
    renderStatus.textContent = '';
    renderStatus.title = '';
  }

  function recordRenderError(label, message) {
    renderErrors.push({ label: label, message: String(message || '未知错误') });
  }

  function recordStaticRenderError(label, message) {
    var error = { label: label, message: String(message || '未知错误') };
    staticRenderErrors.push(error);
    recordRenderError(error.label, error.message);
  }

  function isFloatingToc() {
    return !window.matchMedia || window.matchMedia('(max-width: 760px)').matches || settings.tocLayout === 'float';
  }

  function updateTocLayout() {
    if (!viewerLayout || !settings.toc) return;
    var floating = isFloatingToc();
    viewerLayout.classList.toggle('toc-is-floating', floating);
    if (wasFloatingToc === floating) return;
    wasFloatingToc = floating;
    setTocOpen(floating ? false : true, true);
  }

  function setTocOpen(open, preserveFocus) {
    if (!tocPanel || !tocToggle) return;
    tocPanel.classList.toggle('is-open', open);
    if (viewerLayout) viewerLayout.classList.toggle('toc-is-open', open);
    tocPanel.setAttribute('aria-hidden', open ? 'false' : 'true');
    tocToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    tocToggle.textContent = open ? '收起目录' : '打开目录';
    tocToggle.title = open ? '收起目录' : '打开目录';
    tocToggle.setAttribute('aria-label', tocToggle.title);
    if (!preserveFocus) scheduleVisualResize();
  }

  function setupHeader() {
    var brand = document.createElement('span');
    brand.className = 'viewer-brand';
    var brandText = document.createElement('span');
    brandText.className = 'viewer-brand-text';
    brandText.textContent = title;
    brand.appendChild(brandText);
    controls.appendChild(brand);

    var actions = document.createElement('div');
    actions.className = 'viewer-actions';
    controls.appendChild(actions);

    if (settings.toc) {
      tocToggle = addButton(actions, '打开目录', '打开目录', function() {
        setTocOpen(!tocPanel.classList.contains('is-open'));
      });
      tocToggle.setAttribute('aria-expanded', 'false');
      tocToggle.setAttribute('aria-controls', 'toc-panel');
      updateTocLayout();
    } else if (tocPanel) {
      tocPanel.remove();
      tocPanel = null;
    }

    if (settings.themeControl) {
      themeButton = addButton(actions, '', '页面主题', cycleTheme, 'viewer-btn theme-toggle');
      updateThemeButton(getThemePreference());
    }

    addButton(actions, '下载 MD', '下载源 Markdown 文档', downloadSourceMarkdown);

    if (settings.print) {
      addButton(actions, '打印', '打开系统打印窗口', printDocument);
    }

    renderStatus = document.createElement('span');
    renderStatus.className = 'render-status';
    renderStatus.hidden = true;
    actions.appendChild(renderStatus);
  }

  function slugify(value) {
    var text = String(value || '').trim().toLowerCase();
    if (text.normalize) text = text.normalize('NFKD');
    text = text.replace(/[^a-z0-9_\-\u4e00-\u9fff]+/g, '-').replace(/^-+|-+$/g, '');
    return text || 'section';
  }

  function uniqueSlug(value) {
    var base = slugify(value);
    var count = headingCounts[base] || 0;
    headingCounts[base] = count + 1;
    return count ? base + '-' + count : base;
  }

  function renderMath(tex, display) {
    if (!window.katex) return '<span class="math-error">KaTeX 引擎未加载。</span>';
    try {
      return window.katex.renderToString(tex, { displayMode: display, throwOnError: false });
    } catch (error) {
      return '<span class="math-error">' + escapeHtml(error.message || tex) + '</span>';
    }
  }

  setupHeader();
  applyTheme(getThemePreference(), false);

  var md = window.markdownit({
    html: false,
    linkify: true,
    typographer: true,
    highlight: function(str, lang) {
      if (window.hljs && lang && window.hljs.getLanguage(lang)) {
        try {
          return '<pre><code class="hljs language-' + escapeHtml(lang) + '">' +
            window.hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
            '</code></pre>';
        } catch (error) {}
      }
      return '<pre><code class="hljs">' + md.utils.escapeHtml(str) + '</code></pre>';
    }
  });

  md.block.ruler.before('fence', 'math_display', function(state, startLine, endLine, silent) {
    var start = state.bMarks[startLine] + state.tShift[startLine];
    var max = state.eMarks[startLine];
    if (start + 2 > max || state.src.slice(start, start + 2) !== '$$') return false;

    var firstLine = state.src.slice(start + 2, max);
    var nextLine = startLine + 1;
    var content = '';
    var closeIndex = firstLine.indexOf('$$');
    if (closeIndex >= 0) {
      content = firstLine.slice(0, closeIndex);
    } else {
      var lines = [firstLine];
      var found = false;
      while (nextLine < endLine) {
        var lineStart = state.bMarks[nextLine] + state.tShift[nextLine];
        var line = state.src.slice(lineStart, state.eMarks[nextLine]);
        closeIndex = line.indexOf('$$');
        if (closeIndex >= 0) {
          lines.push(line.slice(0, closeIndex));
          found = true;
          nextLine++;
          break;
        }
        lines.push(line);
        nextLine++;
      }
      if (!found) return false;
      content = lines.join('\n');
    }
    if (silent) return true;
    state.line = closeIndex >= 0 && nextLine === startLine + 1 ? startLine + 1 : nextLine;
    var token = state.push('math_display', 'math', 0);
    token.block = true;
    token.content = content.trim();
    token.map = [startLine, state.line];
    return true;
  }, { alt: ['paragraph', 'reference', 'blockquote', 'list'] });
  md.renderer.rules.math_display = function(tokens, index) {
    return '<div class="math-display">' + renderMath(tokens[index].content, true) + '</div>\n';
  };

  md.inline.ruler.after('escape', 'math_inline', function(state, silent) {
    var src = state.src;
    var pos = state.pos;
    if (src.charCodeAt(pos) !== 0x24 || src.charCodeAt(pos + 1) === 0x24) return false;
    if (pos > 0 && src.charCodeAt(pos - 1) === 0x5c) return false;
    var end = pos + 1;
    while (end < src.length) {
      if (src.charCodeAt(end) === 0x0a) return false;
      if (src.charCodeAt(end) === 0x24) {
        if (src.charCodeAt(end + 1) === 0x24) { end += 2; continue; }
        break;
      }
      end++;
    }
    if (end >= src.length) return false;
    var content = src.slice(pos + 1, end);
    if (!content.trim()) return false;
    if (!silent) {
      var token = state.push('math_inline', '', 0);
      token.content = content;
    }
    state.pos = end + 1;
    return true;
  });
  md.renderer.rules.math_inline = function(tokens, index) {
    return renderMath(tokens[index].content, false);
  };

  md.block.ruler.before('fence', 'columns', function(state, startLine, endLine, silent) {
    var start = state.bMarks[startLine] + state.tShift[startLine];
    var marker = state.src.slice(start, state.eMarks[startLine]).trim();
    if (marker !== '::: columns') return false;
    var nextLine = startLine + 1;
    var columns = [];
    var current = null;
    var closed = false;
    var fence = null;
    while (nextLine < endLine) {
      var line = state.src.slice(state.bMarks[nextLine], state.eMarks[nextLine]);
      var trimmed = line.trim();
      var fenceMatch = trimmed.match(/^(`{3,}|~{3,})/);
      if (fence) {
        if (current) current.push(line);
        if (fenceMatch && fenceMatch[1].charAt(0) === fence.marker && fenceMatch[1].length >= fence.length &&
            trimmed.slice(fenceMatch[0].length).trim() === '') fence = null;
        nextLine++;
        continue;
      }
      if (fenceMatch) {
        if (!current) return false;
        current.push(line);
        fence = { marker: fenceMatch[1].charAt(0), length: fenceMatch[1].length };
        nextLine++;
        continue;
      }
      if (trimmed === ':::') {
        if (current) {
          columns.push(current.join('\n'));
          current = null;
          nextLine++;
          continue;
        } else {
          closed = true;
          nextLine++;
          break;
        }
      }
      if (trimmed === '::: column') {
        if (current) return false;
        current = [];
      } else if (current) {
        current.push(line);
      } else if (trimmed) {
        return false;
      }
      nextLine++;
    }
    if (!closed || current || columns.length < 2 || columns.length > 4 || columns.some(function(column) { return !column.trim(); })) return false;
    if (silent) return true;
    state.line = nextLine;
    var token = state.push('columns', 'div', 0);
    token.block = true;
    token.meta = { columns: columns };
    return true;
  }, { alt: ['paragraph', 'reference', 'blockquote', 'list'] });
  md.renderer.rules.columns = function(tokens, index) {
    var columns = tokens[index].meta.columns;
    return '<div class="columns-layout" style="--column-count:' + columns.length + '">' + columns.map(function(column) {
      return '<section class="column-layout">' + md.render(column) + '</section>';
    }).join('') + '</div>\n';
  };

  md.renderer.rules.heading_open = function(tokens, index, rendererOptions, env, self) {
    var token = tokens[index];
    if (!settings.toc) return self.renderToken(tokens, index, rendererOptions);
    var inlineToken = tokens[index + 1];
    var id = uniqueSlug(inlineToken ? inlineToken.content : token.tag);
    token.attrSet('id', id);
    headingEntries.push({ id: id, level: Number(token.tag.slice(1)) || 1 });
    return self.renderToken(tokens, index, rendererOptions);
  };

  var defaultFence = md.renderer.rules.fence.bind(md.renderer.rules);
  md.renderer.rules.fence = function(tokens, index, rendererOptions, env, self) {
    var token = tokens[index];
    var info = (token.info || '').trim().toLowerCase();
    var infoMatch = info.match(/^(mermaid|markmap|mindmap|echarts)(?:\s+size=(\d+)x(\d+))?$/);
    var content = token.content;

    // 构建期判定为不可渲染的图表 fence：按普通代码块输出，并带上原因，
    // 由 enhanceCodeBlocks 在表头加警示标识与悬浮提示。
    var degradedEntry = degradedFences && degradedFences[token.map ? token.map[0] + 1 : 0];
    if (degradedEntry) {
      var degradedHtml = defaultFence(tokens, index, rendererOptions, env, self);
      var codeAt = degradedHtml.indexOf('<code');
      if (codeAt === -1) return degradedHtml;
      var language = degradedEntry.language || info.split(/\s+/)[0] || 'text';
      var degradedAttributes = ' data-visual-error="' + escapeHtml(degradedEntry.message) +
        '" data-visual-language="' + escapeHtml(language) + '"';
      return degradedHtml.slice(0, codeAt + 5) + degradedAttributes + degradedHtml.slice(codeAt + 5);
    }

    if (infoMatch && infoMatch[1] === 'mermaid') {
      var mermaidId = 'mermaid-' + mermaidBlocks.length;
      mermaidBlocks.push({
        id: mermaidId, label: 'Mermaid 图表', language: 'mermaid', source: content,
        dimensions: infoMatch[2] ? { width: Number(infoMatch[2]), height: Number(infoMatch[3]) } : null
      });
      return '<div class="visual-box mermaid-box" id="' + mermaidId + '"></div>\n';
    }

    if (infoMatch && (infoMatch[1] === 'markmap' || infoMatch[1] === 'mindmap')) {
      var markmapId = 'markmap-' + markmapBlocks.length;
      markmapBlocks.push({
        id: markmapId, label: '思维导图', language: 'markmap', source: content,
        dimensions: infoMatch[2] ? { width: Number(infoMatch[2]), height: Number(infoMatch[3]) } : null
      });
      return '<div class="visual-box markmap-box" id="' + markmapId + '"></div>\n';
    }

    if (infoMatch && infoMatch[1] === 'echarts') {
      var blockIndex = staticBlockQueue.findIndex(function(candidate) {
        return candidate.kind === 'echarts' && candidate.source === content;
      });
      if (blockIndex < 0) return '<div class="callout callout-err">图表预渲染结果缺失。</div>\n';
      var block = staticBlockQueue.splice(blockIndex, 1)[0];
      return '<div class="visual-box static-chart" id="' + block.id + '"></div>\n';
    }

    return defaultFence(tokens, index, rendererOptions, env, self);
  };

  container.innerHTML = md.render(raw);

  function decorateHeadings() {
    if (!settings.toc) return;
    headingEntries.forEach(function(entry) {
      var heading = document.getElementById(entry.id);
      if (!heading) return;
      entry.title = heading.textContent.trim();
      var anchor = document.createElement('a');
      anchor.className = 'heading-anchor';
      anchor.href = '#' + entry.id;
      anchor.textContent = '#';
      anchor.title = '链接到此标题';
      anchor.setAttribute('aria-label', '链接到 ' + entry.title);
      heading.insertBefore(anchor, heading.firstChild);
    });
  }

  function buildToc() {
    if (!settings.toc || !tocContent || !tocToggle) return;
    tocContent.innerHTML = '';
    if (!headingEntries.length) {
      tocToggle.hidden = true;
      setTocOpen(false, true);
      return;
    }
    var minimumLevel = headingEntries.reduce(function(level, entry) {
      return Math.min(level, entry.level);
    }, 6);
    headingEntries.forEach(function(entry) {
      var link = document.createElement('a');
      link.className = 'toc-link';
      link.href = '#' + entry.id;
      link.textContent = entry.title || entry.id;
      link.style.paddingLeft = Math.max(0, entry.level - minimumLevel) * 0.85 + 'rem';
      link.addEventListener('click', function() {
        if (isFloatingToc()) setTocOpen(false);
      });
      entry.link = link;
      tocContent.appendChild(link);
    });
  }

  var tocSpyActiveLink = null;

  function setTocSpyActive(link) {
    if (tocSpyActiveLink === link) return;
    if (tocSpyActiveLink) tocSpyActiveLink.classList.remove('is-active');
    tocSpyActiveLink = link || null;
    if (tocSpyActiveLink) tocSpyActiveLink.classList.add('is-active');
  }

  function setupTocSpy() {
    if (!settings.toc || !tocContent || !headingEntries.length) return;
    if (!('IntersectionObserver' in window)) return;
    var observed = [];
    headingEntries.forEach(function(entry) {
      var heading = document.getElementById(entry.id);
      if (!heading) return;
      entry.spyVisible = false;
      entry.element = heading;
      observed.push(entry);
    });
    if (!observed.length) return;
    // Map 直接定位条目，避免回调里对 observed 做 O(n²) 线性查找
    var entryByElement = new Map();
    observed.forEach(function(entry) { entryByElement.set(entry.element, entry); });
    var pickCurrent = function() {
      for (var index = 0; index < observed.length; index++) {
        if (observed[index].spyVisible) return observed[index];
      }
      return null;
    };
    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(change) {
        var entry = entryByElement.get(change.target);
        if (entry) entry.spyVisible = change.isIntersecting;
      });
      var current = pickCurrent();
      if (current && current.link) setTocSpyActive(current.link);
    }, { rootMargin: '-72px 0px -68% 0px', threshold: 0 });
    observed.forEach(function(entry) { observer.observe(entry.element); });
    var initial = observed[0];
    if (initial && initial.link) setTocSpyActive(initial.link);
  }

  function enhanceCodeBlocks() {
    container.querySelectorAll('pre > code').forEach(function(code) {
      var pre = code.parentElement;
      if (!pre || pre.closest('.visual-source') || pre.parentElement.classList.contains('code-block')) return;
      var wrapper = document.createElement('section');
      wrapper.className = 'code-block';
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);

      var toolbar = document.createElement('div');
      toolbar.className = 'code-toolbar';
      var visualError = code.getAttribute('data-visual-error');
      if (visualError) {
        // 图表降级为代码块：表头加警示标识，悬浮显示构建期记录的原因。
        var badge = document.createElement('span');
        badge.className = 'code-chart-badge';
        badge.innerHTML = iconSvg('warning') + '<span>图表</span>';
        badge.title = visualError;
        badge.setAttribute('aria-label', '图表未渲染，已按代码块展示：' + visualError);
        toolbar.appendChild(badge);
      }
      if (settings.codeTools) {
        var label = document.createElement('span');
        label.className = 'code-language';
        var visualLanguage = code.getAttribute('data-visual-language');
        var languageMatch = code.className.match(/(?:^|\s)language-([^\s]+)/);
        label.textContent = visualLanguage || (languageMatch ? languageMatch[1] : 'text');
        toolbar.appendChild(label);
        var copy = addIconButton(toolbar, 'copy', '复制代码', function() {
          copyText(code.textContent).then(function() {
            flashIconButton(copy, 'check', '已复制', 'copy', '复制代码');
          }).catch(function() {
            flashIconButton(copy, 'copy', '复制失败', 'copy', '复制代码');
          });
        }, 'code-copy');
      }
      var toggle = addIconButton(toolbar, settings.codeCollapse ? 'expand' : 'collapse', settings.codeCollapse ? '展开代码块' : '收起代码块', function() {
        setCodeCollapsed(wrapper, toggle, !wrapper.classList.contains('is-collapsed'));
      }, 'code-collapse');
      setCodeCollapsed(wrapper, toggle, settings.codeCollapse);
      wrapper.insertBefore(toolbar, pre);
    });
  }

  function setCodeCollapsed(wrapper, toggle, collapsed) {
    wrapper.classList.toggle('is-collapsed', collapsed);
    setIconButton(toggle, collapsed ? 'expand' : 'collapse', collapsed ? '展开代码块' : '收起代码块');
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }

  function copyText(text) {
    if (window.navigator.clipboard && window.isSecureContext) {
      return window.navigator.clipboard.writeText(text);
    }
    return new Promise(function(resolve, reject) {
      var textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      try {
        if (document.execCommand('copy')) resolve();
        else reject(new Error('浏览器拒绝复制操作。'));
      } catch (error) {
        reject(error);
      } finally {
        textarea.remove();
      }
    });
  }

  function flashButton(button, text) {
    var original = button.textContent;
    button.textContent = text;
    button.disabled = true;
    window.setTimeout(function() {
      button.textContent = original;
      button.disabled = false;
    }, 1200);
  }

  function flashIconButton(button, icon, label, restoreIcon, restoreLabel) {
    setIconButton(button, icon, label);
    button.disabled = true;
    window.setTimeout(function() {
      setIconButton(button, restoreIcon, restoreLabel);
      button.disabled = false;
    }, 1200);
  }

  function adjustMathOverflow() {
    // 分三阶段批量处理，避免「写-读-写」交替对每个公式强制同步布局
    var maths = container.querySelectorAll('.math-display');
    maths.forEach(function(math) { math.classList.remove('math-overflow'); });
    var overflowed = [];
    maths.forEach(function(math) {
      if (math.scrollWidth > math.clientWidth + 1) overflowed.push(math);
    });
    overflowed.forEach(function(math) { math.classList.add('math-overflow'); });
  }

  function setVisualMode(shell, sourceMode) {
    shell.element.classList.toggle('show-source', sourceMode);
    if (shell.previewButton) shell.previewButton.classList.toggle('is-active', !sourceMode);
    if (shell.sourceButton) shell.sourceButton.classList.toggle('is-active', sourceMode);
    if (!sourceMode && shell.onResize) window.requestAnimationFrame(shell.onResize);
    if (!sourceMode && shell.onReveal) window.requestAnimationFrame(shell.onReveal);
  }

  function relayoutAllVisualsForMaximize() {
    allVisualShells.forEach(function(shell) {
      if (!shell || !shell.stage) return;
      captureVisualViewport(shell);
      if (shell.onResize) window.requestAnimationFrame(shell.onResize);
      else if (shell.element._mermaidShell) window.requestAnimationFrame(function() { fitMermaidDiagram(shell.element._mermaidShell); });
    });
  }

  function setVisualMaximized(shell, maximized) {
    maximized = !!maximized;
    if (shell.maximized === maximized) return;
    shell.maximized = maximized;
    shell.element.classList.toggle('is-maximized', maximized);
    document.body.classList.toggle('visual-maximized-open', maximized);
    updateVisualMaximizeButton(shell);
    if (maximized) {
      window.requestAnimationFrame(function() {
        relayoutAllVisualsForMaximize();
      });
    } else {
      window.requestAnimationFrame(relayoutAllVisualsForMaximize);
    }
  }

  function updateVisualMaximizeButton(shell) {
    if (!shell.maximizeButton) return;
    if (shell.maximized) {
      setIconButton(shell.maximizeButton, 'minimize', '最小化图表');
      shell.maximizeButton.classList.add('is-active');
    } else {
      setIconButton(shell.maximizeButton, 'maximize', '最大化图表');
      shell.maximizeButton.classList.remove('is-active');
    }
  }

  function normalizeVisualZoom(zoom) {
    var value = Number(zoom);
    if (!isFinite(value)) value = 1;
    return Math.max(0.01, Math.min(10, Math.round(value * 100) / 100));
  }

  function visualZoomFor(shell) {
    if (shell.zoomType === 'mermaid') return shell.mermaidZoom;
    if (shell.zoomType === 'markmap') return shell.markmapZoom;
    return shell.staticZoom;
  }

  function updateVisualZoomControl(shell) {
    var zoom = normalizeVisualZoom(visualZoomFor(shell));
    var percent = Math.round(zoom * 100);
    if (shell.zoomInput) shell.zoomInput.value = String(percent);
    shell.zoomButtons.forEach(function(button, index) {
      button.disabled = index === 0 ? percent <= 1 : percent >= 1000;
    });
  }

  function setVisualZoom(shell, zoom) {
    if (shell.zoomType === 'mermaid') setMermaidZoom(shell, zoom);
    else if (shell.zoomType === 'markmap') setMarkmapZoom(shell, zoom);
    else setStaticZoom(shell, zoom);
  }

  function addVisualZoomControl(parent, shell) {
    var group = document.createElement('div');
    group.className = 'visual-zoom';
    var decrease = addButton(group, '-', '缩小图表', function() {
      setVisualZoom(shell, visualZoomFor(shell) - 0.1);
    }, 'visual-btn zoom-btn');
    var input = document.createElement('input');
    input.type = 'number';
    input.className = 'visual-zoom-input';
    input.min = '1';
    input.max = '1000';
    input.step = '1';
    input.value = '100';
    input.title = '图表缩放比例，范围 1% 到 1000%';
    input.setAttribute('aria-label', input.title);
    var applyInput = function() { setVisualZoom(shell, Number(input.value) / 100); };
    input.addEventListener('change', applyInput);
    input.addEventListener('blur', applyInput);
    input.addEventListener('keydown', function(event) {
      if (event.key === 'Enter') {
        applyInput();
        input.blur();
      }
    });
    group.appendChild(input);
    var unit = document.createElement('span');
    unit.className = 'visual-zoom-unit';
    unit.textContent = '%';
    unit.setAttribute('aria-hidden', 'true');
    group.appendChild(unit);
    var increase = addButton(group, '+', '放大图表', function() {
      setVisualZoom(shell, visualZoomFor(shell) + 0.1);
    }, 'visual-btn zoom-btn');
    parent.appendChild(group);
    shell.zoomButtons = [decrease, increase];
    shell.zoomInput = input;
    updateVisualZoomControl(shell);
  }

  function createVisualShell(element, definition) {
    element.innerHTML = '';
    var shell = {
      id: definition.id,
      element: element,
      stage: null,
      onResize: null,
      previewButton: null,
      sourceButton: null,
      exportButtons: [],
      zoomButtons: [],
      zoomInput: null,
      zoomType: definition.zoomType || 'static',
      staticZoom: definition.staticZoom || 1,
      staticImage: null,
      staticBaseWidth: 0,
      staticBaseHeight: 0,
      mermaidZoom: definition.mermaidZoom || 1,
      mermaidBaseWidth: 0,
      mermaidBaseHeight: 0,
      markmapZoom: definition.markmapZoom || 1,
      markmapBaseScale: 0,
      markmapAdjusting: false,
      viewportBaseWidth: 0,
      viewportBaseHeight: 0,
      visualCanvas: null,
      onReveal: null,
      maximized: false,
      maximizeButton: null,
      minimizeButton: null,
      dimensions: definition.dimensions || null,
      svgMarkup: definition.svgMarkup || ''
    };
    element.style.removeProperty('width');
    var dimensions = shell.dimensions || { width: visualDefaultMaxWidth, height: visualDefaultMaxHeight };
    element.style.setProperty('--visual-width', dimensions.width + 'px');
    element.style.setProperty('--visual-height', dimensions.height + 'px');
    var hasToolbar = settings.chartTools;
    if (hasToolbar) {
      var toolbar = document.createElement('div');
      toolbar.className = 'visual-toolbar';
      var label = document.createElement('span');
      label.className = 'visual-label';
      label.textContent = definition.label;
      toolbar.appendChild(label);
      var actions = document.createElement('div');
      actions.className = 'visual-actions';
      toolbar.appendChild(actions);

      if (settings.chartTools && settings.sourceToggle) {
        shell.previewButton = addButton(actions, '预览', '显示图表预览', function() { setVisualMode(shell, false); }, 'visual-btn mode-btn is-active');
        shell.sourceButton = addButton(actions, '源码', '显示图表源码', function() { setVisualMode(shell, true); }, 'visual-btn mode-btn');
      }
      if (settings.chartTools && settings.chartExport) {
        shell.exportButtons.push(addButton(actions, 'SVG', '导出 SVG', function(event) {
          downloadSvgFromShell(shell, definition.id, event.currentTarget);
        }, 'visual-btn'));
        shell.exportButtons.push(addButton(actions, 'PNG', '导出 PNG', function(event) {
          downloadPngFromShell(shell, definition.id, event.currentTarget);
        }, 'visual-btn'));
      }
      if (settings.chartTools && definition.zoomable) {
        addVisualZoomControl(actions, shell);
      }
      if (settings.chartTools && settings.chartMaximize) {
        shell.maximizeButton = addIconButton(actions, 'maximize', '最大化图表', function() {
          setVisualMaximized(shell, !shell.maximized);
        }, 'visual-btn visual-maximize-btn');
      }
      element.appendChild(toolbar);
    }

    var stage = document.createElement('div');
    stage.className = 'visual-stage' + (definition.fitContent ? ' visual-stage-fit' : '');
    if (shell.dimensions) {
      stage.classList.add('visual-stage-explicit');
      stage.style.aspectRatio = shell.dimensions.width + ' / ' + shell.dimensions.height;
    }
    stage.setAttribute('aria-label', definition.label + '预览');
    element.appendChild(stage);
    shell.stage = stage;

    if (settings.chartTools && settings.sourceToggle) {
      var source = document.createElement('pre');
      source.className = 'visual-source';
      source.setAttribute('aria-label', definition.label + '源码');
      var code = document.createElement('code');
      code.className = 'language-' + (definition.language || 'text');
      code.textContent = definition.source || '';
      source.appendChild(code);
      element.appendChild(source);
    }
    element._visualShell = shell;
    if (allVisualShells.indexOf(shell) === -1) allVisualShells.push(shell);
    return shell;
  }

  function showVisualError(shell, message) {
    shell.svgMarkup = '';
    shell.exportButtons.concat(shell.zoomButtons).concat(shell.zoomInput ? [shell.zoomInput] : []).forEach(function(button) {
      button.disabled = true;
      button.title = '图表渲染失败，无法导出。';
    });
    shell.stage.innerHTML = '';
    var error = document.createElement('div');
    error.className = 'callout callout-err';
    error.textContent = message;
    shell.stage.appendChild(error);
  }

  function isUsableSvg(svg) {
    return !!svg && svg.tagName && svg.tagName.toLowerCase() === 'svg' && !!svg.querySelector('*');
  }

  function getShellSvg(shell) {
    var svg = shell.stage.querySelector('svg');
    if (!isUsableSvg(svg)) throw new Error('当前图表没有可导出的 SVG。');
    return svg;
  }

  function getExportPayload(shell) {
    if (shell.svgMarkup) return { markup: shell.svgMarkup, svg: null };
    var svg = getShellSvg(shell);
    return { markup: serializeSvg(svg, shell), svg: null };
  }

  function serializeSvg(svg, shell) {
    var clone = svg.cloneNode(true);
    ['display', 'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height', 'flex-shrink'].forEach(function(property) {
      clone.style.removeProperty(property);
    });
    if (!clone.getAttribute('style')) clone.removeAttribute('style');
    if (shell && shell.zoomType === 'markmap' && shell.element._markmap) {
      var map = shell.element._markmap;
      var state = map.state;
      if (state && isFinite(state.minX) && isFinite(state.maxX) && isFinite(state.minY) && isFinite(state.maxY)) {
        var padding = 24;
        clone.setAttribute('viewBox', [state.minY - padding, state.minX - padding, state.maxY - state.minY + padding * 2, state.maxX - state.minX + padding * 2].join(' '));
        clone.setAttribute('preserveAspectRatio', 'xMidYMid meet');
        var group = clone.querySelector('g');
        if (group) group.removeAttribute('transform');
      }
    }
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(clone);
  }

  function safeExportName(id, extension) {
    var base = String(id || 'diagram').replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '') || 'diagram';
    return base + '.' + extension;
  }

  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
  }

  function downloadSourceMarkdown() {
    downloadBlob(new Blob([sourceMarkdown], { type: 'text/markdown;charset=utf-8' }), sourceDownloadName);
  }

  function downloadSvgFromShell(shell, id, button) {
    try {
      var payload = getExportPayload(shell);
      downloadBlob(new Blob([payload.markup], { type: 'image/svg+xml;charset=utf-8' }), safeExportName(id, 'svg'));
      flashButton(button, '已导出');
    } catch (error) {
      flashButton(button, '导出失败');
    }
  }

  function svgSize(svg, markup) {
    var viewBoxAttribute = svg ? svg.getAttribute('viewBox') : (String(markup).match(/\bviewBox\s*=\s*["']([^"']+)["']/i) || ['', ''])[1];
    var widthAttribute = svg ? svg.getAttribute('width') : (String(markup).match(/\bwidth\s*=\s*["']([^"']+)["']/i) || ['', ''])[1];
    var heightAttribute = svg ? svg.getAttribute('height') : (String(markup).match(/\bheight\s*=\s*["']([^"']+)["']/i) || ['', ''])[1];
    var viewBox = (viewBoxAttribute || '').trim().split(/[ ,]+/).map(Number);
    var width = /%|auto/i.test(widthAttribute) ? 0 : Number.parseFloat(widthAttribute);
    var height = /%|auto/i.test(heightAttribute) ? 0 : Number.parseFloat(heightAttribute);
    if (viewBox.length === 4 && viewBox[2] > 0 && viewBox[3] > 0) {
      width = viewBox[2];
      height = viewBox[3];
    }
    if (!width || !height) {
      var bounds = svg ? svg.getBoundingClientRect() : { width: 0, height: 0 };
      width = width || bounds.width || 1200;
      height = height || bounds.height || 720;
    }
    return { width: Math.max(1, width), height: Math.max(1, height) };
  }

  function downloadPngFromShell(shell, id, button) {
    var objectUrl = '';
    try {
      var payload = getExportPayload(shell);
      objectUrl = URL.createObjectURL(new Blob([payload.markup], { type: 'image/svg+xml;charset=utf-8' }));
      var image = new Image();
      image.onload = function() {
        try {
          var size = svgSize(payload.svg, payload.markup);
          var scale = Math.min(2, 4096 / Math.max(size.width, size.height));
          var canvas = document.createElement('canvas');
          canvas.width = Math.max(1, Math.round(size.width * scale));
          canvas.height = Math.max(1, Math.round(size.height * scale));
          var context = canvas.getContext('2d');
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          var finish = function(blob) {
            if (!blob) {
              flashButton(button, '导出失败');
              return;
            }
            downloadBlob(blob, safeExportName(id, 'png'));
            flashButton(button, '已导出');
          };
          if (canvas.toBlob) canvas.toBlob(finish, 'image/png');
          else finish(dataUrlToBlob(canvas.toDataURL('image/png')));
        } catch (error) {
          flashButton(button, '导出失败');
        } finally {
          URL.revokeObjectURL(objectUrl);
        }
      };
      image.onerror = function() {
        URL.revokeObjectURL(objectUrl);
        flashButton(button, '导出失败');
      };
      image.src = objectUrl;
    } catch (error) {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      flashButton(button, '导出失败');
    }
  }

  function dataUrlToBlob(dataUrl) {
    var parts = dataUrl.split(',');
    var binary = window.atob(parts[1]);
    var bytes = new Uint8Array(binary.length);
    for (var index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
    return new Blob([bytes], { type: 'image/png' });
  }

  function staticSvgForTheme(block) {
    return effectiveTheme === 'dark' && block.darkSvg ? block.darkSvg : block.svg;
  }

  function resetVisualViewport(shell) {
    shell.element.style.removeProperty('width');
    shell.stage.style.removeProperty('height');
    shell.element.classList.remove('is-visual-contained');
    if (shell.visualCanvas) {
      shell.visualCanvas.style.removeProperty('width');
      shell.visualCanvas.style.removeProperty('height');
    }
  }

  function captureVisualViewport(shell) {
    var elementBounds = shell.element.getBoundingClientRect();
    var stageBounds = shell.stage.getBoundingClientRect();
    shell.viewportBaseWidth = Math.max(1, elementBounds.width || shell.stage.clientWidth || visualDimensionsFor(shell).width);
    shell.viewportBaseHeight = Math.max(1, stageBounds.height || shell.stage.clientHeight || visualDimensionsFor(shell).height);
  }

  function centerVisualViewport(shell) {
    if (!shell || !shell.stage) return;
    shell.stage.scrollLeft = Math.max(0, (shell.stage.scrollWidth - shell.stage.clientWidth) / 2);
    shell.stage.scrollTop = Math.max(0, (shell.stage.scrollHeight - shell.stage.clientHeight) / 2);
  }

  function prepareVisualViewportForPrint(shell) {
    if (!shell || !shell.stage || Object.prototype.hasOwnProperty.call(shell.element, '_printScroll')) return;
    shell.element._printScroll = {
      left: shell.stage.scrollLeft,
      top: shell.stage.scrollTop
    };
    shell.stage.scrollLeft = 0;
    shell.stage.scrollTop = 0;
  }

  function restoreVisualViewportAfterPrint(shell) {
    if (!shell || !shell.stage || !Object.prototype.hasOwnProperty.call(shell.element, '_printScroll')) return;
    var saved = shell.element._printScroll;
    delete shell.element._printScroll;
    window.requestAnimationFrame(function() {
      shell.stage.scrollLeft = saved.left;
      shell.stage.scrollTop = saved.top;
    });
  }

  function layoutVisualViewport(shell, contentWidth, contentHeight, zoom) {
    var canvas = shell.visualCanvas;
    if (!shell.stage || !shell.viewportBaseWidth || !shell.viewportBaseHeight) return;
    var next = normalizeVisualZoom(zoom);
    var parent = shell.element.parentElement;
    var parentWidth = shell.viewportBaseWidth;
    if (parent) {
      var parentStyle = getComputedStyle(parent);
      var parentPadding = (Number.parseFloat(parentStyle.paddingLeft) || 0) + (Number.parseFloat(parentStyle.paddingRight) || 0);
      parentWidth = Math.max(1, parent.clientWidth - parentPadding);
    }
    var pageWidth = Math.max(shell.viewportBaseWidth, parentWidth || shell.viewportBaseWidth);
    var pageHeight = Math.max(shell.viewportBaseHeight, Math.min(760, Math.round((window.innerHeight || visualDimensionsFor(shell).height) * 0.7)));
    var viewportWidth = Math.max(1, Math.round(Math.min(shell.viewportBaseWidth * next, pageWidth)));
    var viewportHeight = Math.max(1, Math.round(Math.min(shell.viewportBaseHeight * next, pageHeight)));
    if (!shell.maximized) {
      shell.element.style.width = viewportWidth + 'px';
      shell.stage.style.setProperty('height', viewportHeight + 'px', 'important');
    }
    var contained = contentWidth > viewportWidth + 1 || contentHeight > viewportHeight + 1;
    shell.element.classList.toggle('is-visual-contained', contained);
    if (canvas && contentWidth > 0 && contentHeight > 0) {
      var stageStyle = getComputedStyle(shell.stage);
      var horizontalPadding = (Number.parseFloat(stageStyle.paddingLeft) || 0) + (Number.parseFloat(stageStyle.paddingRight) || 0);
      var verticalPadding = (Number.parseFloat(stageStyle.paddingTop) || 0) + (Number.parseFloat(stageStyle.paddingBottom) || 0);
      var innerWidth = Math.max(1, shell.stage.clientWidth - horizontalPadding);
      var innerHeight = Math.max(1, shell.stage.clientHeight - verticalPadding);
      canvas.style.width = Math.max(innerWidth, Math.round(contentWidth)) + 'px';
      canvas.style.height = Math.max(innerHeight, Math.round(contentHeight)) + 'px';
    }
    if (document.documentElement.getAttribute('data-printing') !== 'true') {
      centerVisualViewport(shell);
      window.requestAnimationFrame(function() {
        if (document.documentElement.getAttribute('data-printing') !== 'true') centerVisualViewport(shell);
      });
    }
  }

  function setStaticZoom(shell, zoom) {
    var next = normalizeVisualZoom(zoom);
    shell.staticZoom = next;
    visualZoomState[shell.id] = next;
    shell.element.classList.toggle('is-static-zoomed', next > 1);
    shell.element.classList.toggle('is-visual-zoomed', next > 1);
    if (shell.staticImage) {
      if (shell.staticBaseWidth) {
        shell.staticImage.style.width = Math.round(shell.staticBaseWidth * next) + 'px';
        shell.staticImage.style.height = 'auto';
        shell.staticImage.style.maxWidth = next > 1 ? 'none' : '100%';
        shell.staticImage.style.maxHeight = next > 1 ? 'none' : '100%';
        layoutVisualViewport(shell, shell.staticBaseWidth * next, shell.staticBaseHeight * next, next);
      } else {
        shell.staticImage.style.width = '';
        shell.staticImage.style.height = '';
        shell.staticImage.style.maxWidth = '';
        shell.staticImage.style.maxHeight = '';
        layoutVisualViewport(shell, 0, 0, next);
      }
    }
    updateVisualZoomControl(shell);
  }

  function setMermaidZoom(shell, zoom) {
    var next = normalizeVisualZoom(zoom);
    shell.mermaidZoom = next;
    visualZoomState[shell.id] = next;
    shell.element.classList.toggle('is-mermaid-zoomed', next > 1);
    shell.element.classList.toggle('is-visual-zoomed', next > 1);
    var svg = shell.stage.querySelector('svg');
    if (svg && shell.mermaidBaseWidth) {
      svg.style.display = 'block';
      svg.style.width = Math.round(shell.mermaidBaseWidth * next) + 'px';
      svg.style.height = 'auto';
      svg.style.maxWidth = next > 1 ? 'none' : '100%';
      svg.style.maxHeight = next > 1 ? 'none' : '100%';
      svg.style.minWidth = '0';
      svg.style.flexShrink = next > 1 ? '0' : '';
      layoutVisualViewport(shell, shell.mermaidBaseWidth * next, shell.mermaidBaseHeight * next, next);
    }
    updateVisualZoomControl(shell);
  }

  function setMarkmapZoom(shell, zoom) {
    var previous = normalizeVisualZoom(shell.markmapZoom);
    var next = normalizeVisualZoom(zoom);
    shell.markmapZoom = next;
    visualZoomState[shell.id] = next;
    shell.element.classList.toggle('is-markmap-zoomed', next > 1);
    shell.element.classList.toggle('is-visual-zoomed', next > 1);
    layoutVisualViewport(shell, shell.viewportBaseWidth * next, shell.viewportBaseHeight * next, next);
    var map = shell.element._markmap;
    if (map && map.rescale && previous !== next) {
      shell.markmapAdjusting = true;
      Promise.resolve(map.rescale(next / previous)).then(function() {
        shell.markmapAdjusting = false;
        updateVisualZoomControl(shell);
      });
    }
    updateVisualZoomControl(shell);
  }

  function visualDimensionsFor(shell) {
    return shell && shell.dimensions ? shell.dimensions : {
      width: visualDefaultMaxWidth,
      height: visualDefaultMaxHeight
    };
  }

  function fitVisualSize(stage, width, height, shell) {
    var limits = visualDimensionsFor(shell);
    var safeWidth = Number(width) || limits.width;
    var safeHeight = Number(height) || limits.height;
    var stageStyle = getComputedStyle(stage);
    var horizontalPadding = (Number.parseFloat(stageStyle.paddingLeft) || 0) + (Number.parseFloat(stageStyle.paddingRight) || 0);
    var verticalPadding = (Number.parseFloat(stageStyle.paddingTop) || 0) + (Number.parseFloat(stageStyle.paddingBottom) || 0);
    var availableWidth = stage.clientWidth - horizontalPadding;
    var availableHeight = shell && shell.dimensions ? stage.clientHeight - verticalPadding : 0;
    if (!availableWidth || !isFinite(availableWidth)) availableWidth = limits.width;
    var printing = document.documentElement.getAttribute('data-printing') === 'true';
    var scale;
    if (shell && shell.dimensions) {
      if (!availableHeight || !isFinite(availableHeight)) availableHeight = limits.height;
      var contentScale = Math.min(1, limits.width / safeWidth, limits.height / safeHeight);
      var viewportScale = Math.min(1, availableWidth / limits.width, availableHeight / limits.height);
      scale = contentScale * viewportScale;
    } else if (printing) {
      scale = Math.min(1, availableWidth / safeWidth);
    } else {
      scale = Math.min(1, availableWidth / safeWidth, limits.width / safeWidth, limits.height / safeHeight);
    }
    return {
      width: Math.max(1, Math.round(safeWidth * scale)),
      height: Math.max(1, Math.round(safeHeight * scale))
    };
  }

  function markmapFitScale(shell, map) {
    if (!shell.dimensions || !map || !map.state) return 1;
    var state = map.state;
    var naturalWidth = Math.max(1, state.maxY - state.minY);
    var naturalHeight = Math.max(1, state.maxX - state.minX);
    var stageWidth = shell.stage.clientWidth || shell.dimensions.width;
    var stageHeight = shell.stage.clientHeight || shell.dimensions.height;
    var contentScale = Math.min(1, shell.dimensions.width / naturalWidth * 0.9, shell.dimensions.height / naturalHeight * 0.9);
    var viewportScale = Math.min(1, stageWidth / shell.dimensions.width, stageHeight / shell.dimensions.height);
    return Math.max(0.0001, contentScale * viewportScale);
  }

  function measureStaticImage(shell) {
    if (!shell.staticImage) return;
    resetVisualViewport(shell);
    var image = shell.staticImage;
    var fallback = svgSize(null, shell.svgMarkup);
    var naturalWidth = image.naturalWidth || fallback.width;
    var naturalHeight = image.naturalHeight || fallback.height;
    var fitted = fitVisualSize(shell.stage, naturalWidth, naturalHeight, shell);
    shell.staticBaseWidth = fitted.width;
    shell.staticBaseHeight = fitted.height;
    image.style.width = Math.round(fitted.width) + 'px';
    image.style.height = 'auto';
    image.style.maxWidth = '100%';
    image.style.maxHeight = '100%';
    captureVisualViewport(shell);
    setStaticZoom(shell, shell.staticZoom);
  }

  function setStaticPreview(shell, block) {
    var markup = staticSvgForTheme(block);
    shell.svgMarkup = markup;
    var image = shell.stage.querySelector('img.static-svg-image');
    if (image) {
      shell.staticBaseWidth = 0;
      shell.staticBaseHeight = 0;
      setStaticZoom(shell, shell.staticZoom);
      image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(markup);
      measureStaticImage(shell);
    }
  }

  function renderStaticCharts() {
    var errors = [];
    Object.keys(staticBlocks).forEach(function(id) {
      var block = staticBlocks[id];
      var element = document.getElementById(block.id);
      if (!element) return;
      element.classList.add('echarts-chart');
      var shell = createVisualShell(element, {
        id: block.id,
        label: block.label,
        language: block.language,
        source: block.source,
        svgMarkup: staticSvgForTheme(block),
        dimensions: block.dimensions,
        fitContent: true,
        zoomable: true
      });
      if (block.error) {
        showVisualError(shell, block.error);
        errors.push({ label: block.label, message: block.error });
        return;
      }
      element._staticShell = shell;
      var canvas = document.createElement('div');
      canvas.className = 'visual-canvas';
      shell.stage.appendChild(canvas);
      shell.visualCanvas = canvas;
      var image = document.createElement('img');
      image.className = 'static-svg-image';
      image.alt = block.label;
      image.addEventListener('load', function() {
        measureStaticImage(shell);
      });
      image.addEventListener('error', function() {
        var message = '静态 SVG 无法由当前浏览器显示。';
        showVisualError(shell, message);
        recordStaticRenderError(block.label, message);
        setRenderStatus(false);
      });
      canvas.appendChild(image);
      shell.staticImage = image;
      shell.onReveal = function() { measureStaticImage(shell); };
      setStaticZoom(shell, shell.staticZoom);
      setStaticPreview(shell, block);
    });
    return errors;
  }

  function refreshStaticCharts() {
    Object.keys(staticBlocks).forEach(function(id) {
      var block = staticBlocks[id];
      if (block.error) return;
      var element = document.getElementById(block.id);
      if (element && element._staticShell) setStaticPreview(element._staticShell, block);
    });
  }

  function resizeStaticCharts() {
    if (document.documentElement.getAttribute('data-printing') === 'true') return;
    Object.keys(staticBlocks).forEach(function(id) {
      var element = document.getElementById(staticBlocks[id].id);
      if (element && element._staticShell) measureStaticImage(element._staticShell);
    });
  }

  function fitMermaidDiagram(shell) {
    var svg = shell.stage.querySelector('svg');
    if (!isUsableSvg(svg)) return;
    resetVisualViewport(shell);
    var size = svgSize(svg, '');
    var fitted = fitVisualSize(shell.stage, size.width, size.height, shell);
    svg.style.display = 'block';
    shell.mermaidBaseWidth = fitted.width;
    shell.mermaidBaseHeight = fitted.height;
    svg.style.width = Math.round(fitted.width) + 'px';
    svg.style.height = 'auto';
    svg.style.maxWidth = '100%';
    svg.style.maxHeight = '100%';
    captureVisualViewport(shell);
    setMermaidZoom(shell, shell.mermaidZoom);
  }

  function resizeMermaids() {
    if (document.documentElement.getAttribute('data-printing') === 'true') return;
    mermaidBlocks.forEach(function(block) {
      var element = document.getElementById(block.id);
      if (element && element._mermaidShell) fitMermaidDiagram(element._mermaidShell);
    });
  }

  function scheduleVisualResize() {
    if (visualResizeFrame) return;
    visualResizeFrame = window.requestAnimationFrame(function() {
      visualResizeFrame = 0;
      resizeStaticCharts();
      resizeMermaids();
      resizeMarkmaps();
      adjustMathOverflow();
    });
  }

  function renderMermaids(generation) {
    if (!mermaidBlocks.length) return Promise.resolve();
    if (!window.mermaid) {
      mermaidBlocks.forEach(function(block) {
        var element = document.getElementById(block.id);
        if (!element) return;
        var previousZoom = visualZoomState[block.id] || (element._mermaidShell ? element._mermaidShell.mermaidZoom : 1);
        element._mermaidShell = null;
        var shell = createVisualShell(element, {
          id: block.id, label: block.label, language: block.language, source: block.source, dimensions: block.dimensions,
          fitContent: true, zoomable: true, zoomType: 'mermaid', mermaidZoom: previousZoom
        });
        var message = 'Mermaid 引擎未加载。';
        showVisualError(shell, message);
        recordRenderError(block.label, message);
      });
      return Promise.resolve();
    }

    try {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: effectiveTheme === 'dark' ? 'dark' : 'default',
        securityLevel: settings.mermaidSecurity
      });
    } catch (error) {
      var initializationError = error.message || error;
      mermaidBlocks.forEach(function(block) {
        var element = document.getElementById(block.id);
        if (!element) return;
        var previousZoom = visualZoomState[block.id] || (element._mermaidShell ? element._mermaidShell.mermaidZoom : 1);
        element._mermaidShell = null;
        var shell = createVisualShell(element, {
          id: block.id, label: block.label, language: block.language, source: block.source, dimensions: block.dimensions,
          fitContent: true, zoomable: true, zoomType: 'mermaid', mermaidZoom: previousZoom
        });
        var message = 'Mermaid 初始化错误: ' + initializationError;
        showVisualError(shell, message);
        recordRenderError(block.label, message);
      });
      return Promise.resolve();
    }

    return Promise.all(mermaidBlocks.map(function(block, index) {
      var element = document.getElementById(block.id);
      if (!element) return Promise.resolve();
      var previousZoom = visualZoomState[block.id] || (element._mermaidShell ? element._mermaidShell.mermaidZoom : 1);
      element._mermaidShell = null;
      var shell = createVisualShell(element, {
        id: block.id, label: block.label, language: block.language, source: block.source, dimensions: block.dimensions,
        fitContent: true, zoomable: true, zoomType: 'mermaid', mermaidZoom: previousZoom
      });
      var diagram = document.createElement('div');
      diagram.className = 'diagram mermaid visual-canvas';
      shell.stage.appendChild(diagram);
      shell.visualCanvas = diagram;
      var renderId = 'mermaid-render-' + generation + '-' + index;
      return Promise.resolve(window.mermaid.render(renderId, block.source)).then(function(rendered) {
        if (generation !== renderGeneration) return;
        diagram.innerHTML = rendered.svg;
        if (!isUsableSvg(diagram.querySelector('svg'))) throw new Error('Mermaid 没有返回有效 SVG。');
        element._mermaidShell = shell;
        shell.onResize = function() { fitMermaidDiagram(shell); };
        shell.onReveal = shell.onResize;
        fitMermaidDiagram(shell);
      }).catch(function(error) {
        if (generation !== renderGeneration) return;
        var message = 'Mermaid 渲染错误: ' + (error.message || error);
        showVisualError(shell, message);
        recordRenderError(block.label, message);
      });
    }));
  }

  var markmapTransformer = null;

  function markmapColorsForTheme() {
    var colors = settings.markmapColors[effectiveTheme];
    return Array.isArray(colors) && colors.length ? colors : settings.markmapColors.light;
  }

  function renderMarkmapBlock(block, generation) {
    if (generation !== renderGeneration) return Promise.resolve();
    var element = document.getElementById(block.id);
    if (!element) return Promise.resolve();
    var previousZoom = visualZoomState[block.id] || (element._markmapShell ? element._markmapShell.markmapZoom : 1);
    if (element._visualResize) {
      element._visualResize = null;
    }
    if (element._markmap) element._markmap.destroy();
    var shell = createVisualShell(element, {
      id: block.id, label: block.label, language: block.language, source: block.source, dimensions: block.dimensions, zoomable: true, zoomType: 'markmap', markmapZoom: previousZoom
    });
    element._markmapShell = shell;
    try {
      var colors = markmapColorsForTheme();
      var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      shell.stage.appendChild(svg);
      captureVisualViewport(shell);
      var result = markmapTransformer.transform(block.source);
      var color = function(node) {
        var depth = node.state && node.state.depth != null ? node.state.depth : 0;
        return colors[depth % colors.length];
      };
      var map = window.markmap.Markmap.create(svg, { autoFit: false, color: color, duration: 0, fitRatio: 0.9 });
      element._markmap = map;
      if (map.zoom && map.zoom.on && window.d3 && window.d3.zoomTransform) {
        if (typeof map.zoom.filter === 'function') {
          map.zoom.filter(function(event) {
            return event && event.type !== 'wheel' && event.type !== 'mousewheel' && !(event.ctrlKey && event.type === 'wheel');
          });
        }
        map.zoom.on('zoom.aidocs', function(event) {
          if (shell.markmapAdjusting || !shell.markmapBaseScale) return;
          var transform = event && event.transform ? event.transform : window.d3.zoomTransform(svg);
          shell.markmapZoom = normalizeVisualZoom(transform.k / shell.markmapBaseScale);
          visualZoomState[shell.id] = shell.markmapZoom;
          layoutVisualViewport(shell, shell.viewportBaseWidth * shell.markmapZoom, shell.viewportBaseHeight * shell.markmapZoom, shell.markmapZoom);
          updateVisualZoomControl(shell);
        });
      }
      map.setData(result.root, { color: color });
      if (!isUsableSvg(svg)) throw new Error('Markmap 没有生成可用 SVG。');
      var fit = function() {
        if (document.documentElement.getAttribute('data-printing') === 'true') return Promise.resolve();
        var zoom = normalizeVisualZoom(shell.markmapZoom);
        shell.markmapAdjusting = true;
        return map.fit(markmapFitScale(shell, map)).then(function() {
          var transform = window.d3 && window.d3.zoomTransform ? window.d3.zoomTransform(svg) : null;
          shell.markmapBaseScale = transform && transform.k ? transform.k : 1;
          if (map.zoom && map.zoom.scaleExtent) map.zoom.scaleExtent([shell.markmapBaseScale * 0.01, shell.markmapBaseScale * 10]);
          if (zoom !== 1) return map.rescale(zoom);
        }).then(function() {
          shell.markmapZoom = zoom;
          shell.markmapAdjusting = false;
          layoutVisualViewport(shell, shell.viewportBaseWidth * zoom, shell.viewportBaseHeight * zoom, zoom);
          updateVisualZoomControl(shell);
        });
      };
      shell.onResize = function() { fit(); };
      element._visualResize = shell.onResize;
      return new Promise(function(resolve) {
        window.requestAnimationFrame(resolve);
      }).then(fit).catch(function(error) {
        if (generation !== renderGeneration) return;
        var message = '思维导图渲染错误: ' + (error.message || error);
        showVisualError(shell, message);
        recordRenderError(block.label, message);
      });
    } catch (error) {
      var message = '思维导图渲染错误: ' + (error.message || error);
      showVisualError(shell, message);
      recordRenderError(block.label, message);
      return Promise.resolve();
    }
  }

  function renderMarkmaps(generation) {
    if (!markmapBlocks.length || generation !== renderGeneration) return Promise.resolve();
    if (!window.markmap || !window.markmap.Markmap || !window.markmap.Transformer) {
      markmapBlocks.forEach(function(block) {
        var element = document.getElementById(block.id);
        if (!element) return;
        var previousZoom = visualZoomState[block.id] || (element._markmapShell ? element._markmapShell.markmapZoom : 1);
        var shell = createVisualShell(element, {
          id: block.id, label: block.label, language: block.language, source: block.source, dimensions: block.dimensions, zoomable: true, zoomType: 'markmap', markmapZoom: previousZoom
        });
        var message = 'Markmap 引擎未加载。';
        showVisualError(shell, message);
        recordRenderError(block.label, message);
      });
      return Promise.resolve();
    }
    try {
      markmapTransformer = new window.markmap.Transformer();
      return Promise.all(markmapBlocks.map(function(block) { return renderMarkmapBlock(block, generation); }));
    } catch (error) {
      markmapBlocks.forEach(function(block) {
        var element = document.getElementById(block.id);
        if (!element) return;
        var previousZoom = visualZoomState[block.id] || (element._markmapShell ? element._markmapShell.markmapZoom : 1);
        var shell = createVisualShell(element, {
          id: block.id, label: block.label, language: block.language, source: block.source, dimensions: block.dimensions, zoomable: true, zoomType: 'markmap', markmapZoom: previousZoom
        });
        var message = '思维导图初始化错误: ' + (error.message || error);
        showVisualError(shell, message);
        recordRenderError(block.label, message);
      });
      return Promise.resolve();
    }
  }

  function resizeMarkmaps() {
    if (document.documentElement.getAttribute('data-printing') === 'true') return;
    markmapBlocks.forEach(function(block) {
      var element = document.getElementById(block.id);
      if (element && element._visualResize) element._visualResize();
    });
  }

  function prepareVisualsForPrint() {
    if (document.documentElement.getAttribute('data-printing') === 'true') return;
    document.documentElement.setAttribute('data-printing', 'true');
    Object.keys(staticBlocks).forEach(function(id) {
      var element = document.getElementById(staticBlocks[id].id);
      var shell = element && element._staticShell;
      if (!shell) return;
      element._printZoom = shell.staticZoom;
      element._printBaseWidth = shell.staticBaseWidth;
      element._printBaseHeight = shell.staticBaseHeight;
      measureStaticImage(shell);
      setStaticZoom(shell, element._printZoom);
      prepareVisualViewportForPrint(shell);
    });
    mermaidBlocks.forEach(function(block) {
      var element = document.getElementById(block.id);
      var shell = element && element._mermaidShell;
      if (!shell) return;
      element._printZoom = shell.mermaidZoom;
      element._printBaseWidth = shell.mermaidBaseWidth;
      element._printBaseHeight = shell.mermaidBaseHeight;
      fitMermaidDiagram(shell);
      setMermaidZoom(shell, element._printZoom);
      prepareVisualViewportForPrint(shell);
    });
    markmapBlocks.forEach(function(block) {
      var element = document.getElementById(block.id);
      var map = element && element._markmap;
      var svg = element && element.querySelector('svg');
      var state = map && map.state;
      if (!svg || !map || !state || !isFinite(state.minX) || !isFinite(state.maxX) || !isFinite(state.minY) || !isFinite(state.maxY)) return;
      var padding = 24;
      var naturalWidth = state.maxY - state.minY + padding * 2;
      var naturalHeight = state.maxX - state.minX + padding * 2;
      var printZoom = element._markmapShell ? normalizeVisualZoom(element._markmapShell.markmapZoom) : 1;
      element._printMarkmap = {
        viewBox: svg.getAttribute('viewBox'),
        width: svg.getAttribute('width'),
        height: svg.getAttribute('height'),
        preserveAspectRatio: svg.getAttribute('preserveAspectRatio'),
        style: svg.getAttribute('style'),
        transform: map.g.attr('transform')
      };
      svg.setAttribute('viewBox', [state.minY - padding, state.minX - padding, naturalWidth, naturalHeight].join(' '));
      svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      svg.style.display = 'block';
      svg.style.setProperty('width', Math.round(printZoom * 100) + '%', 'important');
      svg.style.setProperty('height', 'auto', 'important');
      svg.style.setProperty('max-width', printZoom > 1 ? 'none' : '100%', 'important');
      svg.style.setProperty('max-height', 'none', 'important');
      svg.style.minWidth = '0';
      svg.style.margin = '0 auto';
      map.g.attr('transform', null);
      if (element._markmapShell) prepareVisualViewportForPrint(element._markmapShell);
    });
  }

  function restoreVisualsAfterPrint() {
    if (document.documentElement.getAttribute('data-printing') !== 'true') return;
    Object.keys(staticBlocks).forEach(function(id) {
      var element = document.getElementById(staticBlocks[id].id);
      var shell = element && element._staticShell;
      if (!shell || !Object.prototype.hasOwnProperty.call(element, '_printZoom')) return;
      shell.staticBaseWidth = element._printBaseWidth;
      shell.staticBaseHeight = element._printBaseHeight;
      setStaticZoom(shell, element._printZoom);
      restoreVisualViewportAfterPrint(shell);
      delete element._printZoom;
      delete element._printBaseWidth;
      delete element._printBaseHeight;
    });
    mermaidBlocks.forEach(function(block) {
      var element = document.getElementById(block.id);
      var shell = element && element._mermaidShell;
      if (!shell || !Object.prototype.hasOwnProperty.call(element, '_printZoom')) return;
      shell.mermaidBaseWidth = element._printBaseWidth;
      shell.mermaidBaseHeight = element._printBaseHeight;
      setMermaidZoom(shell, element._printZoom);
      restoreVisualViewportAfterPrint(shell);
      delete element._printZoom;
      delete element._printBaseWidth;
      delete element._printBaseHeight;
    });
    markmapBlocks.forEach(function(block) {
      var element = document.getElementById(block.id);
      var saved = element && element._printMarkmap;
      var map = element && element._markmap;
      var svg = element && element.querySelector('svg');
      if (!saved || !svg || !map) return;
      [['viewBox', saved.viewBox], ['width', saved.width], ['height', saved.height], ['preserveAspectRatio', saved.preserveAspectRatio]].forEach(function(entry) {
        if (entry[1] == null) svg.removeAttribute(entry[0]);
        else svg.setAttribute(entry[0], entry[1]);
      });
      if (saved.style == null) svg.removeAttribute('style');
      else svg.setAttribute('style', saved.style);
      map.g.attr('transform', saved.transform == null ? null : saved.transform);
      if (element._markmapShell) restoreVisualViewportAfterPrint(element._markmapShell);
      delete element._printMarkmap;
    });
    document.documentElement.removeAttribute('data-printing');
    window.requestAnimationFrame(function() {
      resizeStaticCharts();
      resizeMermaids();
      adjustMathOverflow();
    });
  }

  function printDocument() {
    dynamicVisualsReady.then(function() {
      window.print();
    }).catch(function() {});
  }

  function refreshDynamicVisuals() {
    var generation = ++renderGeneration;
    renderErrors = staticRenderErrors.slice();
    setRenderStatus(true);
    // 渲染进度信号供预览注入脚本等待（如滚动位置恢复），不改变任何可见行为
    document.documentElement.setAttribute('data-dynamic-visuals', 'pending');
    dynamicVisualsReady = renderMermaids(generation).then(function() {
      if (generation !== renderGeneration) return;
      return renderMarkmaps(generation);
    }).then(function() {
      if (generation !== renderGeneration) return;
      adjustMathOverflow();
      setRenderStatus(false);
      document.documentElement.setAttribute('data-dynamic-visuals', 'done');
    }).catch(function(error) {
      if (generation !== renderGeneration) return;
      recordRenderError('页面图表', error.message || error);
      setRenderStatus(false);
      document.documentElement.setAttribute('data-dynamic-visuals', 'done');
    });
    return dynamicVisualsReady;
  }

  var headerElement = document.querySelector('.viewer-header');

  function updateHeaderShadow() {
    if (!headerElement) return;
    headerElement.classList.toggle('is-scrolled', (window.scrollY || window.pageYOffset || 0) > 8);
  }

  decorateHeadings();
  buildToc();
  setupTocSpy();
  updateHeaderShadow();
  window.addEventListener('scroll', updateHeaderShadow, { passive: true });
  enhanceCodeBlocks();
  adjustMathOverflow();
  staticRenderErrors = renderStaticCharts();
  visualsStarted = true;
  refreshDynamicVisuals();

  if (window.ResizeObserver && container) {
    var visualSizeObserver = new window.ResizeObserver(scheduleVisualResize);
    visualSizeObserver.observe(container);
  }

  document.addEventListener('click', function(event) {
    if (!isFloatingToc() || !tocPanel || !tocPanel.classList.contains('is-open')) return;
    if (tocPanel.contains(event.target) || (tocToggle && tocToggle.contains(event.target))) return;
    setTocOpen(false);
  });
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') setTocOpen(false);
  });
  window.addEventListener('beforeprint', prepareVisualsForPrint);
  window.addEventListener('afterprint', restoreVisualsAfterPrint);
  if (window.matchMedia) {
    var printMedia = window.matchMedia('print');
    var onPrintMediaChange = function(event) {
      if (!event.matches) restoreVisualsAfterPrint();
    };
    if (printMedia.addEventListener) printMedia.addEventListener('change', onPrintMediaChange);
    else if (printMedia.addListener) printMedia.addListener(onPrintMediaChange);
  }
  window.addEventListener('resize', function() {
    updateTocLayout();
    scheduleVisualResize();
    if (document.body.classList.contains('visual-maximized-open')) {
      window.requestAnimationFrame(relayoutAllVisualsForMaximize);
    }
  });
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape' && document.body.classList.contains('visual-maximized-open')) {
      allVisualShells.forEach(function(shell) {
        if (shell && shell.maximized) setVisualMaximized(shell, false);
      });
    }
  });
  if (window.matchMedia) {
    var media = window.matchMedia('(prefers-color-scheme: dark)');
    var onSystemThemeChange = function() {
      if (getThemePreference() === 'auto') applyTheme('auto', false);
    };
    if (media.addEventListener) media.addEventListener('change', onSystemThemeChange);
    else if (media.addListener) media.addListener(onSystemThemeChange);
  }
}

async function main() {
  const degradedFences = collectDegradedFences();
  const preparedMarkdown = await preRenderStaticCharts(sourceMarkdown, degradedFences.lines);
  preparedMarkdown.warnings = degradedFences.warnings.concat(preparedMarkdown.warnings);
  preparedMarkdown.degraded = degradedFences.degraded;
  const markdownContent = preparedMarkdown.markdown;
  const resourceMarkup = buildResourceMarkup(selectedResources, resourceManifest);
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${esc(title)}</title>
<script>(${bootstrapTheme.toString()})(${scriptJson(options.theme)});</script>
${resourceMarkup.styles}
<style>
:root {
  /* Professional 调性：精致中性灰阶 + 单一 accent + hairline 边框（对齐 Geist/Linear 语言） */
  --bg: #ffffff; --bg2: #fafafa; --bg-code: #f5f5f5;
  --text: #171717; --text2: #737373; --border: #e5e5e5;
  --accent: #2563eb; --accent-bg: rgba(37, 99, 235, 0.08); --accent-strong: #1d4ed8; --accent-fg: #ffffff;
  --error: #dc2626; --error-bg: #fef2f2; --error-text: #991b1b;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 4px 16px rgba(0, 0, 0, 0.05);
  --shadow-lg: 0 8px 32px -8px rgba(0, 0, 0, 0.12);
  --radius-sm: 6px; --radius: 10px;
  --measure: 56rem;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
  --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  --content-width: 80%;
  color-scheme: light;
}
html[data-theme="dark"] {
  --bg: #0a0a0a; --bg2: #141414; --bg-code: #141414;
  --text: #fafafa; --text2: #a3a3a3; --border: #262626;
  --accent: #60a5fa; --accent-bg: rgba(96, 165, 250, 0.12); --accent-strong: #93c5fd; --accent-fg: #0a0a0a;
  --error: #f87171; --error-bg: rgba(248, 113, 113, 0.1); --error-text: #fca5a5;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 4px 16px rgba(0, 0, 0, 0.35);
  --shadow-lg: 0 8px 32px -8px rgba(0, 0, 0, 0.55);
  color-scheme: dark;
}
html[data-theme="dark"] .hljs { color: #c9d1d9; background: var(--bg-code); }
html[data-theme="dark"] .hljs-doctag, html[data-theme="dark"] .hljs-keyword, html[data-theme="dark"] .hljs-meta .hljs-keyword, html[data-theme="dark"] .hljs-template-tag, html[data-theme="dark"] .hljs-template-variable, html[data-theme="dark"] .hljs-type, html[data-theme="dark"] .hljs-variable.language_ { color: #ff7b72; }
html[data-theme="dark"] .hljs-title, html[data-theme="dark"] .hljs-title.class_, html[data-theme="dark"] .hljs-title.class_.inherited__, html[data-theme="dark"] .hljs-title.function_ { color: #d2a8ff; }
html[data-theme="dark"] .hljs-attr, html[data-theme="dark"] .hljs-attribute, html[data-theme="dark"] .hljs-literal, html[data-theme="dark"] .hljs-meta, html[data-theme="dark"] .hljs-number, html[data-theme="dark"] .hljs-operator, html[data-theme="dark"] .hljs-selector-attr, html[data-theme="dark"] .hljs-selector-class, html[data-theme="dark"] .hljs-selector-id, html[data-theme="dark"] .hljs-variable { color: #79c0ff; }
html[data-theme="dark"] .hljs-meta .hljs-string, html[data-theme="dark"] .hljs-regexp, html[data-theme="dark"] .hljs-string { color: #a5d6ff; }
html[data-theme="dark"] .hljs-built_in, html[data-theme="dark"] .hljs-symbol { color: #ffa657; }
html[data-theme="dark"] .hljs-code, html[data-theme="dark"] .hljs-comment, html[data-theme="dark"] .hljs-formula { color: #8b949e; }
html[data-theme="dark"] .hljs-name, html[data-theme="dark"] .hljs-quote, html[data-theme="dark"] .hljs-selector-pseudo, html[data-theme="dark"] .hljs-selector-tag { color: #7ee787; }
html[data-theme="dark"] .hljs-subst { color: #c9d1d9; }
html[data-theme="dark"] .hljs-section { color: #79c0ff; }
html[data-theme="dark"] .hljs-bullet { color: #e3b341; }
html[data-theme="dark"] .hljs-emphasis { color: #c9d1d9; }
html[data-theme="dark"] .hljs-strong { color: #c9d1d9; }
html[data-theme="dark"] .hljs-addition { color: #7ee787; background-color: #033a16; }
html[data-theme="dark"] .hljs-deletion { color: #ffa198; background-color: #67060c; }
 * { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; font-family: var(--sans); color: var(--text); background: var(--bg);
  line-height: 1.7; -webkit-font-smoothing: antialiased;
  /* 只过渡背景色：全页文本节点参与 color 过渡会让大文档的主题切换明显卡顿 */
  transition: background-color 160ms ease;
}
::selection { background: var(--accent-bg); color: var(--accent-strong); }
html[data-theme="dark"] ::selection { background: rgba(96, 165, 250, 0.3); color: #fafafa; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
 /* Firefox 滚动条与 webkit 样式对齐（hover 变色仅 webkit 支持） */
 *, html { scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
 ::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 5px; border: 2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover { background: var(--text2); }
button, input, select { font: inherit; }
.viewer-header {
  position: sticky; z-index: 20; top: 0; border-bottom: 1px solid var(--border);
  background: var(--bg); background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  transition: box-shadow 180ms ease;
}
.viewer-header.is-scrolled { box-shadow: var(--shadow); }
.viewer-header-inner {
  width: 100%; min-height: 3.6rem; padding: 0.5rem clamp(1rem, 3vw, 3rem);
  display: flex; align-items: center; gap: 0.8rem;
}
.viewer-brand { display: inline-flex; align-items: center; gap: 0.55rem; min-width: 0; font-weight: 650; font-size: 0.95rem; letter-spacing: -0.01em; }
.viewer-brand-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.viewer-actions { margin-left: auto; display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap; justify-content: flex-end; }
  .viewer-btn, .theme-select, .code-copy, .code-collapse, .visual-btn {
  min-height: 2rem; padding: 0.2rem 0.55rem; border-radius: 0; border: 1px solid transparent;
  background: transparent; color: var(--text2); cursor: pointer; line-height: 1.3; font-size: 0.82rem;
  transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease;
}
  .viewer-btn:hover, .code-copy:hover, .code-collapse:hover, .visual-btn:hover { background: var(--bg2); color: var(--text); }
  .viewer-btn:disabled, .code-copy:disabled, .code-collapse:disabled, .visual-btn:disabled { cursor: default; opacity: 0.55; }
.theme-toggle { display: inline-flex; align-items: center; gap: 0.35rem; }
.theme-toggle svg { width: 0.95rem; height: 0.95rem; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; flex: 0 0 auto; }
.render-status { color: var(--text2); font-size: 0.75rem; white-space: nowrap; }
.render-status.is-error { color: var(--error); }
.viewer-layout { min-width: 0; }
.toc-panel {
  position: fixed; z-index: 19; top: 4.25rem; bottom: 1rem; left: 1rem; display: none;
  width: min(21rem, calc(100vw - 2rem)); overflow: auto; padding: 0.8rem;
  border: 1px solid var(--border); border-radius: 0; background: var(--bg); box-shadow: var(--shadow-lg);
}
.toc-panel.is-open { display: block; }
.toc-title { margin-bottom: 0.45rem; color: var(--text2); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
.toc-link { display: block; padding: 0.28rem 0.65rem; color: var(--text2); border-radius: 0; font-size: 0.87rem; line-height: 1.45; }
.toc-link:hover { color: var(--accent); background: var(--bg2); text-decoration: none; }
.toc-link.is-active { color: var(--accent); font-weight: 600; }
.container { width: var(--content-width); max-width: var(--measure); min-width: 0; margin: 0 auto; padding: 2.5rem clamp(1rem, 3vw, 3rem) 5rem; animation: viewer-in 260ms ease both; }
@keyframes viewer-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .container { animation: none; } }
/* 全部内容元素共享同一列宽，文字、图表、代码边界完全对齐，不做局部收窄 */
h1, h2, h3, h4, h5, h6 {
  margin-top: 1.9em; margin-bottom: 0.6em; font-weight: 700; line-height: 1.3; letter-spacing: -0.015em; scroll-margin-top: 5rem;
}
h1 { font-size: 2.35rem; padding-bottom: 0.35em; border-bottom: 1px solid var(--border); letter-spacing: -0.022em; }
h2 { font-size: 1.65rem; letter-spacing: -0.018em; }
h3 { font-size: 1.3rem; letter-spacing: -0.01em; }
h4 { font-size: 1.08rem; }
h1:first-child, h2:first-child { margin-top: 0; }
.heading-anchor { display: inline-block; width: 1.25em; margin-left: -1.25em; color: var(--text2); opacity: 0; text-decoration: none; transition: opacity 120ms ease; }
h1:hover .heading-anchor, h2:hover .heading-anchor, h3:hover .heading-anchor, h4:hover .heading-anchor, h5:hover .heading-anchor, h6:hover .heading-anchor, .heading-anchor:focus { opacity: 0.75; }
p { margin: 0 0 1em; }
a { color: var(--accent); text-decoration: none; text-underline-offset: 0.18em; }
a:hover { text-decoration: underline; }
strong { font-weight: 650; }
blockquote { margin: 1.2em 0; padding: 0.6em 1.1em; border-left: 3px solid var(--border); background: var(--bg2); border-radius: 0 var(--radius) var(--radius) 0; color: var(--text2); }
blockquote p:last-child { margin-bottom: 0; }
ul, ol { margin: 0.8em 0; padding-left: 1.8em; }
li { margin-bottom: 0.3em; }
li::marker { color: var(--text2); }
hr { border: 0; height: 1px; background: linear-gradient(to right, transparent, var(--border) 12%, var(--border) 88%, transparent); margin: 2.6em 0; }
img { display: block; width: auto; max-width: 100%; height: auto; margin: 1.2em auto; border-radius: var(--radius); box-shadow: var(--shadow); }
table { width: max-content; max-width: 100%; display: block; overflow-x: auto; border-collapse: separate; border-spacing: 0; margin: 1.4em auto; font-size: 0.92rem; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); box-shadow: var(--shadow-sm); }
thead { border-bottom: 0; }
th { padding: 0.65em 0.9em; text-align: left; font-weight: 650; white-space: nowrap; border-bottom: 2px solid var(--border); }
td { padding: 0.55em 0.9em; border-bottom: 1px solid var(--border); }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:nth-child(even) td { background: var(--bg2); }
tbody tr:hover td { background: var(--accent-bg); }
code { padding: 0.18em 0.42em; border-radius: var(--radius-sm); background: var(--bg-code); font-family: var(--mono); font-size: 0.87em; border: 1px solid var(--border); }
pre { margin: 1.2em 0; overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-sm); }
pre code { display: block; padding: 1em 1.2em; border-radius: 0; border: 0; background: var(--bg-code); font-size: 0.87rem; line-height: 1.65; }
.code-block { margin: 1.2em 0; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-sm); }
.code-block pre { margin: 0; border: 0; border-radius: 0; box-shadow: none; }
.code-toolbar { display: flex; align-items: center; gap: 0.5rem; min-height: 2.2rem; padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--border); background: var(--bg-code); }
  .code-language { margin-right: auto; color: var(--text2); font-family: var(--mono); font-size: 0.76rem; }
  .code-chart-badge { display: inline-flex; align-items: center; gap: 0.25rem; padding: 0.05rem 0.42rem; border: 1px solid #d97706; border-radius: var(--radius-sm); background: #fef3c7; color: #92400e; font-size: 0.72rem; line-height: 1.55; cursor: help; white-space: nowrap; }
  .code-chart-badge svg { width: 0.85rem; height: 0.85rem; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
html[data-theme="dark"] .code-chart-badge { border-color: #a16207; background: #3b2f0b; color: #fbbf24; }
  .icon-button { display: inline-flex; align-items: center; justify-content: center; width: 2rem; min-width: 2rem; padding: 0.25rem; }
  .icon-button svg { width: 1rem; height: 1rem; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  .code-block.is-collapsed pre { display: none; }
.visual-canvas, .diagram { display: flex; align-items: center; justify-content: center; width: 100%; min-width: 100%; margin: 0 auto; }
.diagram svg { display: block; max-width: 100%; height: auto; }
.visual-box { width: min(100%, var(--visual-width)); min-width: 0; max-width: 100%; margin: 1.4em auto; overflow: hidden; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); box-shadow: var(--shadow-sm); --visual-width: 960px; --visual-height: 520px; }
body.visual-maximized-open { overflow: hidden; }
.visual-box.is-maximized {
  position: fixed !important; inset: 0 !important; z-index: 1000 !important; display: flex !important; flex-direction: column !important;
  width: 100vw !important; height: 100vh !important; max-width: none !important; min-width: 0 !important; min-height: 0 !important; margin: 0 !important; border: 0 !important; border-radius: 0 !important;
  background: var(--bg); box-shadow: 0 0 0 100vmax rgba(0, 0, 0, 0.5);
}
.visual-box.is-maximized > .visual-toolbar { flex: 0 0 auto; position: sticky; top: 0; z-index: 2; }
.visual-box.is-maximized > .visual-stage,
.visual-box.is-maximized > .visual-stage.visual-stage-explicit { flex: 1 1 auto !important; min-height: 0 !important; height: auto !important; width: 100% !important; max-width: 100% !important; overflow: auto !important; }
.visual-box.is-maximized.mermaid-box > .visual-stage,
.visual-box.is-maximized.static-chart > .visual-stage { height: auto; }
.visual-box.is-maximized > .visual-source { flex: 1 1 auto; min-height: 0; }
.visual-btn.visual-maximize-btn.is-active, .visual-btn.visual-minimize-btn.is-active { background: var(--accent, #2563eb); color: var(--accent-fg); }
.visual-btn.visual-maximize-btn:disabled, .visual-btn.visual-minimize-btn:disabled { opacity: 0.45; cursor: default; }
.visual-toolbar { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); background: var(--bg); }
.visual-label { margin-right: auto; color: var(--text2); font-size: 0.78rem; }
.visual-actions { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.visual-btn { min-width: auto; }
.visual-btn.mode-btn.is-active { border-color: var(--accent); background: var(--accent); color: var(--accent-fg); }
.visual-zoom { display: inline-flex; align-items: center; flex: 0 0 auto; overflow: hidden; border: 1px solid var(--border); border-radius: 0; background: var(--bg); }
.visual-zoom .zoom-btn { min-width: 1.8rem; border: 0; border-radius: 0; }
.visual-zoom-input { width: 2.75rem; padding: 0.25rem 0.05rem; border: 0; outline: 0; background: transparent; color: var(--text); text-align: center; font-variant-numeric: tabular-nums; appearance: textfield; }
.visual-zoom-input::-webkit-inner-spin-button, .visual-zoom-input::-webkit-outer-spin-button { margin: 0; appearance: none; }
.visual-zoom-unit { padding-right: 0.25rem; color: var(--text2); font-size: 0.78rem; }
.visual-stage { width: 100%; height: var(--visual-height); overflow: auto; }
.visual-stage-fit { height: auto; overflow: visible; }
.visual-source { display: none; max-height: min(34rem, 65vh); margin: 0; overflow: auto; border: 0; border-radius: 0; background: var(--bg-code); }
.visual-source code { min-height: 100%; }
.visual-box.show-source .visual-stage { display: none; }
.visual-box.show-source .visual-source { display: block; }
.mermaid-box .visual-stage { height: auto; overflow: visible; padding: 0.75rem; }
.static-chart { padding: 0; background: var(--bg); }
.static-chart .visual-stage { height: auto; overflow: visible; padding: 0.75rem; }
.visual-box.is-visual-contained .visual-stage { overflow: auto; }
.visual-box.is-visual-zoomed .visual-stage-explicit { place-items: start; overflow: auto; }
.static-chart .static-svg-image { display: block; width: auto; max-width: 100%; max-height: 100%; height: auto; margin: 0 auto; object-fit: contain; }
.markmap-box { background: var(--bg2); }
.markmap-box .visual-stage { background: var(--bg2); }
.markmap-box svg { display: block; width: 100%; height: 100%; min-width: 0; }
.visual-stage-explicit { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); place-items: center; width: 100%; min-width: 0; max-width: 100%; height: auto !important; padding: 0 !important; overflow: hidden; }
.visual-stage-explicit > .visual-canvas { grid-area: 1 / 1; width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: visible; }
.visual-stage-explicit .static-svg-image { min-width: 0; min-height: 0; max-width: 100%; max-height: 100%; margin: auto; object-fit: contain; }
.visual-stage-explicit > svg { grid-area: 1 / 1; width: 100%; height: 100%; min-width: 0; min-height: 0; max-width: 100%; max-height: 100%; }
.visual-stage-explicit > .diagram > svg { min-width: 0; max-width: 100%; max-height: 100%; }
.markmap-box .markmap-node text { fill: var(--text); }
.markmap-box foreignObject { color: var(--text); }
.math-display { max-width: 100%; margin: 1em 0; overflow: visible; text-align: center; }
.math-display .katex { white-space: nowrap; }
.math-display.math-overflow { overflow-x: auto; padding-bottom: 0.2rem; text-align: left; }
.katex-mathml { display: none !important; }
.katex-html { display: inline-block; }
.math-error { color: var(--error); }
.callout { margin: 1.2em 0; padding: 0.85em 1.1em; border-left: 3px solid var(--accent); border-radius: 0 var(--radius) var(--radius) 0; background: var(--accent-bg); font-size: 0.93rem; }
.callout-err { border-color: var(--error); background: var(--error-bg); color: var(--error-text); }
.columns-layout { display: grid; grid-template-columns: repeat(var(--column-count), minmax(0, 1fr)); gap: 1rem; min-width: 0; margin: 1.2em 0; }
.column-layout { min-width: 0; padding: 1.1rem; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg2); box-shadow: var(--shadow-sm); }
.column-layout .visual-box { width: min(100%, var(--visual-width)); min-width: 0; max-width: 100%; }
.column-layout .visual-toolbar { display: grid; grid-template-columns: minmax(0, 1fr); align-items: start; }
.column-layout .visual-label { min-width: 0; margin-right: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.column-layout .visual-actions { min-width: 0; flex-wrap: nowrap; overflow-x: auto; padding-bottom: 0.1rem; }
.column-layout .visual-actions > * { flex: 0 0 auto; }
.column-layout > :first-child { margin-top: 0; }
.column-layout > :last-child { margin-bottom: 0; }
@media screen and (min-width: 761px) {
  .viewer-layout:not(.toc-is-floating).toc-is-open { display: grid; grid-template-columns: minmax(0, 1fr) minmax(10rem, var(--toc-width)); align-items: start; }
  .viewer-layout[data-toc-layout="right"] .toc-panel { grid-column: 2; }
  .viewer-layout[data-toc-layout="right"] .container { grid-column: 1; }
  .viewer-layout[data-toc-layout="left"] .toc-panel { grid-column: 1; }
  .viewer-layout[data-toc-layout="left"] .container { grid-column: 2; }
  .viewer-layout[data-toc-layout="left"].toc-is-open { grid-template-columns: minmax(10rem, var(--toc-width)) minmax(0, 1fr); }
  .viewer-layout:not(.toc-is-floating).toc-is-open .toc-panel {
    position: sticky; z-index: 1; top: 4.5rem; bottom: auto; left: auto; display: block;
    width: auto; max-height: calc(100vh - 5.5rem); margin: 1rem 0.75rem; box-shadow: none;
  }
  .viewer-layout:not(.toc-is-floating).toc-is-open .container { width: 100%; padding-left: clamp(1rem, 3vw, 3rem); padding-right: clamp(1rem, 3vw, 3rem); }
  .viewer-layout:not(.toc-is-floating):not(.toc-is-open) .container { width: var(--content-width); }
}
@media print {
  @page { margin: 12mm; }
  html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { margin: 0 !important; padding: 0 !important; width: 100% !important; }
  .viewer-header, .toc-panel, .visual-toolbar, .code-toolbar { display: none !important; }
  .viewer-layout { display: block !important; width: 100% !important; max-width: 100% !important; margin: 0 !important; padding: 0 !important; transform: none !important; }
  .container { width: 100% !important; max-width: 100% !important; min-width: 0 !important; margin: 0 !important; padding: 0 !important; box-sizing: border-box !important; }
  h1, h2, h3 { break-after: avoid-page; page-break-after: avoid; }
  .visual-box:not(.markmap-box), blockquote, table, pre { break-inside: avoid; page-break-inside: avoid; }
  .visual-box { width: 100% !important; max-width: 100% !important; overflow: visible; margin: 1.2em 0 !important; }
  .visual-box.show-source .visual-stage { display: block !important; }
  .visual-source { display: none !important; }
  .visual-stage { position: relative !important; display: grid !important; grid-template-columns: minmax(0, 1fr) !important; grid-template-rows: minmax(0, 1fr) !important; align-items: unsafe center !important; justify-items: center !important; overflow: hidden !important; }
  .visual-stage-explicit { width: 100% !important; min-width: 0 !important; max-width: 100% !important; overflow: hidden !important; }
  .visual-stage > .visual-canvas, .markmap-box .visual-stage > svg { position: static !important; grid-area: 1 / 1 !important; align-self: unsafe center !important; justify-self: center !important; margin: 0 auto !important; max-width: 100% !important; min-width: 0 !important; transform: none !important; }
  .visual-stage-explicit .diagram svg, .visual-stage-explicit .static-svg-image { max-width: 100% !important; max-height: 100% !important; height: auto !important; object-fit: contain; }
  .markmap-box .visual-stage-explicit > svg { width: 100% !important; height: 100% !important; max-width: 100% !important; max-height: 100% !important; }
  .mermaid-box .visual-stage:not(.visual-stage-explicit), .static-chart .visual-stage:not(.visual-stage-explicit) { overflow: hidden !important; }
  .mermaid-box .visual-stage:not(.visual-stage-explicit) .diagram svg { max-width: 100% !important; max-height: none !important; height: auto !important; }
  .static-chart .visual-stage:not(.visual-stage-explicit) .static-svg-image { max-width: 100% !important; max-height: none !important; height: auto !important; }
  .mermaid-box.is-mermaid-zoomed .visual-stage .diagram svg, .static-chart.is-static-zoomed .visual-stage .static-svg-image { max-width: none !important; max-height: none !important; }
  .markmap-box { break-inside: auto; page-break-inside: auto; }
  .markmap-box .visual-stage:not(.visual-stage-explicit) { overflow: hidden !important; padding: 0 !important; }
  .markmap-box .visual-stage:not(.visual-stage-explicit) svg { display: block; width: 100% !important; max-width: 100% !important; max-height: none !important; min-width: 0 !important; height: auto !important; }
  table { display: table !important; width: auto !important; max-width: 100% !important; margin: 1em 0 !important; overflow: visible !important; }
  .columns-layout { display: grid !important; grid-template-columns: repeat(var(--column-count), minmax(0, 1fr)) !important; gap: 6mm; width: 100%; align-items: start; }
  .column-layout { width: auto; min-width: 0; padding: 4mm; }
  .column-layout .visual-box { width: 100% !important; max-width: 100% !important; }
  .code-block.is-collapsed pre { display: block !important; }
  pre { overflow: visible; white-space: pre-wrap; word-break: break-word; }
  .math-display { overflow: visible !important; text-align: center !important; }
}
@media screen and (max-width: 760px) {
  .viewer-header-inner { align-items: flex-start; flex-direction: column; }
  .viewer-actions { width: 100%; margin-left: 0; justify-content: flex-start; }
  .toc-panel { top: 7.5rem; }
  .viewer-layout { display: block; }
  .container { width: 100%; padding: 1.25rem 1rem 3.5rem; }
  .columns-layout { grid-template-columns: 1fr; }
  h1 { font-size: 1.8rem; } h2 { font-size: 1.42rem; } h3 { font-size: 1.18rem; }
  .heading-anchor { margin-left: 0; width: auto; margin-right: 0.25em; opacity: 0.55; }
}
</style>
</head>
<body>
<header class="viewer-header"><div class="viewer-header-inner" id="viewer-controls"></div></header>
<div class="viewer-layout" id="viewer-layout"><main class="container" id="content"></main><aside class="toc-panel" id="toc-panel" aria-label="文档目录" aria-hidden="true"><div class="toc-title">目录</div><nav id="toc-content"></nav></aside></div>
${licenseMarkup()}
${resourceMarkup.scripts}
<script>(${clientRuntime.toString()})(${scriptJson(markdownContent)}, ${scriptJson(sourceDownloadName)}, ${scriptJson(preparedMarkdown.blocks)}, ${scriptJson(options)}, ${scriptJson(title)}, ${scriptJson(preparedMarkdown.degraded)});</script>
</body>
</html>`;

  writeFileAtomically(outputFile, html);
  const sizeKB = (Buffer.byteLength(html) / 1024).toFixed(0);
  const sizeMB = (Buffer.byteLength(html) / 1024 / 1024).toFixed(1);
  const size = sizeKB > 1024 ? sizeMB + ' MB' : sizeKB + ' KB';
  const resourceSummary = output.mode === 'single'
    ? `内联资源 ${selectedResources.length} 个`
    : `本地资源 ${resourceMarkup.copied.length} 个`;
  console.log(`已生成: ${outputFile} (${size}, ${resourceSummary})`);
  if (preparedMarkdown.warnings.length) {
    preparedMarkdown.warnings.forEach(function(warning) { console.warn(`⚠️ ${warning}`); });
  }
}

main().catch(function(error) {
  console.error(`生成失败: ${error.message || error}`);
  process.exit(1);
});
}
