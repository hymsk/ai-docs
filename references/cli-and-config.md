# CLI 与 JSON 配置

构建入口始终使用 Skill 自带脚本：

```bash
node <SKILL_DIR>/scripts/build.js --input document.md --output document.html
```

也支持位置参数：

```bash
node <SKILL_DIR>/scripts/build.js document.md document.html
```

默认生成按需内联依赖的单文件 HTML。未指定输出时，在输入文件旁生成同名 `.html`；构建器会创建缺失的输出目录。输出不能覆盖输入 Markdown，也不能通过软链接间接覆盖输入。

生成页面会安全内嵌原始 Markdown，并提供“下载 MD”按钮。下载文件名沿用输入 Markdown 文件名；若输入扩展名不是 `.md` 或 `.markdown`，则改用 `.md`。

## 输出模式

| 模式 | CLI | JSON | 结果 |
| --- | --- | --- | --- |
| 单文件 | `--output-mode single` | `output.mode: "single"` | 一个按需内联依赖的自包含 HTML，默认模式 |
| 本地多文件 | `--output-mode multi` | `output.mode: "multi"` | HTML 与本地静态依赖目录，适合 Nginx 或 Python HTTP 服务 |

### 资源模式

单文件输出下资源默认按需内联（`--resources-mode inline`，`resources.mode: "inline"`）。服务端托管场景可改用 `--resources-mode linked`（`resources.mode: "linked"`）：HTML 不再内联资源，而是引用 `--public-path` 指向的文件，这些文件需要由外部服务提供；`linked` 必须显式指定 `resources.publicPath`，否则构建失败。Web 服务的预览与公开页面即使用该模式，资源由 `/assets/<renderer-fingerprint>/<file>` 端点提供，见 [web-mcp-setup](web-mcp-setup.md)。

无论哪种模式，依赖都会被分类为关键资源（Markdown-it、Highlight.js、KaTeX 等，参与内容渲染）与延后引擎（Mermaid、D3、Markmap，位于渲染入口之后，内容呈现后再执行），以避免大脚本阻塞首屏。

`--emit-resources <directory>` 把资源清单按与内联/multi 复制完全一致的转换写入目录（服务端用于托管导出），不接受输入文件，普通文档构建无需使用。

当前不支持 CDN 或任意远程资源 URL。ECharts 始终在构建期生成静态 SVG，不会复制 ECharts 浏览器运行时。AI Docs 不内置 Graphviz；`dot`/`graphviz` fence 会降级为普通代码块（表头警示标识，悬浮显示原因），构建仍以 0 退出，请迁移为 Mermaid flowchart。

### 单文件

```bash
node <SKILL_DIR>/scripts/build.js \
  --input document.md \
  --output dist/document.html
```

构建器按 Markdown 内容选择依赖：

| 内容 | 资源 |
| --- | --- |
| 所有文档 | Markdown-it |
| 带语言名的普通代码块 | Highlight.js 与高亮样式 |
| KaTeX 公式 | KaTeX JS/CSS |
| Mermaid fence | Mermaid |
| Markmap/Mindmap fence | D3、KaTeX、Markmap Lib、Markmap View |

未使用的可选资源不会写入成品。默认的 `inline` 单文件不请求外部脚本或样式，可直接离线打开；`linked` 模式则引用 `publicPath` 下托管的同一套文件，需要外部服务提供它们。

### 本地多文件

```bash
node <SKILL_DIR>/scripts/build.js \
  --input document.md \
  --output-mode multi \
  --output-dir dist/docs \
  --output-name index.html
```

默认生成：

```text
dist/docs/
├── index.html
└── static/
    └── 当前文档实际需要的依赖
```

自定义 Nginx 公开路径：

```bash
node <SKILL_DIR>/scripts/build.js \
  --input document.md \
  --output-mode multi \
  --output-dir dist/docs \
  --output-name index.html \
  --static-dir assets/vendor \
  --public-path /docs/assets/vendor/
```

`--static-dir` 是磁盘目录，相对于输出 HTML；`--public-path` 是 HTML 中的 URL 前缀。后者不会改变依赖文件的实际写入位置。

当 `publicPath` 使用 `/docs/assets/vendor/` 这类 Nginx 根路径时，本地服务器也必须从包含 `docs/` 的上级目录启动，并访问 `/docs/`。如果希望直接服务 HTML 所在目录，请使用默认相对路径 `./static/`。

## 输入输出选项

