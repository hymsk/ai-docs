---
name: ai-docs
description: 创建、改写、发布并验证富 Markdown 和 HTML 文档。默认优先使用已配置的 AI Docs Web MCP 返回可访问 URL；MCP 不可用时回退到自带离线渲染器生成单文件 HTML。支持 Mermaid、ECharts、Markmap、KaTeX、代码高亮、表格、2-4 列布局、主题、目录、图表导出、Nginx HTTPS 发布、本地目录浏览和浏览器打印；同时内置"文档生成 Agent"设计方法论（需求/代码解释/架构文档生成、Agentic UX、防幻觉溯源、增量防漂移、质量评估）。只要用户提到 AI Docs、Markdown 转 HTML、网页发布、可视化技术文档、单文件报告、多文件静态站点、带图表的方案文档，或需要设计文档生成 Agent，就应使用本技能。Use when creating or publishing rich documents and when designing documentation-generation agents.
developer: hymsk
compatibility: 构建需要 Node.js 18+ 和文件系统访问；Python 工具需要 Python 3.9+；Web MCP 管理器需要 Linux 与 systemd；Mermaid、Markmap、主题切换及打印效果的最终验证需要现代浏览器。
---

# AI Docs

本技能覆盖两类任务，先按用户意图路由：

| 任务 | 说明 | 入口 |
| --- | --- | --- |
| **A. 写文档** | 把信息组织成可维护的 Markdown；已配置 AI Docs Web MCP 时优先发布为 Web URL，否则生成本地单文件 HTML | 继续阅读本文件下文（核心原则 → 完整工作流） |
| **B. 设计文档生成 Agent** | 构建、评审或改进"生成文档的 Agent"：需求文档（PRD/SRS）、代码解释（wiki/README）、架构文档（C4/arc42/ADR），以及交互设计、防幻觉溯源、增量防漂移、质量评估 | 先读 `references/agent-design/00-方法论总览.md`，再按其路由深入对应报告 |

两类任务可以串联：用任务 B 的方法论设计生成流水线，用任务 A 的渲染器作为其确定性输出层（模板驱动 + Diagram-as-code + 构建期校验，正是方法论推荐的"确定性打底"形态）。

任务 A 的交付以事实准确、图表选型合适、源码可继续编辑和输出可验证为目标。

## 核心原则

> 以下各节为任务 A（写文档）的执行规范；任务 B 请直接转入 `references/agent-design/`。

- 始终先生成或更新 `.md` 源文件。若当前会话已经提供 `ai-docs` MCP 的 `publish_document` Tool，默认优先调用它，把文档写入公开文档目录并交付返回的 `public_url`；未提供 Tool、调用不可用或普通发布失败时，使用 `<SKILL_DIR>/scripts/build.js` 回退生成本地单文件 HTML，并明确说明回退原因。
- 用户明确要求“只在本地”“不要发布”或“单文件 HTML”时，不调用 MCP。用户明确要求 Web URL 而 MCP 不可用时，不伪造 URL；报告阻塞，并询问是否进入 MCP 配置流程。
- MCP 的安装、升级、Host 注册、Nginx、端口和 TLS 配置有外部副作用。只有用户明确要求配置、启用、部署或修复 AI Docs Web MCP 时，才读取 `references/web-mcp-setup.md`；普通文档任务不得加载或执行该流程。
- 部署引导遵循 `references/web-mcp-setup.md` 的“交互式部署引导”：基础配置验证后，先询问是否配置 Nginx Auth，并让用户选择自行交互式设置账号密码或授权生成；处理完该选择后，再单独询问是否开放公网 MCP。不得把域名部署等同于公网 MCP 授权；无论是否开放，都说明凭据文件位置和用户在本机查询 Token 的方式，不在会话中输出 Token。
- 本地回退使用 `<SKILL_DIR>/scripts/build.js`，不重新实现渲染器，也不引用 CDN。需要快速访问本地多文件目录时使用 `<SKILL_DIR>/scripts/serve.py`；需要左侧编辑、右侧实时查看结果时使用 `<SKILL_DIR>/scripts/preview.js` 或 `build.js --preview`。
- 需要长期常驻的浏览器预览或 Markdown 目录浏览时，使用 Web MCP 的 `/preview/` 路由：它通过无 URL Token 的 POST 登录换取会话 cookie，再提供库目录列表和左右分栏编辑器。该路由的启用与公网暴露属于部署动作，仍需用户明确要求。
- 先根据表达目的选择组件，再写图表语法；不要为了“看起来丰富”堆叠无信息增益的图表。
- 默认保持 `strict: true` 和 `mermaidSecurity: strict`。只有来源可信且用户确有需要时才考虑 Mermaid `loose`。
- 不在 Markdown 中使用原始 HTML、脚本、事件属性或任意嵌入内容。分栏只使用受限的 `::: columns` 语法。
- 不使用 `code-group`，也不承诺直接生成 PDF。需要 PDF 时使用生成页面的浏览器原生打印；需要源文件时使用页面的“下载 MD”。
- 把 ECharts 构建成功和 Mermaid/Markmap 浏览器运行成功区分开；未做浏览器检查时明确说明。
- 不使用 `dot`/`graphviz` fence。AI Docs 不内置 Graphviz，已有 DOT 图应迁移为 Mermaid flowchart；残留 fence 会降级为代码块并在表头给出警示标识，不中断构建。

