# 内嵌依赖安全跟踪

本页记录实际配置与待处理条件，不是“没有漏洞”的证明。精确 bundle、公告来源及核查时间见 `scripts/vendor-provenance.json`，第三方归属见 `licenses/manifest.json`。

## 已采取措施

- 直接 Mermaid 从 11.4.0 升级为同主版本 11.17.2，直接 markdown-it 从 14.1.0 升级为 14.3.2。采用上游精确发布字节，不直接修补 vendor。
- 继续使用 Mermaid strict、禁用 Markdown 原始 HTML；Web 渲染保留既有 CSP。功能测试不能替代安全回归，也不能单靠版本号作全面安全保证。
- `licenses/verify-provenance.py` 可复核精确 tarball、文件与许可载荷；该命令不在线刷新公告，维护者需要定期重新核查。

## 待跟踪公告

### Mermaid 内嵌 DOMPurify

11.17.2 bundle 内嵌 DOMPurify 3.4.12，仍在 [GHSA-55q2-fjhq-7xh7](https://github.com/cure53/DOMPurify/security/advisories/GHSA-55q2-fjhq-7xh7) 的版本范围内；上游修复为 3.4.13。核查的 Mermaid 12.0.0 也包含 3.4.12，单纯跨主版本升级不能解决。

该公告要求 `IN_PLACE` 与移除元素的 hook 条件。检查当前 Mermaid sourcemap，实际 sanitize 调用点使用文本输入，没有发现 Mermaid 源码启用 `IN_PLACE`；这降低了默认调用路径的可达性疑虑，但不是完整利用性证明。不得通过配置注入、自定义 hook 或 Mermaid loose 模式扩大边界。后续有合适的上游 bundle 时升级并重做浏览器及安全回归；若选择自行构建，须另行建立可复现构建与来源规则，不能把自建文件标为上游原版。

### Markmap 内嵌 markdown-it

Markmap 0.17.2 发布锁文件锁定 markdown-it 14.1.0，直接 vendor 升级不会替换该内部副本。核查的 Markmap 0.18.12 发布锁也仍为该版本。

跟踪公告：

- [GHSA-6v5v-wf23-fmfq](https://github.com/markdown-it/markdown-it/security/advisories/GHSA-6v5v-wf23-fmfq)
- [GHSA-253c-mchw-3w2r](https://github.com/markdown-it/markdown-it/security/advisories/GHSA-253c-mchw-3w2r)
- [GHSA-r7fv-28h4-cvq7](https://github.com/markdown-it/markdown-it/security/advisories/GHSA-r7fv-28h4-cvq7)

当前 `new markmap.Transformer().md.options` 的 `typographer` 与 `linkify` 均为 false；可选浏览器测试对此设有断言，避免将相关已知复杂度路径意外开启。仍须跟踪内部版本更新，不能对其他解析路径和任意大输入推导“无 DoS 风险”。当前不接收用户指定的 Markmap 插件或解析器配置。

## 发布判断

许可缺口、公告命中、实际可达性及修复状态是不同维度。公开源码可如实披露未决问题；正式推荐处理不可信内容或公网部署前，应完成针对实际输入路径的安全评估。平台漏洞报告入口、维护者接受残余风险以及公开范围决定不能由本地扫描自动代替。
