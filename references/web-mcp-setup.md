# AI Docs Web MCP 安装与管理

> 仅在用户明确要求“配置/安装/启用/升级/修复 AI Docs Web MCP”时读取并执行本流程。普通文档生成任务不得自动安装服务、修改 Host、启用 systemd 或写 Nginx。

## 1. 架构和事实源

### 交互式部署引导（Agent 执行顺序）

这是 Agent 的问答流程，不是安装器已有的交互式 CLI 向导。仅在用户明确要求部署时执行；已明确回答的选择直接复用，不重复询问。

1. **确认基础范围**：安装位置、域名、CDN/直连、TLS 终止与回源协议、文档分享和编辑范围。确认库目录；复制导入与直接编辑原目录必须区分，不能暗示副本会自动同步。默认 MCP 绑定 loopback，公网编辑入口在防护就绪前保持关闭。
2. **完成基础配置并验证**：安装/升级受管 Runtime，验证 `doctor`、服务启动、HTTPS 和文档访问。保留现有凭据和数据，不修改未经授权的 Host 配置。
3. **询问 Nginx Auth**：“基础配置已完成，是否配置 Nginx Basic Auth？保护编辑入口，还是同时保护分享文档？”默认建议保护公网编辑入口，不能无声改变分享链接的可访问性。
   - 选择“是”：询问用户名，并让用户选择在服务器终端交互式输入密码、自行配置已有密码文件，或明确授权生成随机密码。不要要求用户把密码输入普通聊天或普通问答工具；只有确认具备保密输入能力时才使用该输入渠道。未授权时不预设账号或自动生成密码。
   - 让用户自行设置时，先说明工具及权限要求；初次创建可以运行 `htpasswd -c /etc/nginx/ai-docs-preview.htpasswd <username>`，已有文件只能运行 `htpasswd /etc/nginx/ai-docs-preview.htpasswd <username>`，不得重复使用 `-c` 覆盖其他账号。密码通过交互提示输入，不放进命令参数或历史。密码文件应允许 Nginx worker 读取、禁止其他用户读取。
   - 说明“仅 Nginx 登录”和“Basic Auth + 应用 Token 登录”不是同一种体验。Basic 与 Bearer 共用 `Authorization`，不能未经验证直接叠加。单次登录使用显式 `preview.login_mode: "proxy"`（默认 `"token"`），要求 loopback 绑定且保留全局鉴权。登录页自动 POST 会话端点；生成的 Nginx 模板对该端点执行 Basic Auth 和 Origin 校验，通过私有 include 注入后端 Bearer，不将 Token 下发浏览器。需由部署者另行安全创建 `/etc/nginx/ai-docs-session-auth.inc`（root 所有、`0600`），内容为 `proxy_set_header Authorization "Bearer <实际 Token>";`，不能提交或打印该文件。其余预览请求清空 Authorization，继续使用会话 cookie。验证跨站保护、无凭据访问和完整登录流程；模板仅生成、不自动应用。
   - 选择“否”：询问是否已有 VPN/SSO/CDN 访问控制；若没有，不自动开放公网编辑，保持仅本机访问并说明原因。`public/` 内的文档默认公开且可被索引；需要私有分享时必须额外保护文档和原文路径。
4. **再询问公网 MCP**：“是否允许远程客户端通过 HTTPS 访问 MCP？默认否；这将允许持有 Token 的客户端调用文档发布工具。”仅回答“是”才另行实施；“部署域名”“开放网页”或“启用 Basic Auth”均不代表这项授权。
   - 选择“否”：保持 loopback 监听，Nginx `/mcp` 返回 `404`，不开放后端端口。
   - 选择“是”：先确认 HTTPS、Bearer Token、限流/请求大小、日志脱敏和 CDN 不缓存策略；仅反代明确的 MCP 路径，不顺带开放 `/v1/` 或 `/healthz`。MCP 使用 Bearer，不继承编辑器 Basic Auth 或把服务端 Token 注入匿名 MCP 请求。然后验证无效 Token 被拒绝及 `initialize`、`tools/list` 成功；远程 Host 注册仍需单独授权。
