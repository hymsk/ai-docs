# AI Docs Web MCP 外网与 HTTPS 规划

> 仅在用户明确要求域名、HTTPS、Nginx、外网 URL 或直接公网监听时读取。

## 推荐拓扑

部署问答的授权顺序见 `web-mcp-setup.md` 的“交互式部署引导”：基础配置后先确认 Nginx Auth，再单独确认公网 MCP。下述默认拓扑不开放公网 MCP；不要因用户配置域名就自动扩大访问范围。

默认只把公开文档目录的实时渲染结果暴露到外网；MCP、预览和配置接口保持 localhost：

```text
Agent -> http://127.0.0.1:18080/mcp (publish_document)
                     |
                     +-> library/public/ 实时渲染
                                   |
                                Nginx TLS（限速 + 动态代理）
                                   |
                    https://docs.example.com/docs/guide/intro
```

`nginx-template` 默认输出 `location ^~ /preview/ { return 404; }`，即使本地 `preview.enabled: true` 也不生成预览/session 代理。只有确认要在公网提供预览与编辑后，才显式传 `--expose-preview`，此时后端预览必须已启用，模板生成带 HTTP Basic Auth 的代理。公网 MCP 另需独立授权 `--expose-mcp`：

```text
用户 -> https://docs.example.com/preview/
                     |
              Nginx Basic Auth
                     |
              ai-docs-web /preview/login
                     |
        POST /preview/session + Authorization
                     |
              HttpOnly 会话 cookie
                     |
              ~/.local/share/ai-docs-web/data/private/library/
```

模板生成的块引用 `/etc/nginx/ai-docs-preview.htpasswd`，需要使用者自行创建（例如 `htpasswd -c /etc/nginx/ai-docs-preview.htpasswd <user>`）并自行 reload Nginx。两层防护含义不同：Basic Auth 挡住不知道账号的访问者，会话 cookie 挡住未完成 Bearer 登录的访问者；两者都不能替代 SSO 或 VPN。不要使用 `/preview/?token=...`，因为 URL 会进入浏览器历史、代理访问日志和链路诊断记录。

`/preview/` 的写回能力等价于“谁通过鉴权谁就能改库目录里的 Markdown”。若预览只需只读，保持 `preview.write_back: false`，生成的 systemd unit 使私有库只读，但公开子目录仍可由 MCP 发布；这不是全服务只读模式。不要将 MCP Token 当作只读账号发给阅读者。

配置示例：

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 18080,
    "public": { "scheme": "https", "host": "docs.example.com", "port": 443 },
    "documents_prefix": "/docs/"
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
  }
}
```

## 生成 Nginx 模板

管理器只生成供审阅的配置，不写 `/etc/nginx`、不申请证书、不 reload Nginx：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py nginx-template \
  --public-scheme https --public-host docs.example.com --public-port 443
```

默认输出：

```text
~/.local/state/ai-docs-web/nginx/ai-docs-web.conf
```

也可指定审阅位置：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py nginx-template \
  --public-scheme https --public-host docs.example.com --public-port 443 \
  --output /tmp/ai-docs-web.conf
```

模板默认只代理 `/docs/`（动态、带限速）；显式传 `--expose-preview` 时额外代理预览前缀并加 Basic Auth。预览代理块不发送 `Forwarded`、`X-Forwarded-Proto` 或可由客户端污染的代理链头；应用是否设置 `Secure` cookie 只依赖受管 `server.public.scheme`。对未授权的 `/mcp`、`/v1/`、`/healthz` 与预览前缀明确返回 `404`。证书路径、域名、Nginx 安装位置及 reload 必须由用户确认后单独处理。相同输出路径已有不同内容时管理器拒绝覆盖，应先写入新的审阅路径并比较。

公网预览授权示例（仅在用户明确同意后）：

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py nginx-template \
  --public-scheme https --public-host docs.example.com --expose-preview \
  --output /tmp/ai-docs-preview-review.conf
```

### 公网 MCP（`--expose-mcp`）

默认拓扑不开放公网 MCP；只有在用户明确确认后（见 `web-mcp-setup.md` 的授权顺序），才给 `nginx-template` 加 `--expose-mcp`。此时模板把 `location = /mcp` 从 `404` 改为反向代理，规则如下：

- **Bearer 透传**：Token 由后端校验，Nginx 不得剥离、注入或覆盖 `Authorization`；同时清空 `X-AI-Docs-Token` 与 `Forwarded`，避免等价认证头或代理链头被客户端污染。
- **按源 IP 限速**：模板在 http 上下文生成 `limit_req_zone $binary_remote_addr zone=ai_docs_mcp:10m rate=30r/m;` 与 `limit_req_status 429;`，location 内 `burst=10`。后端仍有并发信号量、请求体上限与渲染超时兜底。
- **超时**：`proxy_read_timeout`/`proxy_send_timeout` 取 130s，覆盖渲染超时（默认 120s）。
- **`/v1/`、`/healthz` 仍返回 404**：公网 MCP 不扩大到上传 API 或健康检查。