## 资源定位

将包含本文件的目录记为 `<SKILL_DIR>`。不要依赖仓库绝对路径，安装后的 Skill 可能位于任意宿主目录。

按任务读取以下资源：

| 资源 | 何时读取 |
| --- | --- |
| `references/agent-design/00-方法论总览.md` | 任务 B：设计/评审文档生成 Agent 时首先阅读，含八条铁律、工程决策速查表与方向路由 |
| `references/agent-design/README.md` | 任务 B：需要五方向调研总览、共同结论详注或阅读路径时 |
| `references/authoring-guide.md` | 新建或重构整篇文档、决定信息层级、尺寸和分栏时 |
| `references/cli-and-config.md` | 需要完整 CLI、JSON 配置、优先级或路径行为时 |
| `references/safety-and-limitations.md` | 处理不可信输入、渲染失败、浏览器验证、打印或能力边界时 |
| `references/web-mcp-setup.md` | **仅**用户明确要求安装、配置、升级、注册或排障 AI Docs Web MCP 时 |
| `references/web-mcp-external-access.md` | **仅**用户明确要求域名、HTTPS、Nginx、外网 URL 或直接公网监听时 |
| `references/components/index.json` | 不确定应选哪类图表或要按用途检索绘图方法时 |
| `references/components/<component>/index.md` | 确定组件后，先读取该组件概述和详细文档索引 |
| `assets/document-template.md` | 从零创建标准报告时 |
| `assets/default-config.json` | 需要稳定复用默认页面设置时 |
| `assets/default-resources.json` | 维护按需内联、多文件复制或 linked 托管导出的本地资源清单时；普通文档任务通常无需读取 |
| `assets/full-example.md` | 需要查看全部已支持语法的组合示例时 |

可直接查询组件目录：

```bash
node <SKILL_DIR>/scripts/build-component-index.js --query "依赖 拓扑"
```

## 组件选择

| 表达目标 | 首选组件 | 原因 |
| --- | --- | --- |
| 流程、分支、依赖、调用链、网络拓扑、状态迁移、时序、甘特、ER、简单占比 | Mermaid | 语法紧凑，支持 flowchart 与 subgraph，适合文档内维护 |
| 柱、线、饼、散点、雷达等定量数据 | ECharts | 数据编码、坐标轴和系列表达能力强 |
| 提纲、知识树、主题分解 | Markmap | Markdown 层级可直接转为思维导图 |
| 行内或块级数学表达 | KaTeX | 公式比图片更清晰、可复制 |
| 并列比较、说明与图表同屏 | `::: columns` | 保持 Markdown 源码和打印布局 |
| 配置、源码、命令、SQL | fenced code block | 提供语言高亮、复制和可选折叠 |
| 对比矩阵、字段说明、清单 | Markdown table | 扫读效率通常高于图表 |

如果一个表格已能准确回答问题，不要改成图表。数据图必须有可核对的数据来源；关系图必须明确节点和边的含义。

## 完整工作流

### 1. 确认交付

从用户消息和现有文件中确定：