5. **无论是否开放公网，都说明 Token 查询方法**：告知实际凭据路径，请用户在自己的服务器终端运行下列命令。Agent 不执行显示 Token 的命令，不将结果写入聊天、仓库、URL 或普通日志。

   ```bash
   # 默认 user scope；设置过 XDG_CONFIG_HOME 时自动采用该位置。
   sed -n 's/^AI_DOCS_API_TOKEN=//p' "${XDG_CONFIG_HOME:-$HOME/.config}/ai-docs-web/credentials.env"
   # system scope：仅有权限的管理员在服务器上执行。
   sudo sed -n 's/^AI_DOCS_API_TOKEN=//p' /etc/ai-docs-web/service.env
   ```

   提醒用户只把值填入客户端的安全凭据配置，不回贴到会话；MCP 请求使用 `Authorization: Bearer <token>`，并包含 `Accept: application/json, text/event-stream`。变更 Token 会影响客户端和编辑会话；若使用服务端会话桥接，还需同步其私有凭据片段。
6. **交付**：明确 Auth 保护路径、MCP 是本机还是公网、实际入口、Token 查询方法、库目录与原目录的关系，以及已验证和未验证项。CDN 场景要求编辑与 MCP 路径不缓存，并透传所需请求头和 Cookie。

本仓库是 Skill、renderer 与 Web MCP 的唯一事实源，不依赖外部管理器。Host 的 Skill 安装目录可能不同，不能作为长期服务路径，例如：

```text
~/.claude/skills/ai-docs/
<HOST_SKILL_DIRECTORY>/ai-docs/
```

显式安装时，`scripts/web-mcp-manager.py` 把服务和运行所需 renderer 文件复制到稳定 runtime。服务后续运行不依赖某个 Host 的 Skill 目录；Skill 更新也不会隐式重启服务。

## 2. 默认安装范围

默认使用 `user` scope：不需要 `sudo`、监听 `127.0.0.1`、通过 user systemd 常驻。

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py plan
python3 <SKILL_DIR>/scripts/web-mcp-manager.py install
```

只有用户明确要求 VPS、多用户或系统服务，并确认系统已有 `ai-docs` 服务账号和适当权限时，才使用：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py plan --scope system
sudo python3 <SKILL_DIR>/scripts/web-mcp-manager.py install --scope system
```

管理器不会调用 `sudo`，也不会创建系统账号。

## 3. 用户级默认路径

所有路径遵循 XDG 变量；下表是变量未设置时的默认值。

| 内容 | 默认位置 | 权限/语义 |
| --- | --- | --- |
| 稳定 Runtime | `~/.local/share/ai-docs-web/runtime/` | 服务代码与 renderer 运行文件；不是内容数据 |
| 服务配置 | `~/.config/ai-docs-web/server.json` | `0600`；不含 Token |
| 凭据 | `~/.config/ai-docs-web/credentials.env` | `0600`；包含随机 Token，不写入仓库 |
| 文档库 | `~/.local/share/ai-docs-web/data/private/library/` | `0700`；`/preview/` 浏览和编辑的 Markdown |
| 公开目录 | `~/.local/share/ai-docs-web/data/private/library/public/` | 库内 `public/` 子目录；其中 Markdown 经 `/docs/` 实时渲染公开 |
| 临时 Workspace | `~/.cache/ai-docs-web/workspace/` | 可重建的渲染工作区 |
| 管理状态 | `~/.local/state/ai-docs-web/install.json` | 安装版本、路径和摘要 |
| user systemd | `~/.config/systemd/user/ai-docs-web.service` | 安装时生成，不自动启用 |
| OpenCode 配置 | `~/.config/opencode/opencode.json` | 仅显式 `register` 时修改 |
| Host 注册状态 | `~/.local/state/ai-docs-web/opencode-registration.json` | 用于冲突和漂移保护 |
| Nginx 模板 | `~/.local/state/ai-docs-web/nginx/ai-docs-web.conf` | 仅生成供审阅，不自动应用 |

