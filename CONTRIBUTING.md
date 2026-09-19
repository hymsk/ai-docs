# Contributing

## Development

AI Docs 不需要安装第三方运行时依赖；renderer 使用 Node.js 18+，Python 工具使用 Python 3.9+ 标准库。Web MCP 管理器面向 Linux 与 systemd。建议使用受维护的 Node.js LTS 和 Python 版本。

运行完整质量门：

```bash
python3 scripts/check-release.py
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/licenses.test.js
node scripts/build-component-index.js --check
node tests/component-index.test.js
node tests/build.test.js
node tests/output-modes.test.js
node tests/serve.test.js
node tests/preview.test.js
python3 -m unittest discover -s web-mcp/tests -p 'test_*.py'
node --check scripts/build.js
node --check scripts/preview.js
python3 -m py_compile scripts/serve.py scripts/web-mcp-manager.py web-mcp/source/ai_docs_web.py
git diff --check
```

修改组件文档后先运行：

```bash
node scripts/build-component-index.js
```

浏览器验收为单独的开发检查，不增加 renderer 运行时依赖。环境预装 Python Playwright 和 Chromium 时执行：

```bash
python3 tests/browser-smoke.py
# 或指定已有 Chromium：
python3 tests/browser-smoke.py --chromium /absolute/path/to/chromium
```

该检查使用临时目录、独立浏览器配置及 loopback 临时静态服务，覆盖单/多文件、图表、主题、Markdown 下载和 PDF 生成；不等于人工逐页视觉及打印排版审核。脚本不会自行安装浏览器。

## 第三方许可维护

默认以实际分发的 vendor 为单位维护，不要求逐文件审计整个依赖树：

1. 新增或更新 vendor 时核对准确版本、上游发布文件和摘要，同步 `THIRD_PARTY_NOTICES.md` 与 manifest。
2. 携带适用的上游 LICENSE / NOTICE，保留 bundle 的版权和许可声明；已有的内嵌依赖材料不因精简流程而删除。
3. 运行 `python3 scripts/check-release.py` 和 `node tests/licenses.test.js`，检查本地材料完整性与单/多文件 HTML 分发。Runtime、源码归档的携带行为由相应回归覆盖。
4. 已知正文缺失、许可声明冲突或条件不兼容须针对性处理和记录；安全公告另按 `references/dependency-security.md` 评估。开源项目本身不免除这些义务。

逐文件来源比对、完整递归 SBOM、上游 bundle 重建是可选深度审计，不属于常规 CI 或默认发布门槛；未完成这些审计不自动等同于许可违规。已有 `partial` 等字段保留为事实边界，不要求为了发布改成 `complete`。

### 可选来源复核

仅在更新来源存疑、发现具体问题或明确要求深度审计时，按需复核现有证据（只下载已固定包，不运行 npm 安装脚本）：

```bash
python3 licenses/verify-provenance.py --download
```

已有 tarball 缓存可用一个或多个 `--archive-dir`，无需再次下载。固定 GitHub 许可及对应代码使用 `<sha256>.source` 缓存；缺少时需显式 `--download`，不会跳过校验。缓存格式见 `licenses/README.md`。

## Pull Requests

- 修改 renderer、vendor、Web MCP 或 Skill 行为时补充对应隔离测试。
- 修改 vendor 时同步更新 `THIRD_PARTY_NOTICES.md` 中的版本、上游路径、许可证和 SHA-256。
- 不提交生成的 HTML、发布数据、凭据、用户配置、cache 或开发机绝对路径。
- Web MCP、systemd、Nginx 和 Host 注册属于显式副作用；测试必须使用临时 XDG 目录和本地 mock，不接触真实用户配置。
- 当前文档只描述已实现且可验证的行为；未来产品规划不进入当前能力说明。

发布步骤、兼容性及独立验收见 [`references/releasing.md`](references/releasing.md)。源码修改不代表授权发布、推送或改变仓库可见性。