- 输入是新建内容还是已有 Markdown。
- Markdown 和 HTML 的目标路径，是否允许覆盖已有 HTML。
- 文档标题、读者、用途和主要结论。
- 是否需要目录、主题控制、代码折叠、图表导出、分栏和打印。
- 用户是否明确要求本地单文件、Web URL，或允许按“可用 MCP 优先、本地单文件回退”的默认路由。
- 图表数据、关系和时间信息是否完整；缺少关键事实时先询问，不编造。

不影响内容方向的页面细节可采用默认值：目录右侧停靠、正文宽度 80%、图表上限 960x520、主题跟随系统、严格模式开启。

### 2. 检查输入与现有规则

- 读取已有 Markdown、关联数据和项目内适用规则。
- 保留用户已有内容和术语，除非用户要求重写。
- 识别适合表格、代码、公式或图表的信息，不重复表达相同内容。
- 对外部或不可信 Markdown，读取 `references/safety-and-limitations.md` 后再处理。

### 3. 设计文档结构

先写标题层级和文字结论，再补图表。推荐结构：

1. 标题和摘要。
2. 背景、范围或关键指标。
3. 主体章节，每张图前说明它回答的问题。
4. 风险、限制或待决事项。
5. 必要的附录、代码或数据表。

从零创建时可基于：

```bash
cp <SKILL_DIR>/assets/document-template.md /path/to/report.md
```

只有实际执行环境允许复制文件时才运行命令；否则直接按模板结构创建目标文件。

### 4. 编写 Markdown 与图表

- 普通代码块标注语言，例如 `json`、`typescript`、`bash`。
- 图表 fence 只添加受支持的 `size=<宽>x<高>`；宽 240-2400，高 160-1600，单位 px。
- 同一行或同一比较组中的图表使用一致尺寸，例如都用 `size=640x360`；分栏受挤压时会按同一比例同步缩小。
- 分栏只使用 2-4 个 `::: column`，并考虑移动端会堆叠、打印仍保留列。
- ECharts fence 内必须是 JSON option，不能写 JavaScript 函数、变量或注释。
- Markmap fence 内不能包含原始 HTML。

确定组件后读取对应详细方法。例如：

```text
references/components/mermaid/flowchart.md
references/components/echarts/bar-line.md
references/components/markmap/hierarchy.md
```

### 5. 选择交付通道与配置

按以下顺序路由，不通过读取本机私有配置来猜测 Tool 是否可用：

发布前先确认用户允许将该内容公开：MCP 可用不等于获得公开内部资料或机密内容的授权。含敏感内容或分享范围不清楚时先澄清；不确定时只生成本地文件。不要把 `/preview/` 的鉴权误当成 `/docs/` 的鉴权。

1. 用户明确要求本地或单文件：直接本地构建。
2. 当前会话已经暴露 `ai-docs` MCP Tool：调用 `publish_document`，传入公开目录内的相对路径和完整 Markdown 内容。成功后交付 `public_url`；`overwrite` 默认为 `false`，同名文档已存在时会返回 `document_exists` 及当前 `sha256`，需要覆盖时显式设置 `overwrite: true`（可附 `expected_sha256` 做乐观并发控制）。发布只写入源文件，页面在访问时实时渲染；`render_status: "not_checked"` 表示发布成功不保证渲染无误。
3. Tool 未暴露：使用本地单文件构建，不把“未安装”和“当前会话未加载”混为一谈。
4. 普通任务中 MCP 调用失败：报告错误摘要后本地回退。
5. 用户明确要求 Web URL 时 MCP 调用失败：报告发布失败；可同时提供本地文件，但不能声称任务已完成远程发布。

MCP Tool 接收内容而不是客户端路径：

```json
{
  "path": "guide/report.md",
  "markdown": "# Report\n\n正文"
}
```

发布后渲染地址省略 `.md` 后缀（上例为 `/docs/guide/report`）；目录的 `README.md` 即该目录的索引页。可用 `list_documents` 查看公开目录现有文档，再决定路径是否冲突。不得向远程服务发送任意本地路径、目录、zip、凭据或与文档无关的文件。

短任务可直接使用 CLI；需要重复构建或设置较多时创建 JSON config。CLI 值优先于 config。

默认构建：

```bash
node <SKILL_DIR>/scripts/build.js \
  --input /path/to/report.md \
  --output /path/to/report.html
```