| CLI | JSON 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `-i, --input <file>` | 无 | 必填 | 输入 Markdown |
| `-o, --output <file>` | 无 | 输入旁同名 HTML | 完整输出 HTML 路径 |
| `--output-mode single\|multi` | `output.mode` | `single` | 输出模式 |
| `--output-dir <directory>` | `output.directory` | 输入文件目录 | 输出目录 |
| `--output-name <file>` | `output.fileName` | 输入文件同名 HTML | 输出文件名，必须以 `.html` 或 `.htm` 结尾 |
| `--title <text>` | `title` | 输入文件名 | 页面标题 |
| `--config <file>` | 无 | 无 | 读取 JSON 配置 |
| `-h, --help` | 无 | 无 | 显示脚本内置帮助 |

`--output` 表示完整目标路径，不能与 `--output-dir` 或 `--output-name` 同时使用。CLI 没有 `--output` 时，配置中的 `output.directory` 相对于配置文件所在目录解析。

## 本地资源选项

| CLI | JSON 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--static-dir <directory>` | `resources.directory` | `static` | 多文件依赖写入目录，相对于输出 HTML |
| `--public-path <url-path>` | `resources.publicPath` | 从静态目录推导 | HTML 中的本地资源 URL 前缀 |
| `--resources-mode <inline\|linked>` | `resources.mode` | `inline` | 单文件下资源内联进 HTML，还是引用 `publicPath` 下由外部托管的文件 |

`resources.directory` 必须位于输出 HTML 目录内，不能使用绝对路径、软链接或 `..` 越界。已有资源目标必须是单链接普通文件，不能是软链接、悬空软链接或硬链接。`resources.publicPath` 只接受本地相对 URL 或根路径 URL，例如 `./static/`、`../shared/`、`/docs/static/`；不接受 URL 协议、协议相对地址、query 或 fragment。

内置资源清单位于 `assets/default-resources.json`，包含以下资源：

```text
markdownIt
highlightCss
katexCss
highlightJs
mermaid
d3
katexJs
markmapLib
markmapView
```

## 页面选项

| CLI | JSON 字段 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `--toc` / `--no-toc` | `toc` | `true` | 标题锚点和目录 |
| `--code-tools` / `--no-code-tools` | `codeTools` | `true` | 语言标签和复制按钮 |
| `--code-collapse` / `--no-code-collapse` | `codeCollapse` | `false` | 普通代码块初始收起或展开；按钮始终可手动切换 |
| `--chart-tools` / `--no-chart-tools` | `chartTools` | `true` | 整套图表工具栏 |
| `--source-toggle` / `--no-source-toggle` | `sourceToggle` | `true` | 预览/源码切换 |
| `--chart-export` / `--no-chart-export` | `chartExport` | `true` | SVG/PNG 导出 |
| `--chart-maximize` / `--no-chart-maximize` | `chartMaximize` | `true` | 图表最大化和最小化 |
| `--print` / `--no-print` | `print` | `true` | 打印按钮和打印样式 |
| `--theme-control` / `--no-theme-control` | `themeControl` | `true` | 主题选择器 |
| `--strict` / `--no-strict` | `strict` | `true` | ECharts 预渲染失败时退出或保留错误卡片 |

`--no-chart-tools` 会关闭整个图表工具栏；此时源码切换、导出、缩放和最大化控件都不会显示。

## 枚举与尺寸

| CLI | JSON 字段 | 范围 | 默认值 |
| --- | --- | --- | --- |
| `--theme auto\|light\|dark` | `theme` | 三选一 | `auto` |
| `--content-width <50-100>` | `contentWidth` | 50-100，可写 `80%` | `80` |
| `--toc-layout left\|right\|float` | `tocLayout` | 三选一 | `right` |
| `--toc-width <10-40>` | `tocWidth` | 10-40 | `20` |
| `--visual-width <240-2400>` | `visualWidth` | 整数 px | `960` |
| `--visual-height <160-1600>` | `visualHeight` | 整数 px | `520` |
| `--mermaid-security strict\|loose` | `mermaidSecurity` | 二选一 | `strict` |

## 实时编辑预览

`preview.js` 启动仅监听本机的网页编辑器：左侧编辑 Markdown，右侧通过 `build.js` 的同一渲染路径显示结果。因此预览保留离线 renderer 的严格校验、按需本地依赖、图表与页面选项；它不是另一套 renderer。

```bash
node <SKILL_DIR>/scripts/preview.js \
  --input document.md \
  --open