对应 XDG 变量：`XDG_DATA_HOME`、`XDG_CONFIG_HOME`、`XDG_CACHE_HOME`、`XDG_STATE_HOME`。

## 4. 系统级默认路径

| 内容 | 默认位置 |
| --- | --- |
| Runtime | `/opt/ai-docs-web/runtime/` |
| 配置 | `/etc/ai-docs-web/server.json` |
| 凭据 | `/etc/ai-docs-web/service.env` |
| 文档库（含 `public/` 公开子目录） | `/var/lib/ai-docs-web/private/library/` |
| Workspace | `/var/cache/ai-docs-web/workspace/` |
| systemd | `/etc/systemd/system/ai-docs-web.service` |

系统级安装默认要求现有用户和组 `ai-docs`。Runtime 由 `root` 管理，数据目录由 `ai-docs` 写入；配置和凭据不得全局可读。

## 5. 默认配置

新安装默认生成以下结构（`workspace_root`、`library_directory` 和 Node 路径由安装器解析为实际绝对路径；手工配置时必须替换示例路径）：

```json
{
  "schema_version": 2,
  "workspace_root": "/absolute/path/to/workspace",
  "library_directory": "/absolute/path/to/library",
  "public_directory": "public",
  "server": {
    "host": "127.0.0.1",
    "port": 18080,
    "public": {
      "scheme": "http",
      "host": "127.0.0.1",
      "port": 18080
    },
    "documents_prefix": "/docs/"
  },
  "preview": {
    "enabled": true,
    "path": "/preview",
    "write_back": true,
    "session_seconds": 43200
  },
  "library_limits": {
    "max_files": 1000,
    "max_total_bytes": 52428800,
    "max_path_depth": 8
  },
  "mcp": {
    "path": "/mcp",
    "reference": {
      "name": "ai-docs",
      "scheme": "http",
      "host": "127.0.0.1",
      "port": 18080,
      "path": "/mcp",
      "timeout_ms": 30000,
      "token_env": "AI_DOCS_API_TOKEN"
    }
  },
  "renderer": {
    "node": "/absolute/path/to/node"
  },
  "max_upload_bytes": 5242880,
  "max_rpc_bytes": 6291456,
  "auth_required": true,
  "auth_token_env": "AI_DOCS_API_TOKEN"
}
```

`workspace_root` 与 `library_directory` 均为必填且必须是绝对路径（缺省或相对路径会拒绝加载）；默认安装分别落在缓存工作区与私有数据目录；`public_directory`（默认 `"public"`）指定库内公开子目录，其中 Markdown 经 `/docs/` 实时渲染公开。`preview.session_secret` 只在需要脱离 Token 固定会话密钥时设置，且必须至少 32 字符。`preview.write_back: false` 会将 systemd 私有库设为只读，`ReadWritePaths` 仅保留 workspace 与公开子目录；MCP 发布仍可写公开目录，并非全服务只读。默认保存配额为 `1000` 个受管理文件、`50 MiB` 总字节和 `8` 段相对路径深度；`public_docs.max_files`/`max_total_bytes` 是公开子目录的子配额（默认取库配额的 4/5）；超额保存返回冲突错误，不会自动清理或删除用户文件。`render_cache`（默认 `128 MiB` / `128` 条 / 单条 `32 MiB`）约束进程内渲染缓存；`public_docs.max_concurrent_renders`（默认 `1`）与 `render_timeout_seconds`（默认 `30`）约束公共冷渲染。

完整模板见 `web-mcp/assets/server-config.user.example.json` 和 `server-config.system.example.json`。

