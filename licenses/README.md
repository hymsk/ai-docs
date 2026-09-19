# 离线许可证与证据清单

本目录保存精确上游版本的 LICENSE、NOTICE 和从现有 bundle 提取的许可注释。入口为 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)，机器可读数据为 [manifest.json](./manifest.json)。这里记录可复现来源，不构成法律意见或全部传递依赖许可完备的保证。

## 日常维护范围

以实际分发的 vendor 和上游提供的许可材料为单位维护：核对版本来源、保存适用 LICENSE/NOTICE 与原有版权声明，并验证它们随源码、Runtime、HTML 交付。常规检查使用 `python3 scripts/check-release.py` 和 `node tests/licenses.test.js`，不需要下载全部包或逐文件追溯来源。

已收集的附加正文和来源证据继续保留，但不是今后每次升级都必须扩展到相同审计深度的模板。`transitive_license_inventory: partial` 仅说明未建立完整递归清单，既不是自动发布阻断项，也不是合规结论。

`gaps` 中须区分三类内容：D3/Markmap 构建证明、完整递归来源链等属于可选审计边界；jsx-dom 声明冲突、KaTeX 改编许可材料等属于需针对性判断的已知许可问题；安全公告独立评估。boolbase 正文已经恢复。缩减审计范围不改变这些事实或擅自关闭具体问题。

## manifest schema v1

- `schema_version: 1`、`hash_algorithm: "sha256"`、`path_base: "repository-root"` 固定。所有本地路径相对于 AI Docs 仓库根；摘要为原始字节的 64 位小写十六进制 SHA-256。
- `packages[]`：`name`、`version` 精确标识 npm 包；`source_url` 是匿名 tarball URL；`archive_sha256` 校验整个压缩包；`declared_license` 仅抄录该包 `package.json`，不替代 LICENSE，也不覆盖 bundle 依赖。
- `vendor_files[]`：`file`、`package`、`version`、`source_path`、`sha256`、`license_files[]`。源 URL 由 `packages` 的 `(name, version)` 解析；源文件字节已与本地文件全量比较，因此此处 `sha256` 同时是源与本地摘要。`license_files` 是已收集的关联材料，不表示传递依赖完整。
- `files[]`：每个许可/notice 文件有唯一 `file`，以及 `package`、`version`、`kind`（`license` / `notice` / `bundle-notices`）、`source_url`、`source_path`、`source_sha256`、`sha256`、`normalization`。`source_path` 含 tarball 内真实 `package/` 前缀；`source_sha256` 始终是该完整上游成员的摘要，`sha256` 是保存后的本地文件摘要。可选 `additional_sources[]` 记录逐字节相同的其他包来源。
- `files[].source_type` 省略时为 `npm-member`。例外 `github-file` 用于 npm 未携带的原始上游许可：必须给出 `source_repository`、40 位 `source_commit`、仓库内 `source_path`、完全对应的 raw URL、`source_blob_sha1` 和 SHA-256，只允许 `normalization: none`。`npm_member_match` 将同一 commit 的代码文件与该 npm 包成员逐字节对应；它不代表整个仓库、package.json 或 bundle 构建一致。此模式不改变 `packages[]` 的 npm 来源，也不允许 vendor 使用 GitHub 替代源。
- `normalization` 为 `none` 时完整逐字节复制；`crlf-to-lf-and-ensure-final-lf` 只将 CRLF 转 LF，并在缺失末尾 LF 时补一个，不改版权或许可文字。Cytoscape、ECharts NOTICE、ZRender 原文件无末尾 LF；tslib 原文是 CRLF。原始与本地摘要分别保留。
- `bundle-notices` 的 `normalization` 为 `byte-ranges-joined-with-lf-and-final-lf`；`source_ranges` 是按顺序排列的 `[start, end]` **字节**偏移，0 起始、右端不包含。复现方法：从完整源成员提取各范围，用一个 LF 连接，再附加一个 LF；范围内原文（包括空白）不改动。
- `evidence[]`：外部证据的 `id`、`source_url`、`source_path`、`source_sha256` 与 `observations[]`；观察项使用 JSON Pointer 或同样语义的 `byte_range`，`value` 为实际观测原文。大型 source map 不复制到本仓库，可从已固定摘要的 tarball 重取。
- `coverage` 描述已验证边界；`gaps[]` 记录尚未关闭的限制与上游冲突。当前 `transitive_license_inventory` 明确为 `partial`，不可把 hash 通过解释为法律审查通过。

`files` 枚举本目录全部许可/notice 载荷；`README.md`、`manifest.json` 是维护元数据，`verify-provenance.py` 是只读审核程序，均不伪装成第三方许可载荷。新增载荷必须同时更新 `files`。发布检查应将这三个固定维护文件与 payload 区分：拒绝绝对路径、`..`、符号链接和重复路径；确认每个 `files[].sha256` 匹配、`vendor_files[].license_files` 均存在且指向清单条目，并对比实际 vendor/许可文件集合。网络复核另外验证 tarball 摘要、成员摘要及声明的转换。

额外的 [`scripts/vendor-provenance.json`](../scripts/vendor-provenance.json) 是审核证据，不改变 manifest schema v1：记录精确 sourcemap 依赖 locator、成员比较结果、上游锁文件 URL/摘要、候选与已证实内嵌的区别、jsx-dom 冲突结论和有限安全公告快照。`packages` 可以保留历史来源或候选包，不等于所有包都在当前 bundle 内；当前关联以 `vendor_files[].license_files`、provenance 的证据等级为准。

## 已核实修正

