# Third-Party Notices

AI Docs 自有代码使用 `AGPL-3.0-or-later`。`scripts/vendor/` 中的预构建浏览器资源仍遵循各自的上游许可证；本文件不改变或替代这些许可证。

下表记录实际分发的 10 个 vendor 文件的版本、来源及 SHA-256。更新只使用公开 npm tarball 中的预构建文件，不本地重打包、不引入运行时 npm 依赖、不修改压缩后的程序。日常检查核对本地文件与清单；更新时核对相应上游发布文件。SHA-256 用于完整性校验，不构成法律认证。

离线许可正文、必要的已识别 NOTICE 和 bundle 许可注释保存在 [`licenses/`](./licenses/README.md)；[`licenses/manifest.json`](./licenses/manifest.json) 记录每个文件的来源 URL、包内路径、原始/本地摘要、提取范围与未决缺口。包的顶层许可证不代表所有内嵌依赖都采用相同许可证。

| 本地文件 | 上游 package / 版本 | package 内路径 | 许可证 | SHA-256 |
| --- | --- | --- | --- | --- |
| `scripts/vendor/markdown-it.min.js` | [`markdown-it@14.3.2`](https://www.npmjs.com/package/markdown-it/v/14.3.2) | `dist/markdown-it.min.js` | [MIT](./licenses/markdown-it-14.3.2/LICENSE)；另见内嵌依赖 | `e32488403e2e565ac12a9669bfdf2b1b876eb0a5c84f8e0699884b562d18eb52` |
| `scripts/vendor/highlight.min.js` | [`@highlightjs/cdn-assets@11.11.1`](https://www.npmjs.com/package/@highlightjs/cdn-assets/v/11.11.1) | `highlight.min.js` | [BSD-3-Clause](./licenses/highlight.js-11.11.1/LICENSE) | `c4a399dd6f488bc97a3546e3476747b3e714c99c57b9473154c6fb8d259b9381` |
| `scripts/vendor/highlight-styles.css` | [`highlight.js@11.11.1`](https://www.npmjs.com/package/highlight.js/v/11.11.1) | `styles/github.min.css` | [BSD-3-Clause](./licenses/highlight.js-11.11.1/LICENSE) | `3a9a5def8b9c311e5ae43abde85c63133185eed4f0d9f67fea4b00a8308cf066` |
| `scripts/vendor/mermaid.min.js` | [`mermaid@11.17.2`](https://www.npmjs.com/package/mermaid/v/11.17.2) | `dist/mermaid.min.js` | [MIT](./licenses/mermaid-11.17.2/LICENSE)；另见下方内嵌依赖与缺口 | `581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8` |
| `scripts/vendor/d3.min.js` | [`d3@7.8.5`](https://www.npmjs.com/package/d3/v/7.8.5) | `dist/d3.min.js` | [ISC](./licenses/d3-7.8.5/LICENSE) | `d6b03aefc9f6c44c7bc78713679c78c295028fa914319119e5cc4b4954855b1c` |
| `scripts/vendor/katex.min.js` | [`katex@0.16.21`](https://www.npmjs.com/package/katex/v/0.16.21) | `dist/katex.min.js` | [MIT](./licenses/katex-0.16.21/LICENSE) | `863811e2baa0849c77bc92d26d44f4d0a4843c2a8ab52c462017dea57316e4d8` |
| `scripts/vendor/katex.min.css` | [`katex@0.16.21`](https://www.npmjs.com/package/katex/v/0.16.21) | `dist/katex.min.css` | [MIT](./licenses/katex-0.16.21/LICENSE) | `f787891b550d554c214aa8902f39ac46df2dbd48fdec500a2040a5dce1e8ab58` |
| `scripts/vendor/markmap-lib.browser.js` | [`markmap-lib@0.17.2`](https://www.npmjs.com/package/markmap-lib/v/0.17.2) | `dist/browser/index.iife.js` | [MIT](./licenses/markmap-lib-0.17.2/LICENSE)；另见内嵌依赖 | `7fa851eda0f0eaf08a88d8894c843a987934bc029dbe0df5901698897ae4131b` |
| `scripts/vendor/markmap-view.browser.js` | [`markmap-view@0.17.2`](https://www.npmjs.com/package/markmap-view/v/0.17.2) | `dist/browser/index.js` | [MIT](./licenses/markmap-view-0.17.2/LICENSE)；另见内嵌依赖 | `98770326cd0014f7bcfaaf906316ab6aba170239a93098d5857298f59be405ab` |
| `scripts/vendor/echarts.min.js` | [`echarts@5.6.0`](https://www.npmjs.com/package/echarts/v/5.6.0) | `dist/echarts.min.js` | [Apache-2.0 与 subcomponents 声明](./licenses/echarts-5.6.0/LICENSE)、[NOTICE](./licenses/echarts-5.6.0/NOTICE) | `bf4a223524e40b77c304bec67e1222cf551f14880cf42c69dc046558e11c07b1` |

包内路径在 tarball 中统一带 `package/` 前缀。来源修正：`highlight.js@11.11.1` tarball 不含 `highlight.min.js`，JS 实际匹配官方 CDN assets 包；CSS 在两包中逐字节相同，LICENSE 也相同。当前 `markmap-lib` 与上游完全一致，旧版“版本标识清理”的说法没有字节证据支持，故移除。

## 随附的许可材料

除表中顶层 LICENSE，还保留上游 bundle 声明和已收集的内嵌依赖材料，不将整个 bundle 一概视为顶层许可证：

- Mermaid 的 [`Bundled license information`](./licenses/mermaid-11.17.2/BUNDLED-NOTICES.txt)，以及已识别的 DOMPurify、KaTeX、D3、Cytoscape 等许可和归属。
- markdown-it、Highlight.js、D3 的 banner 与依赖材料；Highlight.js CSS 的 [theme 声明](./licenses/highlight.js-11.11.1/GITHUB-THEME-NOTICE.txt)。
- Markmap 的 [lib](./licenses/markmap-lib-0.17.2/BUNDLED-NOTICES.txt) / [view](./licenses/markmap-view-0.17.2/BUNDLED-NOTICES.txt) 声明、[d3-flextree WTFPL](./licenses/d3-flextree-2.1.2/LICENSE) 及已收集的候选依赖许可；候选集合不等同于实际内嵌清单。
- ECharts 的 [NOTICE](./licenses/echarts-5.6.0/NOTICE)、[D3 BSD 条款](./licenses/echarts-5.6.0/licenses/LICENSE-d3)、ZRender 与 tslib 材料。ECharts 引用的旧 D3 BSD 不能用独立 D3 的 ISC 替代。

全部材料及其关联见 [manifest](./licenses/manifest.json)。详细 source map、锁文件和逐成员比对记录留在 [来源说明](./licenses/README.md) 与 [`vendor-provenance.json`](./scripts/vendor-provenance.json)，无需为日常使用逐项阅读或重做审计。

## 分发要求与维护范围

分发包含这些 vendor 的源码包、静态目录或 HTML 时，应一并提供本文件与适用的离线许可证/NOTICE，保留嵌入代码里的版权和许可声明。Renderer 在单文件和多文件 HTML 中嵌入当前已收集的许可材料，并提供可展开的“软件许可证”区域；Web MCP 安装器也将这些文件复制到 Runtime。单独分发静态资源时仍须随附许可证，不能只给 HTML 链接。仅有 npm/GitHub 外链不能替代应交付的正文。实际分发形式、修改标记、对应源码提供等义务须按适用许可证确认；自动嵌入不消除下述清单缺口，也不替代法律审查。

## 可选来源复核

常规本地检查是 `python3 scripts/check-release.py` 与 `node tests/licenses.test.js`。以下深度复核不属于默认发布门槛，仅在需要验证已有来源证据时执行：校验 archive、包身份、vendor 原始字节、许可转换及 sourcemap 观察项，不安装或执行包代码、不写仓库。已有完整缓存可离线验证，缺失时显式 `--download` 仅下载到临时目录：

```bash
python3 licenses/verify-provenance.py --archive-dir /path/to/tarballs
python3 licenses/verify-provenance.py --download
```

脚本不重新获取外部 lockfile/公告，也不判定法律完整性。手工核对示例：

```bash
tmp="$(mktemp -d)"
curl --disable --fail --location \
  https://registry.npmjs.org/mermaid/-/mermaid-11.17.2.tgz \
  --output "$tmp/mermaid-11.17.2.tgz"
sha256sum "$tmp/mermaid-11.17.2.tgz"
tar -xOf "$tmp/mermaid-11.17.2.tgz" package/dist/mermaid.min.js | sha256sum
sha256sum scripts/vendor/mermaid.min.js
tar -xOf "$tmp/mermaid-11.17.2.tgz" package/LICENSE | sha256sum
sha256sum licenses/mermaid-11.17.2/LICENSE
```

许可文件仅在 manifest 明示时规范化换行；保留上游原始摘要和本地摘要。bundle 注释的源字节范围与复现算法见 [schema 说明](./licenses/README.md)。主要上游仓库：

- https://github.com/markdown-it/markdown-it
- https://github.com/highlightjs/highlight.js
- https://github.com/mermaid-js/mermaid
- https://github.com/d3/d3
- https://github.com/KaTeX/KaTeX
- https://github.com/markmap/markmap
- https://github.com/apache/echarts
