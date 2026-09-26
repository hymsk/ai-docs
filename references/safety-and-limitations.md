# 安全、验证与能力边界

## 信任边界

Markdown、图表源码和配置都可能来自不可信输入。处理时：

- 保持 Markdown 原始 HTML 禁用。
- 不生成 `<script>`、事件属性、iframe、object、embed 或外部资源标签。
- 不把用户提供的 SVG 字符串直接注入正文。
- Markmap 源码不能包含原始 HTML。
- ECharts 只接受 JSON option，不执行函数或任意 JavaScript。
- Mermaid 默认 `securityLevel: strict`。
- 不把密码、token、cookie、私钥或内部 URL 写入文档示例。

`mermaidSecurity: loose` 会扩大 Mermaid 可表达内容和攻击面。只有 Markdown 来源可信、用户明确需要且结果仍要本地检查时才使用。

## 严格与非严格模式

默认严格模式在 ECharts 构建失败时返回非零退出码，并报告输入文件和代码块起始行。该行为适合正式交付和自动化。

`--no-strict` 仅把静态图失败改为页面中的错误卡片。它不会修复语法，也不会让错误图可用。适用场景是用户明确要查看其余草稿内容。

含原始 HTML 的 Markmap fence 会降级为普通代码块（不渲染思维导图）；危险路径和配置边界仍会被拒绝，不应通过非严格模式绕过。

`dot`/`graphviz` fence 不受支持：它会降级为普通代码块，代码块表头显示警示标识，悬浮可见具体原因，构建日志同时打印 `⚠️` 警告；该降级与 `--no-strict` 无关，不会让构建失败。请改用 Mermaid flowchart/subgraph。

## 渲染阶段

| 内容 | 阶段 | 构建退出码能否完整证明成功 |
| --- | --- | --- |
| Markdown、代码、表格 | 浏览器加载前已生成 | 基本可以 |
| ECharts | 构建期静态 SVG | 可以 |
| Mermaid | 浏览器运行时 | 不可以 |
| Markmap | 浏览器运行时 | 不可以 |
| KaTeX | 浏览器运行时转换 | 不完全可以 |

因此没有浏览器检查时，最终报告应写“构建已通过；Mermaid/Markmap 运行时效果未做浏览器验证”。

## 离线边界

单文件模式按内容把需要的脚本和样式内联到 HTML；多文件模式把相同依赖写入 HTML 旁的本地静态目录。两种模式的内置资源都不需要 CDN，资源清单也不接受远程 URL。但 Markdown 图片链接不受该清单限制，独立 HTML 打开后可能请求远端；严格模式不保证拒绝所有远程图片。

`resources.mode: "linked"`（`--resources-mode linked`）只影响单文件输出：HTML 引用 `publicPath` 托管的文件而不内联，此时页面不再能离线独立打开；Web 服务的预览与公开页面使用该模式，资源由同源 `/assets/` 端点提供。无论哪种模式，大体积图表引擎都排在渲染入口之后，内容先呈现、引擎就绪后再绘制图表。

单文件可以直接离线打开。多文件依赖本地 URL，正式部署应由 Nginx 等静态服务器提供，本地检查可使用 `serve.py`。默认 `./static/` 可直接服务输出目录；若 `resources.publicPath` 配置为 `/docs/static/`，应服务 `docs` 的上级目录并访问 `/docs/`。`resources.publicPath` 只改变 HTML 中的本地 URL，不能配置 URL 协议、query 或 fragment。服务端部署的 `linked` 模式走 `/assets/<fingerprint>/`，该路径必须由反代转发到后端（`nginx-template` 已包含）。

多文件构建拒绝静态目录路径中的软链接，以及资源目标软链接、悬空软链接和硬链接；所有资源通过预检和预读后才开始写入。`serve.py` 也拒绝通过服务根目录内软链接访问根目录外文件。

不要在文档中嵌入远程图片并声称“完全离线”。需要图片时，应先明确用户是否允许本地文件或 data URI；当前构建工作流不负责自动抓取和内联任意图片。

## Web MCP 发布边界

AI Docs Web MCP 是可选发布通道，不改变 renderer 的内容安全规则：