```

也可从构建命令进入：

```bash
node <SKILL_DIR>/scripts/build.js --preview --input document.md --port 0 --open
```

| CLI | 默认值 | 说明 |
| --- | --- | --- |
| `-i, --input <file>` | 必填 | 要编辑和渲染的 Markdown 文件 |
| `--config <file>` | 无 | 复用 AI Docs JSON 配置中的页面选项；不会采用其输出或服务目录设置 |
| `--title <text>` | 输入文件名 | 覆盖右侧 renderer 文档标题 |
| `--host <address>` | `127.0.0.1` | 预览服务器监听地址；除非明确需要局域网访问，否则不要改为 `0.0.0.0` |
| `-p, --port <port>` | `8000` | 监听端口；`0` 自动选择空闲端口 |
| `--open` / `--no-open` | `false` | 启动后是否打开默认浏览器 |

编辑器会在输入停止约 350 ms 后刷新，`Ctrl/⌘ + Enter` 可立即渲染。点击“保存”或按 `Ctrl/⌘ + S` 才会原子写回输入 Markdown；仅渲染不会修改源文件。编辑器和预览之间的分隔栏可以拖动，窄屏时自动改为上下布局。

预览网页不公开静态目录，也不接受文件路径参数；它只服务自身页面并接收当前编辑器中的 Markdown 内容。为了避免长期运行的本地服务被滥用，单次 Markdown 限制为 4 MiB。停止命令后，临时构建文件会被删除。

## 本地文件服务器

`serve.py` 使用 Python 标准库启动支持目录浏览的静态文件服务器：

```bash
python3 <SKILL_DIR>/scripts/serve.py \
  --directory dist/docs \
  --host 127.0.0.1 \
  --port 8000
```

也可以读取与构建器相同的配置：

```bash
python3 <SKILL_DIR>/scripts/serve.py --config ai-docs.config.json
```

| CLI | JSON 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `-c, --config <file>` | 无 | 无 | 读取 AI Docs JSON 配置 |
| `-d, --directory <dir>` | `server.directory`，其次 `output.directory` | 当前目录 | 服务根目录 |
| `--host <address>` | `server.host` | `127.0.0.1` | 监听地址 |
| `-p, --port <port>` | `server.port` | `8000` | 端口；`0` 自动选择空闲端口 |
| `--open` / `--no-open` | `server.open` | `false` | 是否自动打开浏览器 |

目录浏览始终启用。默认只监听本机；只有明确需要局域网访问时才传 `--host 0.0.0.0`。

服务器逐个请求解析真实路径，并拒绝通过服务目录内软链接读取根目录外文件。

## 完整配置示例

```json
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
  "server": {
    "directory": "./dist/docs",
    "host": "127.0.0.1",
    "port": 8000,
    "open": false
  },
  "theme": "auto",
  "contentWidth": 80,
  "toc": true,
  "tocLayout": "right",
  "tocWidth": 20,
  "visualWidth": 960,
  "visualHeight": 520,
  "codeTools": true,
  "codeCollapse": false,
  "chartTools": true,
  "sourceToggle": true,
  "chartExport": true,
  "chartMaximize": true,
  "print": true,
  "themeControl": true,
  "markmapColors": {
    "light": ["#0077b6", "#00b4d8", "#48cae4", "#90e0ef", "#023e8a", "#0096c7"],
    "dark": ["#a78bfa", "#8b5cf6", "#c4b5fd", "#ddd6fe", "#6d28d9", "#7e22ce"]
  },
  "strict": true,
  "mermaidSecurity": "strict"
}
```

`markmapColors` 必须同时提供非空 `light` 和 `dark` 十六进制颜色数组。

## 优先级和相对路径

优先级从高到低：

1. CLI 参数。
2. JSON config。
3. 构建器默认值。

路径规则：

- CLI 的输入、输出和目录相对于执行命令时的当前工作目录。
- 配置中的 `output.directory`、`resources.config` 和 `server.directory` 相对于配置文件所在目录。
- `resources.directory` 相对于最终 HTML 所在目录。
- `resources.publicPath` 是浏览器 URL，不是文件系统路径。
- `--output` 指定完整路径时覆盖配置中的输出目录和文件名。

## 常用方案

### 默认离线单文件

```json
{
  "output": {
    "mode": "single",
    "directory": "./dist",
    "fileName": "report.html"
  },
  "strict": true
}
```

### Nginx 子路径部署

```json
{
  "output": {
    "mode": "multi",
    "directory": "./dist/docs",
    "fileName": "index.html"
  },
  "resources": {
    "directory": "static",
    "publicPath": "/docs/static/"
  }
}
```

### 草稿错误卡片

```bash
node <SKILL_DIR>/scripts/build.js \
  --input draft.md \
  --output draft.html \
  --no-strict
```

仅在用户需要“其他内容先可预览”时使用。正式交付前恢复严格模式并修复错误。