多文件本地构建：

```bash
node <SKILL_DIR>/scripts/build.js \
  --input /path/to/report.md \
  --output-mode multi \
  --output-dir /path/to/site \
  --output-name index.html
```

默认生成 `/path/to/site/index.html` 与 `/path/to/site/static/`。部署在 Nginx 子路径时增加 `--public-path /docs/static/`；它只改变 HTML 中的 URL，不改变磁盘写入目录。

使用配置：

```bash
node <SKILL_DIR>/scripts/build.js \
  --input /path/to/report.md \
  --output /path/to/report.html \
  --config /path/to/ai-docs.config.json
```

需要单次覆盖时把 CLI 放在 config 后仍可生效：

```bash
node <SKILL_DIR>/scripts/build.js \
  --input /path/to/report.md \
  --config /path/to/ai-docs.config.json \
  --theme dark \
  --code-collapse
```

完整参数和配置字段见 `references/cli-and-config.md`。

需要在本地直接编辑并实时查看 renderer 效果时：

```bash
node <SKILL_DIR>/scripts/preview.js --input /path/to/report.md --open
```

页面左侧是 Markdown 编辑器，右侧为经同一 `build.js` 渲染器生成的隔离预览。预览默认仅监听 loopback；编辑内容只在点击“保存”或按 `Ctrl/⌘ + S` 后才会写回 Markdown。

已安装并启用 Web MCP 预览时，同一个编辑体验常驻在服务端：

```text
http://127.0.0.1:18080/preview/
```

该地址在没有会话时跳转到登录页；登录页通过 `POST /preview/session` 和 `Authorization: Bearer ...` 下发 `HttpOnly` + `SameSite=Lax` 会话 cookie。不要使用或推荐 `?token=`，服务会拒绝 URL Token。`/preview/` 列出库目录中的 Markdown，点击进入 `/preview/edit?path=...`。渲染与保存分别调用 `/preview/api/render` 和 `/preview/api/save`，都由 cookie 会话鉴权；`preview.write_back: false` 时保存返回 `403`。库目录由 `library_directory` 指定，默认位于私有数据目录；其中由 `public_directory`（默认 `public/`）指定的子目录是公开渲染源，访问 `/docs/` 时实时渲染，其余部分不对外发布；保存受文件数、总字节数和路径深度配额约束，超额只拒绝、不自动删除用户文件。

### 6. 构建并修复

1. 确认输出目标正确；构建器会创建缺失的输出目录。
2. 运行构建命令并检查退出码。
3. 严格模式失败时，按错误中的输入路径和代码块起始行定位。
4. 修复源 Markdown 或图表语法，不要用 `--no-strict` 掩盖可修复错误。
5. 只有用户明确希望保留错误卡片用于草稿预览时才使用 `--no-strict`。
6. 多文件成品需要通过 HTTP 访问；默认 `./static/` 可直接服务站点目录。若 `publicPath` 是 `/docs/static/` 这类 Nginx 根路径，则服务其上级目录并访问 `/docs/`。

常见失败处理：

| 现象 | 处理 |
| --- | --- |
| ECharts JSON 解析失败 | 删除注释、尾逗号、函数和未加引号的键 |
| `dot`/`graphviz` fence 未渲染成图（表头警示） | 将依赖、调用关系或拓扑迁移为 Mermaid flowchart/subgraph |
| 图表 size 未生效（表头警示） | 只保留 `size=宽x高`，并满足范围 |
| Markmap 未渲染成思维导图（表头警示） | 改成普通 Markdown 文本或链接语法 |
| 输出覆盖输入被拒绝 | 选择不同的 `.html` 路径，不绕过保护 |

### 7. 验证成品

至少执行：

- 确认命令退出码为 0，HTML 文件存在且非空。
- 确认没有远程 `script`、`link`、`img`、`iframe` 等资源引用。
- 多文件模式确认所有 `script` 和 `link` 都指向目标目录内的本地资源 URL，且静态依赖文件存在。
- 检查标题、目录、代码块和静态 ECharts 是否存在。

如环境有现代浏览器，再检查：