文档发布地址和 MCP Host 引用都使用明确的 `scheme + host + port`，路径分别由 `server.documents_prefix` 与 `mcp.reference.path` 管理。推荐外网文档使用 HTTPS，同时保持 MCP 为 loopback HTTP：

```json
{
  "server": {
    "public": { "scheme": "https", "host": "docs.example.com", "port": 443 }
  },
  "mcp": {
    "reference": {
      "scheme": "http", "host": "127.0.0.1", "port": 18080, "path": "/mcp"
    }
  }
}
```

安装器默认从当前可用 `node` 解析真实绝对路径，并写入 `renderer.node` 与 systemd unit。服务和 `doctor` 始终使用该固定路径，不依赖交互式 Shell 的 `PATH`。`server.json` 与凭据文件在 user scope 下会被强制修复为 `0600`。

创建新配置时可直接指定各地址字段：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py install \
  --bind-host 127.0.0.1 --port 18080 \
  --public-scheme https --public-host docs.example.com --public-port 443 \
  --mcp-scheme http --mcp-host 127.0.0.1 --mcp-port 18080
```

若 `--bind-host` 是 `0.0.0.0` 或 `::`，必须显式提供可连接的 `--public-host`；wildcard bind address 不会被当作发布 URL。

## 6. 凭据管理

安装器首次安装时生成随机 `AI_DOCS_API_TOKEN` 并写入私有凭据文件。它不会：

- 把 Token 写入 `server.json`、仓库、管理状态或普通命令输出；
- 覆盖已有凭据文件；
- 把 Token 传给 Node renderer 子进程。

OpenCode 配置只写：

```text
Bearer {env:AI_DOCS_API_TOKEN}
```

因此启动 OpenCode 的环境也必须提供该变量。可以在启动前从凭据文件安全导出，但不要把值复制到仓库、Shell history 或文档。

## 7. 启动、检查和注册

```bash
# 检查安装文件是否完整
python3 <SKILL_DIR>/scripts/web-mcp-manager.py status

# 验证配置、Node、Token 和目录权限
python3 <SKILL_DIR>/scripts/web-mcp-manager.py doctor

# 显式启用并启动 user systemd
python3 <SKILL_DIR>/scripts/web-mcp-manager.py start

# 显式注册 OpenCode；不会覆盖同名非受管配置
python3 <SKILL_DIR>/scripts/web-mcp-manager.py register --host opencode
```

配置或注册后，已有 OpenCode 会话不会自动获得新 Tool。提示用户重新启动 Host，并在新会话中确认 `publish_document`、`list_documents` 可见。

本地地址：

```text
MCP:     http://127.0.0.1:18080/mcp
Docs:    http://127.0.0.1:18080/docs/guide/intro   （实时渲染 public/guide/intro.md）
Preview: http://127.0.0.1:18080/preview/
Health:  http://127.0.0.1:18080/healthz
```

预览入口只在 `preview.enabled: true` 时存在。浏览器打开 `/preview/` 后，无会话时会跳转至 `/preview/login`；登录页通过 `POST /preview/session` 的 `Authorization: Bearer <token>` 请求头校验 Token，再下发 `HttpOnly` + `SameSite=Lax` + `Path=/preview/` 会话 cookie。服务拒绝 `?token=`，应用访问日志只记录规范化 path，不回显 query、Authorization 或 cookie。HTTPS 由明确的 `server.public.scheme: "https"` 决定并添加 `Secure`；本地 HTTP 不添加，且服务不信任任意客户端提供的 `Forwarded` 或 `X-Forwarded-Proto`。`/preview/` 列出库目录内的全部受管理 Markdown，`/preview/edit?path=...` 打开编辑器，页面通过 `/preview/api/render` 和 `/preview/api/save` 渲染与写回。仅渲染不发布；保存非公开文件不会发布，但保存 `public/` 内的文件会立即影响 `/docs/`。

非浏览器客户端可这样交换 cookie；不要把 Token 写进命令行字面量或 URL：

```bash
curl -i -X POST \
  -H "Authorization: Bearer $AI_DOCS_API_TOKEN" \
  http://127.0.0.1:18080/preview/session
