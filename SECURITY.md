# Security Policy

## Reporting

优先使用仓库 Security 页的 GitHub Private Vulnerability Reporting（需维护者启用）。若入口不可用，请只通过公开 Issue 请求私密联系渠道，不公开漏洞细节。不要在公开 Issue 中提交 token、cookie、私钥、Host 用户配置、发布文档内容、内部 URL 或包含私人服务信息的日志。

## Security Model

- 构建器及内置脚本/样式不依赖 CDN；资源清单拒绝远程 URL。但 Markdown 图片可以引用远程地址，独立 HTML 打开后可能请求它们。对不可信 Markdown，发布或打开前检查并移除外部图片；不能把内置资源离线等同于任何输入都不会联网。
- 默认启用严格输入校验和 Mermaid strict security；原始 HTML、脚本、事件属性与任意嵌入会被拒绝。`dot`/`graphviz`、非法 `size=` 和含原始 HTML 的 Markmap 等内容级图表问题降级为普通代码块，不执行也不渲染。
- Web API 与 MCP 默认要求 Bearer Token；Token 只保存在仓库外的私有凭据文件中，不传给 Node renderer。
- 安装器默认使用用户级 XDG 路径，并将配置和凭据保持为 `0600`；system scope 必须显式指定。
- 外网默认只公开 `/docs/` 与只读渲染器资源 `/assets/<fingerprint>/<file>`，后端继续监听 loopback。`nginx-template` 默认拒绝公网预览和 session；仅显式 `--expose-preview` 且后端预览已开启时生成带 Basic Auth 的代理，后端预览禁用时该参数会报错。公网 MCP 独立使用 `--expose-mcp`。模板不会自动应用或 reload。`/static/` 和旧 `/v1/renders` 已移除，不公开 `/healthz`。
- `/assets/` 端点只按 `assets/default-resources.json` 白名单返回经过构建器同套转换的 vendor 文件，请求文件名不匹配或 renderer 指纹不匹配即 404，不做目录遍历；URL 内嵌指纹使版本更新自动切换新路径并可长期缓存。它无需应用 Token（srcdoc 子资源请求无法携带 Bearer 头），因此只暴露开源依赖字节，不暴露任何文档内容、库路径或配置。
- 预览与公开页面的 CSP 允许 `script-src`/`style-src` 为 `'unsafe-inline' 'self'`，以支持服务端托管的同源引用型资源；`default-src 'none'`、`connect-src 'none'` 与远程子资源禁令不变，Markdown 中的图片仍受原有边界约束。
- 库内 `public/`（可配置）是公开区域：HTML 和 Markdown 原文无需应用 Token，URL 按文件路径生成，并可能被搜索引擎索引。它不是高熵链接或 `unlisted` 私密分享，不能存放机密内容。
- 编辑公开目录中的 Markdown 会即时改变线上内容；删除源文件会使服务不再提供该文档，但不能撤回外部副本。没有 TTL、独立用户权限或文档删除 API。需要私有分享时，必须在边缘层对文档及原文路径实施访问控制。
- `/preview/` 使用 Token 交换的会话 cookie，不接受 URL Token；库内非公开文件仅经受保护预览访问。编辑器能编辑公开子目录，因此“预览保存”不等于“永不发布”。

更完整的输入、浏览器和发布边界见 [`references/safety-and-limitations.md`](references/safety-and-limitations.md)。

## Vendored dependency review

精确版本、公告快照及未决项见 `scripts/vendor-provenance.json` 和 `licenses/manifest.json`，实际配置与处置见 [依赖安全跟踪](references/dependency-security.md)。构建后浏览器会执行图表代码，不要把不可信输入当作可靠内容隔离边界。
