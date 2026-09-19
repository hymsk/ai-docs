# 独立源码发布与迁移

本文定义源码发布检查，不代表某个 tag、GitHub Release 或软件包已经发布。当前公开兼容基线为 `v1.0.0rc1`。

## 分发边界

- 完整源码包括 Skill、CLI renderer、vendor、可选 Web MCP、参考资料、示例、测试和许可证。
- 运行不依赖其他仓库；不要在源码归档中放入真实 Host 配置、服务数据、生成文档、凭据、缓存或开发机路径。
- 首轮分发使用完整源码归档与 Git tag，不要求 npm/PyPI 发布。安装 Skill 时保留完整目录；只复制 `SKILL.md` 不受支持。
- 自有代码维持 `AGPL-3.0-or-later`；第三方资源按各自许可处理。用户文档内容不会仅因使用 renderer 而自动变成项目代码，但生成的 HTML 含项目运行时代码和第三方资源，不能据此声称整个产物没有软件许可义务。

## 发布前检查

### 已知部署限制

- Nginx 模板默认拒绝公网预览，开放须显式 `--expose-preview`；本地 `preview.enabled` 不等于公网授权。模板应用及真实登录仍需验收，见 [外网指南](web-mcp-external-access.md)。
- systemd unit 从有效配置读取库及 workspace；关闭预览写回时私有库只读，公开子目录仍可供 MCP 发布。修改配置后须显式 `upgrade` 更新 unit，再按授权重启。路径、服务账户及 systemd 沙箱在真实部署环境仍需验证；`doctor` 在管理器进程中通过不证明真实服务可写。
- 独立 HTML 可能加载 Markdown 中的远程图片；“内置资源离线”不是对任意输入的网络隔离保证，见 [安全与限制](safety-and-limitations.md)。

### 检查顺序

1. 更新 `VERSION`、管理器、服务、README 与 CHANGELOG；校验器从 `VERSION` 读取目标版本。源码版本不等于已发布版本。
2. 执行 CONTRIBUTING 中完整质量门；浏览器检查见 [安全与限制](safety-and-limitations.md)。没有验证的环境和视觉效果要列为未验证。
3. 执行 `python3 scripts/check-release.py --history`，检查本地 HEAD、分支和 tag 可达文件、文件名、提交元数据、引用名及 annotated tag 注释；浅克隆会拒绝作为完整审核。诊断不回显疑似凭据。此检查不读取 reflog、不查询远端，也不是完整秘密检测器。未获取的远端引用、二进制内容、业务机密及版权仍须人工审核。
4. 审查计划发布的准确文件集合，构建干净源码归档。在仓库之外解压后再次运行质量门及 CLI 示例；使用临时 HOME/XDG 和 mock systemd 验证 manager install/upgrade/uninstall，不接触真实服务。
5. 按实际分发的 vendor 核验版本来源、摘要、适用的 LICENSE/NOTICE 和原有版权声明，并确认源码包、Runtime、HTML 携带对应材料。针对已知许可缺失、冲突或不兼容条件记录处理结论；安全公告单独评估。默认不要求逐文件追溯、完整递归 SBOM 或上游构建复现，`partial` 也不是独立失败条件。摘要通过仅证明材料一致，不是法律认证。
6. 在托管平台确认 Private Vulnerability Reporting、CI 和需要的分支保护设置。仓库文件不能证明这些远端设置已经启用。
7. 只有维护者明确授权后才提交、推送、创建 tag、Release 或改变仓库可见性。Release 附迁移说明、已验证环境、已知限制、完整源码及 SHA-256；不宣称不存在的包仓库发布。

历史扫描发现问题时，先报告具体路径与规则，不输出疑似凭据内容，不自动改写历史。历史中的真实凭据必须先撤销/轮换，再单独决定清理和发布范围。

### 许可检查与可选审计的边界

- 常规检查以本地分发材料为准；`check-release.py` 校验 vendor/许可文件集合、关联及摘要，`licenses.test.js` 验证 HTML 携带许可。检查失败须修复，不能靠删除声明或放宽摘要检查绕过。
- `licenses/verify-provenance.py` 及 `scripts/vendor-provenance.json` 保留为可选来源复核工具和证据。
- `licenses/manifest.json` 的 `gaps` 同时包含审计覆盖限制和具体问题，并非统一的发布阻断清单。jsx-dom 声明冲突、KaTeX 已识别的改编归属等具体事项不能因缩减审计范围而标记已解决；现状见 `THIRD_PARTY_NOTICES.md`。本流程不代替对实际许可条件的判断。

## 对应源码与可核验归档

HTML 的软件许可证区域包含源码版本、renderer 材料的 SHA-256 标识及逐文件摘要；单/多文件使用同一套身份计算。摘要覆盖构建器、默认资源清单、所有 vendor 和许可材料，不包含用户 Markdown，也不代表已发布的 Git commit。源码归档和安装后的 Runtime 均不依赖 Git 即可生成该标识。

分发者应将生成 HTML 与对应的完整源码包一起提供，或提供可持续访问的准确源码下载地址；仅指向不断变化的仓库首页不应作为对应源码交付方案。修改版须包含实际修改及构建材料，不得只链接上游原版。适用许可证的具体义务需按实际分发方式确认。

在干净的发布 checkout 内执行（目标必须不存在且在仓库之外）：

```bash
python3 scripts/check-release.py
python3 scripts/package-source.py --output /absolute/output/ai-docs-source.tar.gz
```

工具仅生成本地归档，不提交、不创建 tag、不上传。归档携带 `SOURCE.json`，记录版本、基准 commit、是否有修改以及交付文件的逐文件 SHA-256；命令输出归档 SHA-256。忽略文件不进入归档，符号链接与非普通文件会拒绝。仍需审核文件集合并在仓库外解压执行测试，摘要不是秘密检测或许可审查的替代品。

开发验收可显式传 `--allow-dirty`，产物将标记 `modified: true`；此包只能作为候选验收材料，不得冒充准确 commit 的正式发布资产。正式包应由最终干净提交生成，将其下载位置与校验值加入 Release notes，并抽查其中源码与 HTML 的逐文件摘要一致。