1. `highlight.js@11.11.1` 没有 `package/highlight.min.js`；当前 JS 精确匹配 `@highlightjs/cdn-assets@11.11.1/package/highlight.min.js`。CSS `styles/github.min.css` 在两包中相同；两包的 LICENSE 也相同。
2. 当前 `markmap-lib.browser.js` 与 `markmap-lib@0.17.2/package/dist/browser/index.iife.js` 完全一致。旧说明中的“版本标识清理”未获字节证据支持，已删除。
3. ECharts 的 Apache LICENSE 自带 subcomponents 段落，明确指向旧版 D3 的 BSD 条款；这与独立 `d3@7.8.5` 的 ISC LICENSE 不是同一份材料，两者分别保存。ECharts `NOTICE`、ZRender LICENSE、tslib LICENSE/CopyrightNotice 及 bundle 注释同时保留。

## 已保留的补充证据与未决项（非逐项发布门禁）

- Mermaid 当前 11.17.2 的全部 60 个带版本第三方 source locator 已收集顶层许可；664 个 source contents 与对应精确 npm tarball 成员逐字节相同。另 11 个 `marked` TypeScript 成员不在 npm tarball，版本证据是 sourcemap 路径，而非猜测范围。DOMPurify 3.4.12、KaTeX 0.16.47、Cytoscape 3.34.0 等内嵌版本与独立 vendor 分别记录。上游 `roughjs` patch hash 原样保留。
- 一级 source map 包许可收齐不等于递归内嵌许可完备：roughjs、Cytoscape、KaTeX、D3 子包的预构建产物还可能内嵌其他来源。Cytoscape 3.34.0 的 npm dist 内容与 Mermaid map 相同；Thenable / jQuery events / Bezier / Framer / CoSE 的原始归属注释已按字节范围提取，改编片段的不可变上游 revision 仍未确认。
- 两个 Markmap bundle 明示 `@gera2ld/jsx-dom v2.2.2 | ISC License`。该 tarball 的 MIT LICENSE 与标签 `v2.2.2` 的 commit `9f9660e94280e642ee6ba8e644a3f2cd8903f7e1` LICENSE 逐字节一致，但同 commit 的 package.json 仍写 ISC。本分发保留明确 MIT 正文与 ISC 声明，不将冲突默认为双许可证或宣称上游已经澄清。
- Markmap tarball 虽没有 map/lockfile，但其 `gitHead` 可定位到 `bbeec32d0efeea4e36755b1909a5993187264487/pnpm-lock.yaml`。已收集锁定候选的正文，明确它不是全量构建证明；view 明示 `d3-flextree` 2.1.2，lock 对应 `d3-hierarchy` 1.1.9。`boolbase@1.0.0` tarball 只有三个文件，无许可证正文；现从上游 commit `be0bcd8a4e917a0a5895e95b523fbbed05a64871` 补回原始 [ISC LICENSE](./boolbase-1.0.0/LICENSE)，同时保留 npm 作者/ISC 元数据。该 commit 的 `index.js` 与 npm 唯一执行成员逐字节一致；package.json 仍声明 1.0.0/ISC，但 scripts 不同，不宣称全包相同。这是 2015-10-14 上游后补正文，不是通用模板，也不关闭 Markmap 构建证明缺口。
- KaTeX 0.16.21 和 0.16.47 的 `dist/katex.mjs` 明示 `hyphenate` / `escape` 改编自 Apache-2.0 React；现按字节范围保留两份 `REACT-NOTICE.txt`。npm 只携带 KaTeX 顶层 MIT 正文，确切 React revision、版权及完整适用 notices 尚未证实，继续保留具体缺口，不以一行注释代替许可完整性。
- markdown-it 14.3.2 发布 map 的 19 个第三方成员与同标签 lockfile 固定的 mdurl 2.0.0 / uc.micro 2.1.0 / entities 4.5.0 / linkify-it 5.0.2 / punycode.js 2.3.1 全部逐字节相同，正文已保存；浏览器 map 未包含 argparse。
- D3 7.8.5 的 33 个依赖版本来自 `v7.8.5/yarn.lock`，补充 ISC、BSD、Unlicense 等对应正文，并保留与未压缩 dist 相同的部分源片段观察。没有 source map 或完整重建，不声称所有锁定依赖都是字节级证明的内嵌版本。
- 原版本的 DOMPurify 3.1.6 等保留材料是历史证据，不代表当前 Mermaid 使用这些版本。所有具体缺口仍在 `gaps`，`transitive_license_inventory` 继续为 `partial`。

## 可选深度来源复核

下列命令用于复核已有详细证据，不属于常规 CI 或每次发布的必跑步骤；需要时才显式执行。

```bash
python3 licenses/verify-provenance.py --archive-dir /path/to/tarballs
# 或显式联网；下载仅保存到临时目录，不安装/执行包：
python3 licenses/verify-provenance.py --download
```

脚本检查精确 tarball 摘要、包身份、10 个 vendor 完整字节、130 个许可/notice 载荷的源范围/转换/摘要，以及上述 Mermaid、markdown-it 源成员。`github-file` 同时复核许可 Git blob 与同 commit 代码/npm 成员匹配：离线缓存命名为 `<source_sha256>.source`，放入 `--archive-dir`；缺失时只有显式 `--download` 才通过 GitHub contents API 读取固定 commit 并验证解码后的原始字节，联网失败不会跳过。没有任何 vendor 换行豁免。不重新联网验证外部锁文件、可变公告快照或法律充分性。网络快照与当前残余安全公告见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

部分上游原文包含行尾空格、额外末尾空行或版权年份差异，保留它们用于复核；不要为了通用 whitespace 检查擅自改写许可证。本目录不包含下载包、包执行代码或新运行时依赖。
