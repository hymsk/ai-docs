# Changelog

## 未发布

- 服务端渲染不再每次把 3.4MB 级图表引擎内联进 HTML：预览与公开页面改用 `resources.mode: "linked"`，引用 `/assets/<fingerprint>/<file>` 托管的资源（manifest 白名单、无鉴权只读、`immutable` 缓存、指纹随 renderer 版本切换），同时把 Mermaid/D3/Markmap 排到渲染入口之后，内容先呈现、引擎就绪后再绘制图表。CLI 默认仍是 `inline` 单文件自包含；新增 `--resources-mode`、`--emit-resources` 与同源 `'self'` 的 CSP 白名单，`nginx-template` 同步包含 `/assets/` 转发。浏览器实测同文档首屏由约 1.8s 降至约 0.25s，二次打开命中资源缓存后引擎不再重复下载。
- 内容级图表问题改为降级而非失败：`dot`/`graphviz` fence、非法 `size=` 参数、含原始 HTML 的 Markmap 不再让构建以非零退出，而是按普通代码块输出。降级块的表头显示「⚠ 图表」标识，悬浮可见具体原因，构建日志同时打印 `⚠️` 警告；ECharts 严格校验、配置/资源/IO 等基础设施错误行为不变。

## 1.0.0rc1

首个公开候选版本，公开兼容基线自此开始维护。能力与使用说明见 [`README.md`](README.md)；第三方组件许可与来源见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