- Mermaid 和 Markmap 是否完成运行时渲染。
- 亮/暗主题切换和目录布局。
- 图表源码切换、缩放、SVG/PNG 导出。
- 分栏在桌面和移动宽度下的表现。
- 打印预览是否隐藏工具栏、展开折叠代码并完整显示图表。

没有浏览器能力时，不宣称 Mermaid、Markmap 或打印视觉效果已验证。

### 8. 交付说明

最终简短报告：

- Markdown 源文件，以及远程 `public_url` 或本地 HTML 成品路径。
- 实际通道（`ai-docs` MCP 或本地 renderer）；发生回退时给出原因。
- 使用的 config 或关键 CLI 选项。
- 包含的图表类型及其表达目的。
- 已执行的构建/验证命令。
- 未做的浏览器检查、字体回退或其他已知限制。

## 维护 Skill 自身

修改组件参考或索引后运行：

```bash
node <SKILL_DIR>/scripts/build-component-index.js
node <SKILL_DIR>/scripts/build-component-index.js --check
node <SKILL_DIR>/tests/component-index.test.js
node <SKILL_DIR>/tests/build.test.js
node <SKILL_DIR>/tests/output-modes.test.js
node <SKILL_DIR>/tests/serve.test.js
node <SKILL_DIR>/tests/preview.test.js
python3 -m unittest discover -s <SKILL_DIR>/web-mcp/tests -p 'test_*.py'
```

`build-component-index.js` 会从每个组件的 `index.json` 生成总目录，并校验所有相对文档路径。不要手工编辑生成的 `references/components/index.json`。

## 当前边界

- ECharts 在构建期生成亮/暗静态 SVG；tooltip、hover emphasis 等浏览器交互不会保留。
- `dot`/`graphviz` fence 不受支持，会降级为普通代码块（表头警示 + 悬浮原因）而不让构建失败，与 `--no-strict` 无关；请迁移为 Mermaid flowchart。
- Mermaid 和 Markmap 在页面打开后渲染，构建成功不等于它们已在浏览器中成功。
- KaTeX 字体没有完整内联，复杂字形和可伸缩定界符可能使用系统字体回退。
- 页面使用浏览器原生搜索和打印，不提供自定义搜索控件或直接 PDF 生成。
- 本地 renderer 仅支持单文件和本地多文件资源，不支持 CDN 或任意远程资源 URL；Web MCP 将 Markdown 写入公开目录，并在访问 `/docs/` 时实时渲染。
- Web MCP 每次发布一份 Markdown；HTML 和 Markdown 原文无需应用 Token，路径可预测且可能被搜索引擎索引，不是 `unlisted` 私密分享。发布返回 `render_status: "not_checked"`，不能当作渲染验证成功。没有 TTL 或删除 API；删除公开源文件会使服务不再提供内容，但不能撤回外部副本。
- Web MCP `/preview/` 会话 cookie 由 API token 派生签名，默认有效期 12 小时，可配置到 7 天且签发、验证使用同一时长；换 token 会使旧会话立即失效。HTTPS 配置加 `Secure`，本地 HTTP 不加；服务不使用不受信任的代理协议头推断安全连接。会话 cookie 不是独立账号体系，公网部署仍需在边缘层额外加 Basic Auth、SSO 或 VPN。
- `/preview/` 入口受会话保护；库中非公开文件不经 `/docs/` 提供，但保存公开子目录内的文件会立即更新线上内容。路径校验拒绝 `..`、隐藏段、绝对路径、非 Markdown 后缀和符号链接穿越。单文件上限为 `max_upload_bytes`，库配额由 `library_limits` 控制，默认 `1000` 文件、`50 MiB` 总量和 `8` 段路径深度；超额不删除文件。
- 预览渲染受 `max_concurrent_renders` 约束；公开冷渲染还受 `public_docs` 并发与超时约束。公开访问失败统一返回简洁 404，不能仅凭状态码诊断渲染错误。预览 `srcdoc` 注入严格 CSP，阻止远程子资源自动联网。
- 本 Skill 只覆盖当前离线 Markdown 渲染器，不代表未来的 Intent Schema、AG-UI、Next.js、SQLite 或审批运行时已经实现。
- `references/agent-design/` 是文档生成 Agent 的设计方法论与调研结论，不含可直接运行的 Agent 实现代码；落地实现需按其中"落地路线"章节自行构建。