- `publish_document` 接收相对于公开目录的安全 Markdown 路径和 UTF-8 内容，不读取客户端文件路径，不接受任意服务端绝对路径或 zip。覆盖必须显式指定 `overwrite: true`，可用 `expected_sha256` 进行乐观并发校验。
- API/MCP 默认需要 Bearer Token；Token 保存在仓库外的私有凭据文件，不传给 Node renderer。
- 发布会把 Markdown 写入库内 `public/`，`/docs/` 在访问时实时渲染；发布返回 `render_status: "not_checked"`，不证明渲染成功。`list_documents` 提供受鉴权的公开文档分页浏览。
- HTML 与带 Markdown 后缀的原文 URL 不要求应用 Token；路径可预测且允许搜索引擎索引，不是 `unlisted` 私密分享。目录没有 README 时返回 404，不提供目录列表，但这不构成访问控制。
- 编辑或删除公开源文件会立即影响服务响应；没有 TTL、逐用户授权或删除 API，也无法撤回外部副本。敏感内容不得放入公开目录；私有分享必须由 Nginx/SSO/VPN 等保护全部文档及原文路径。
- `/preview/` 保护的是访问入口，而不是自动把其编辑的文件标记为私有；保存 `public/` 内文件同样会改变线上内容。
- 推荐服务继续监听 `127.0.0.1`，外网默认只暴露 `/docs/`；`/static/` 和旧 `/v1/renders` 已移除。公网 `/mcp` 仅在显式启用并具备 HTTPS、Bearer 鉴权和限流后开放。
- 修改 `server.host` 为 `0.0.0.0` 不会自动获得 HTTPS，并会扩大 API/MCP 攻击面。

普通任务中 MCP 不可用时，应明确回退为本地单文件 HTML；用户明确要求 Web URL 时则不能把本地路径伪装成发布成功。

## ECharts 限制

ECharts 在 Node.js 中 SSR 为静态 SVG：

- tooltip 不可交互。
- hover emphasis 不可交互。
- dataZoom、拖拽和点击事件不保留。
- JavaScript formatter/function 不是 JSON，不能使用。

需要真正交互式 dashboard 时，应选择其他实现，不要把 AI Docs 静态图描述成完整 ECharts 应用。

## Mermaid 与 Markmap 限制

- 两者依赖浏览器 SVG/layout API。
- Mermaid 语法错误会在对应图表位置显示，不应让其他正文消失。
- Markmap 会根据主题和容器变化重新布局。
- 超大图即使支持缩放，也可能不适合打印；应拆图或简化节点。

## KaTeX 字体

当前 Skill 没有完整打包 KaTeX WOFF2 字体。常见公式可用系统数学字体回退，但复杂字形和可伸缩定界符可能与官方 KaTeX 字体略有差异。不要声称像素级一致。

## 打印与 PDF

- 页面“打印”调用 `window.print()`。
- 打印时隐藏控制栏、目录和图表工具栏。
- 初始折叠的代码会展开。
- 分栏在打印时使用不受图表固有宽度影响的等宽列，显式尺寸图表在列宽受挤压时按声明比例缩小。
- 图表打印保留当前缩放倍率；视口达到页面上限后只放大框内内容，因此高倍率打印可能只保留当前视口区域。
- Markmap 会临时扩展以降低裁切风险。
- PDF 由浏览器打印目标生成，不是构建器直接导出。

页面的“下载 MD”会导出构建时内嵌的原始 Markdown，不包含 ECharts 预渲染时使用的内部占位符。

不要引入 `code-group` 或标签页式代码组织，因为隐藏面板容易导致打印遗漏。

## 浏览器验证清单

1. 单文件直接打开；多文件通过 Nginx 或 `serve.py` 访问，并确认静态资源请求成功。
2. 检查控制台和页面错误卡片。
3. 切换亮/暗主题。
4. 展开/收起目录并调整窗口宽度。
5. 操作 Mermaid/静态图缩放和导出。
6. 检查 Markmap 缩放和主题重绘。
7. 打开打印预览，确认分页、分栏、代码和图表。

环境没有浏览器时保留该清单给用户，不伪造视觉验证结果。

可选自动检查见 `tests/browser-smoke.py`（开发环境需 Python Playwright 与 Chromium）。它验证全功能样例的执行错误、资源请求、主题切换、源码下载及 PDF 生成，不证明任意输入安全，也不能代替人工检查复杂公式字形、分页和图表裁切。

## 非当前能力

仓库中的未来设计可能提到 Intent Schema、AG-UI、json-render、React Flow、Monaco Diff、SQLite、Next.js 或审批运行时。这些不是本 Skill 当前离线渲染器的实现能力，不能在交付中当作已完成特性。
