# Changelog

## 未发布

- 内容级图表问题改为降级而非失败：`dot`/`graphviz` fence、非法 `size=` 参数、含原始 HTML 的 Markmap 不再让构建以非零退出，而是按普通代码块输出。降级块的表头显示「⚠ 图表」标识，悬浮可见具体原因，构建日志同时打印 `⚠️` 警告；ECharts 严格校验、配置/资源/IO 等基础设施错误行为不变。

## 1.0.0rc1

首个公开候选版本，公开兼容基线自此开始维护。能力与使用说明见 [`README.md`](README.md)；第三方组件许可与来源见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