```

会话 cookie 的签名密钥由 `AI_DOCS_API_TOKEN` 派生，除非显式设置 `preview.session_secret`。因此更换 Token 会立即让旧会话失效，同一 Token 下服务重启不会登出。`preview.session_seconds` 的签发与验证采用相同配置值，允许 `60` 秒到 `604800` 秒（7 天）。预览和发布渲染共用 `max_concurrent_renders`，容量用尽时返回 `429 render_busy`。预览 iframe 会为 renderer 输出注入严格 CSP：普通 `<a href>` 保留，但图片、脚本、样式、iframe 和 `fetch` 等远程子资源不会自动联网。

### Preview quick start (English)

Open `http://127.0.0.1:18080/preview/` and enter the API token on the login page. The page sends it only in `Authorization: Bearer ...` to `POST /preview/session`; query-token URLs such as `/preview/?token=...` are rejected. The resulting cookie is `HttpOnly` and `SameSite=Lax`; it is also `Secure` when `server.public.scheme` is `https`. Do not rely on client-supplied `Forwarded` or `X-Forwarded-Proto` headers.

Writes are limited by `library_limits.max_files`, `library_limits.max_total_bytes`, `library_limits.max_path_depth`, and the per-file `max_upload_bytes`. An over-quota write is rejected without deleting existing files. Saving a file inside `public/` changes its public page and raw Markdown immediately. Preview rendering is bounded by `max_concurrent_renders`; public cold rendering has additional `public_docs` limits. Preview HTML keeps ordinary links, while a preview-only CSP prevents remote subresources and network requests from loading automatically.

## 8. 升级

管理器生成的 systemd 权限跟随有效配置的 `library_directory` 和 `workspace_root`；关闭预览写回时私有库只读，`public_directory` 子目录仍可供 MCP 发布。自定义路径不能与 Runtime、配置、状态或另一存储根重叠，也不能包含软链接及路径穿越。system scope 路径须位于 home/user runtime 之外。修改配置后显式 `upgrade` 更新 unit，再按授权重启；检查已有目录的服务用户权限，管理器不会接管或递归改变已有目录所有权。仅在终端运行 `doctor` 通过不能证明 systemd 服务可写，详见 [发布与迁移](releasing.md)。

同步 Skill 不会自动替换或重启稳定 Runtime。先查看：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py status
```

出现 Runtime drift 后显式升级：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py upgrade
python3 <SKILL_DIR>/scripts/web-mcp-manager.py restart
python3 <SKILL_DIR>/scripts/web-mcp-manager.py doctor
```

升级通过临时目录复制和原子目录替换更新 Runtime；配置、凭据和发布数据独立保留。

## 9. 卸载

默认卸载会先校验 Runtime/unit 未被手工修改，再通过 systemd 停止并禁用服务，然后删除 unit、Runtime、受管 Host 注册和安装状态；配置、凭据、Host 配置备份及已发布文档保留：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py uninstall
```

只有用户明确要求永久删除数据和凭据时；该模式也删除管理器创建的 OpenCode 配置备份：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py uninstall --purge
```

## 10. 安全停止条件

遇到以下情况停止并请用户处理，不强制覆盖：

- Runtime 或 systemd unit 已存在但无匹配受管状态；
- OpenCode 有同名非受管 MCP 配置；
- 受管 Host 项已被手工修改；
- 目标或父目录经过符号链接；
- system scope 缺少 `ai-docs` 账号或写权限；
- 用户要求公网直接暴露，但尚未确认 TLS、鉴权、防火墙和页面公开边界。

外网和 HTTPS 继续读取 `references/web-mcp-external-access.md`。