公网 MCP 意味着任何持有 Token 的第三方都能调用渲染并向 `/docs/` 发布页面；Token 一旦泄露应立即轮换（轮换会使所有预览会话失效）。如需按调用方隔离，应为不同第三方分别签发 Token 并在 Nginx 层按 `Authorization` 映射限速，当前版本只支持单一 Token。

## 页面公开边界

### 从 Markdown 直接打开页面（当前行为）

- **编辑与实时预览**：库中的 `notes/guide.md` 对应 `/preview/edit?path=notes%2Fguide.md`。`path` 是相对 `library_directory` 的路径，需用 URL query 编码；不能传服务器绝对路径，也不能绕过目录和符号链接校验。浏览器需要已有有效编辑会话；当前直接访问编辑路由时不会自动保留目标并完成登录，首次使用应先访问 `/preview/` 登录，再打开直达链接。
- **受保护的阅读页面**：同一文件对应 `/preview/view?path=notes%2Fguide.md`，沿用编辑会话鉴权和相同路径边界。每次打开/浏览器刷新读取并渲染最新保存的 Markdown，使用隔离 iframe 展示，不生成公开发布物；不自动刷新，不提供“刷新最新内容”按钮。顶部可按文档库文件名顺序切换同目录上一篇／下一篇（忽略大小写，大小写同名时按原名排序；首尾禁用、不循环、不跨子目录），也可返回文档库或切换编辑。文档库提供文件路径搜索、目录筛选及阅读/编辑入口。这里只是阅读布局，不是独立只读账号权限；若需禁止保存，还要配置 `preview.write_back: false`。
- **预览内链接跳转**：渲染产物由浏览器端转换，服务端向隔离 iframe 注入链接改写脚本。指向库内其他 Markdown 的相对链接按当前文档目录解析并改写为 `/preview/view?path=...`，阅读页中点击在当前页面跳转，`#片段` 跳转后滚动到目标标题；编辑器预览中的库内链接以新标签页打开阅读页，避免丢失未保存编辑。改写失败的链接（如越过库根目录）保持原样，目标路径仍由服务端重新校验。
- **发布后的阅读页面**：调用 `publish_document`，传入公开目录内的相对路径和 Markdown 内容，使用返回的 `public_url`。其形态按 URL 映射规则推导：`public/guide/intro.md` → `/docs/guide/intro`（省略 `.md`），目录的 `README.md` → `/docs/guide/`；带 `.md`/`.markdown`/`.txt` 后缀的 URL 返回原文。`list_documents` 按 prefix 分页浏览公开目录。
- **公开跟随源文件**：`/docs/` 页面在访问时实时渲染并带 ETag 强制重新验证，覆盖或删除 `public/` 内的源文件立即生效，没有孤立旧快照。页面内容哈希即缓存键，进程内 LRU（默认 `128 MiB`）只加速重复访问。
- **私有与公开的边界就是目录**：`library_directory` 中 `public/` 之外的内容不经 `/docs/` 提供；保存库内其他位置的 Markdown 不影响公开文档。预览路由可读取整个库；启用预览写回时保存 `public/` 内文件同样会更新线上内容，并非两个互不写入的目录。

当前 `/docs/` 页面不要求 Bearer Token。它是**公开可索引**的文档层：

- URL 与公开目录中的源文件路径一一对应，可被猜测；
- 没有目录列表（无 `README.md` 的目录返回 404）；
- 失败（不存在、路径非法、渲染失败、过载）统一返回简洁的 HTML 404 页面，不暴露内部错误码；
- 响应允许搜索引擎索引，不设置 `noindex`；
- 持有 URL 的任何人仍可以访问；
- 下线即删除 `public/` 内的源文件；当前没有逐用户授权。

因此不得将其描述为“私有页面”。敏感文档需要放在 `public/` 之外，或在 Nginx、SSO、VPN 或访问控制层额外保护。

`/preview/` 与之不同：它需要会话 cookie，且会话 cookie 只能由持有 `AI_DOCS_API_TOKEN` 的一方换取。但它一次成功换取后，浏览器在 `preview.session_seconds` 内持续有效，因此仍必须叠加边缘层鉴权，不能仅凭 token 交换就判定为“私有”。

## 直接公网监听

只有用户明确接受风险时才修改：

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 18080,
    "public": { "scheme": "http", "host": "203.0.113.10", "port": 18080 }
  },
  "mcp": {
    "reference": {
      "scheme": "http", "host": "127.0.0.1", "port": 18080, "path": "/mcp"
    }
  }
}
```

必须同时说明：

- `0.0.0.0` 只是监听地址，不是可访问 URL；
- Python 服务不会自动提供 HTTPS；
- 需要防火墙、TLS 终止、访问日志、限流和 Token；
- API/MCP 也会进入公网监听面；
- 推荐改用 Nginx、Caddy、Traefik、Cloudflare Tunnel 或 VPN。

## 子路径

文档和静态资源可以使用子路径前缀：

```json
{
  "server": {
    "public": { "scheme": "https", "host": "example.com", "port": 443 },
    "documents_prefix": "/ai-docs/docs/"
  }
}
```

最终 URL：

```text
https://example.com/ai-docs/docs/guide/intro
```

对应 Nginx location 也必须同步使用这些前缀。公开 origin 只由 `server.public.scheme/host/port` 组成，不包含子路径。
