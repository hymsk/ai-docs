# AI Docs

> AI Docs lets Agents and CLI users write, render, preview, and optionally publish Markdown documents: Mermaid, ECharts, Markmap, KaTeX, and multi-column layouts, delivered as offline single-file HTML or Web URLs.

[![CI](https://github.com/hymsk/ai-docs/actions/workflows/ci.yml/badge.svg)](https://github.com/hymsk/ai-docs/actions/workflows/ci.yml)

[中文](README.cn.md) | [English](README.md) · [Changelog](CHANGELOG.md) · [Security policy](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Agent guidelines](AGENTS.md)

Current public compatibility baseline: `v1.0.0rc1`. Project code is licensed under `AGPL-3.0-or-later`; bundled browser assets follow their own licenses, see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Use cases

- **Documents from your Agent**: let AI render research reports, architecture designs, and meeting notes into chart-rich HTML; when an `ai-docs` MCP is configured the skill returns shareable Web URLs, otherwise it produces local single files.
- **Local typesetting and preview**: build Markdown into offline single-file HTML from the command line (no CDN dependency), or write with a live split-pane preview; print to get a PDF.
- **A team document library**: optionally deploy the Web publishing service — `publish_document` writes straight into the public directory to go live, `/docs/` renders on request, and the resident preview library offers protected online reading and editing.

AI Docs never publishes anything automatically: the Web service is installed only on explicit request, and everything under `public/` is world-readable — confirm it contains no secrets before writing.

## Install

Choose by how you will use it; command-line users can skip installation and build directly (see [Usage](#usage)).

| Mode | When | What you do |
| --- | --- | --- |
| [Agent Skill](#agent-skill) | Let AI write documents following the skill workflow | Clone the full repository into your host's skill directory, keeping the name `ai-docs` |
| [Optional Web publishing](#optional-web-publishing) | Publish URLs, read and edit online | On top of the Agent Skill, explicitly run the installer (Linux + systemd) |

**One prompt for AI-assisted setup:**

```text
Clone https://github.com/hymsk/ai-docs.git into my [skill directory, e.g. ~/.claude/skills/ai-docs] (keep the directory name ai-docs and preserve local changes), follow "Install" in README.md to set it up for my [Agent Host, e.g. Claude Code], restart and verify ai-docs is visible; do not copy SKILL.md alone, do not install or start the Web MCP service, and ask me for any missing information.
```

### Agent Skill

```bash
mkdir -p "$HOME/.claude/skills"
git clone https://github.com/hymsk/ai-docs.git "$HOME/.claude/skills/ai-docs"
```

You can also unpack a full source archive; consult your host's documentation for Codex and OpenCode discovery paths. Restart or reload the host afterwards. **Do not copy `SKILL.md` alone**: the skill requires `scripts/`, `scripts/vendor/`, `references/`, `assets/`, `licenses/`, and the root license files.

Requirements: Node.js 18+ and Python 3.9+ (standard library only) — no dependencies to install; the Web MCP installer additionally needs Linux with systemd. Verify Mermaid, Markmap, KaTeX, and print output in a modern browser.

## Usage

### Build a single-file HTML

```bash
node scripts/build.js --input document.md --output document.html
```

The default output is a single file with dependencies inlined per content; unused diagram and highlighting assets are never written into the artifact. Multi-file site mode (`--output-mode multi`) writes dependencies into a configurable static directory for Nginx sub-path deployments; see [CLI and configuration](references/cli-and-config.md).

![Rendered output](docs/images/rendered-output.png)

### Live editing preview

```bash
node scripts/preview.js --input document.md --open
```

A Markdown editor on the left and an isolated preview from the same renderer on the right, refreshed after a short debounce; `Ctrl/⌘ + S` writes the source file back atomically, `Ctrl/⌘ + Enter` renders immediately. The preview binds `127.0.0.1:8000` by default; binding a non-loopback host issues a per-process random access token (the printed URL carries `?key=`, and `Authorization: Bearer` is also accepted), and `/save` rejects unauthorized requests. A directory-browsing static server is also available: `python3 scripts/serve.py --directory dist --port 8000`.

![Local live preview](docs/images/preview.png)

### Optional Web publishing

Skill synchronization never installs the Web MCP. Only on explicit user request:

```bash
python3 <SKILL_DIR>/scripts/web-mcp-manager.py plan
python3 <SKILL_DIR>/scripts/web-mcp-manager.py install
python3 <SKILL_DIR>/scripts/web-mcp-manager.py start
```

Default user-level installation: runtime and data under `~/.local/share/ai-docs-web/`, config and private credentials (`0600`) under `~/.config/ai-docs-web/`, with a user systemd unit registered automatically. Public HTTPS, Nginx Auth, and public MCP all require explicit opt-in; full installation and upgrade semantics are covered in the [Web MCP setup guide](references/web-mcp-setup.md).

Once installed, the service provides:

- **MCP publishing**: `publish_document` writes Markdown into the library's `public/` directory to publish it; `/docs/` renders it live per URL (the `.md` suffix is omitted, and a directory's `README.md` serves as its index).
- **Resident preview library**: `/preview/` lists every managed Markdown file; the browser login page exchanges `Authorization: Bearer` via `POST /preview/session` for an `HttpOnly` session cookie — **`?token=` is not accepted**, keeping tokens out of URLs and history.
- **Reading page** `/preview/view?path=...`: protected rendered reading, with the title navigating the library folder by folder and same-directory previous/next links.
- **Editor** `/preview/edit?path=...`: the same split editor as the local preview; saves are bounded by library quotas, and `preview.write_back: false` rejects write-back.

![Web reading page](docs/images/web-view.png)

![Web editor](docs/images/web-edit.png)

## MCP tools at a glance

| Tool | Purpose |
| --- | --- |
| `publish_document` | Write Markdown straight into the public directory to publish it; overwrites are refused by default, with `expected_sha256` optimistic concurrency; returns `public_url` |
| `list_documents` | Browse documents in the public directory by `prefix` and pagination |

Both tools require a Bearer token. Publishing success does not guarantee a clean render (`render_status: "not_checked"`) — confirm the result in a browser. Parameters and limits: [CLI and configuration](references/cli-and-config.md).

## Uninstall

| Scope | Procedure |
| --- | --- |
| Agent Skill | Delete `ai-docs/` from the host's skill directory and restart the host; generated HTML and the Web service are unaffected |
| Web MCP service | `python3 <SKILL_DIR>/scripts/web-mcp-manager.py uninstall`; library data is kept by default — use `--purge` once you confirm it is no longer needed |

Uninstalling does not remove generated HTML artifacts, library data, or deployment-time manual configuration such as Nginx rules and credentials; clean those up separately after confirming.

## Security boundaries

- **Built-in assets work offline**: scripts/styles avoid CDNs and the resource manifest rejects remote URLs; Markdown images may still reference remote hosts, so opening a standalone HTML may access the network.
- **`public/` is not private**: content is readable without a token, paths are predictable, and search engines may index it — never store secrets there.
- **Tokens never appear in URLs**: the Web API and MCP require a Bearer token by default; preview login exchanges it via POST for a session cookie; the token lives only in the private credentials file and is never passed to the renderer.
- Full boundaries: [`SECURITY.md`](SECURITY.md) and [security and limitations](references/safety-and-limitations.md).

## Feature overview

Markdown, tables, code highlighting and copy, folding; Mermaid diagrams of all kinds, static ECharts, Markmap mind maps, KaTeX math; restricted 2–4 column layouts, table of contents, light/dark themes, diagram zoom and SVG/PNG export, native browser printing; strict build-time ECharts validation. Authoring details: [authoring guide](references/authoring-guide.md) and the [component catalog](references/components/index.json).

ECharts output is currently static SSR (no tooltips or click interactions); PDFs come from browser printing. Graphviz is not bundled — `dot`/`graphviz` fences are rejected with a migration hint to Mermaid flowchart.

## Documentation

In-depth reference documents are currently written in Simplified Chinese.

- [CLI and JSON configuration](references/cli-and-config.md)
- [Authoring guide](references/authoring-guide.md)
- [Security and limitations](references/safety-and-limitations.md)
- [Web MCP setup](references/web-mcp-setup.md) · [HTTPS and external access](references/web-mcp-external-access.md)
- [Documentation-generation Agent methodology](references/agent-design/00-方法论总览.md) · [Agent workflow](SKILL.md)

## Development and license

Change only this repository when modifying the renderer, vendored assets, examples, or component docs; vendor updates must keep [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) in sync. Quality-gate commands and collaboration rules: [`CONTRIBUTING.md`](CONTRIBUTING.md).

[AGPL-3.0-or-later](LICENSE); bundled browser assets follow their own licenses, see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
