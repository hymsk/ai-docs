# AI Docs Repository Rules

本仓库只维护 AI Docs。默认使用中文沟通；代码、命令、路径和 API 名称保留原文。

## 不变量

- 本仓库是 Agent Skill、离线 renderer、可选 Web MCP、vendor、参考文档、示例和测试的唯一事实源，不维护第二份实现。
- `SKILL.md` 必须保持自包含，不依赖父仓库或安装位置的绝对路径；运行时资源统一通过 `<SKILL_DIR>` 定位。
- Web MCP 安装、升级、Host 注册、systemd、Nginx、端口和 TLS 配置只能在用户明确要求后执行；普通 Skill 同步不得产生这些副作用。
- 默认保持 `strict: true` 和 `mermaidSecurity: strict`，不得用降级模式掩盖可修复错误；仅内容级不可渲染图表按设计降级为代码块。
- 不内置 Graphviz；`dot`/`graphviz` fence 会降级为普通代码块（表头带警示标识，悬浮显示原因），关系图统一迁移到 Mermaid。
- vendor 文件只能来自 `THIRD_PARTY_NOTICES.md` 记录的精确上游版本和路径；更新时同步校验 SHA-256、许可证和 notices。
- 不提交密码、token、cookie、私钥、真实 Host 配置、个人服务地址、内部仓库 URL、开发机绝对路径或生成的发布数据。
- `v1.0.0rc1` 是当前公开兼容基线；从该 tag 开始维护公开 CLI、配置、MCP 工具与 Web 行为的向后兼容。不得覆盖或移动公开 tag，也不得将准备中的源码版本描述为已发布。
- 公开文档和运行入口必须独立可用；不依赖私有管理工具。许可证文件必须随完整源码和受管 Runtime 分发。
- 许可维护以实际分发的 vendor 及上游 LICENSE、NOTICE、bundle 声明为边界；已知许可问题与安全公告按具体事实处理，并记入 `references/dependency-security.md` 跟踪。

## 验证

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
