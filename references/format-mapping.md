# Format Mapping — 設定格式對照

跨 CLI 設定格式的完整轉換規則。

## MCP Server 格式對照

### HTTP / Streamable HTTP Server

**Claude Code** (`.claude/mcp.json`):
```json
{
  "mcpServers": {
    "deepwiki": {
      "type": "http",
      "url": "https://mcp.deepwiki.com/mcp"
    }
  }
}
```

**Gemini CLI** (`~/.gemini/settings.json`):
```json
{
  "mcpServers": {
    "deepwiki": {
      "httpUrl": "https://mcp.deepwiki.com/mcp"
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`):
```toml
[mcp_servers.deepwiki]
transport = "streamable_http"
url = "https://mcp.deepwiki.com/mcp"
```

### Stdio Server

**Claude Code**:
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "ghp_xxx" }
    }
  }
}
```

**Gemini CLI**:
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "$GITHUB_TOKEN" }
    }
  }
}
```

**Codex CLI**:
```toml
[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
```

> 注意：Codex TOML 格式不支援在設定檔中定義 env，需透過 shell 環境變數。

## Tool Name 映射

| Claude Code | Gemini CLI | 說明 |
|-------------|------------|------|
| `Read` | `read_file` | 讀取檔案 |
| `Write` | `write_file` | 建立/覆寫檔案 |
| `Edit` | `edit_file` | 編輯檔案 |
| `Bash` | `run_shell_command` | 執行 shell 指令 |
| `Glob` | `glob_search` | 檔案名稱搜尋 |
| `Grep` | `grep_search` | 檔案內容搜尋 |
| `WebFetch` | `web_fetch` | 抓取網頁 |
| `WebSearch` | `web_search` | 搜尋網路 |
| `Task` | (sub-agent tool name) | 子代理 |

> Codex CLI 的工具名稱與 Claude Code 差異較大，且不開放使用者在 skill frontmatter 中指定。

## Hook 事件映射

| Claude Code | Gemini CLI | 說明 |
|-------------|------------|------|
| `SessionStart` | `SessionStart` | 對話開始 |
| `UserPromptSubmit` | `BeforeAgent` | 使用者送出訊息後 |
| `PreToolUse` | `BeforeTool` | 工具執行前 |
| `PostToolUse` | `AfterTool` | 工具執行後 |
| `PreCompact` | `PreCompress` | Context 壓縮前 |
| `Stop` | `AfterAgent` | Agent 停止生成 |
| `SessionEnd` | `SessionEnd` | 對話結束 |
| `Notification` | `Notification` | 通知事件 |
| `SubagentStart` | — | ❌ Gemini 不支援 |
| `SubagentStop` | — | ❌ Gemini 不支援 |
| `PermissionRequest` | — | ❌ Gemini 不支援 |
| — | `BeforeModel` | ❌ Claude 無對應 |
| — | `AfterModel` | ❌ Claude 無對應 |
| — | `BeforeToolSelection` | ❌ Claude 無對應 |

## Agent Frontmatter 映射

| Claude Code | Gemini CLI | 說明 |
|-------------|------------|------|
| `model: opus` | `model: gemini-2.5-pro` | 需手動選擇對應模型 |
| `model: sonnet` | `model: gemini-2.5-flash` | 需手動選擇對應模型 |
| `model: haiku` | `model: gemini-2.5-flash` | 需手動選擇對應模型 |
| `allowed-tools:` | `tools:` | 欄位名不同 |
| `disallowed-tools:` | `excludeTools:` (extension 層級) | 位置不同 |
| `permission-mode:` | — | Gemini 無直接對應 |
| — | `kind: local` | Gemini 需要此欄位 |
| — | `temperature:` | Gemini 可額外設定 |
| — | `max_turns:` | Gemini 可額外設定 |

## 專案指令格式對照

### Claude Code → Gemini CLI

| 特性 | Claude Code (`CLAUDE.md`) | Gemini CLI (`GEMINI.md`) |
|------|--------------------------|--------------------------|
| 全域檔案 | `~/.claude/CLAUDE.md` | `~/.gemini/GEMINI.md` |
| 專案檔案 | `CLAUDE.md` in project root | `GEMINI.md` in project root |
| 階層載入 | 父目錄到 root | 父目錄到 `.git` root + JIT 發現 |
| Import 語法 | 不支援 | `@file.md` (相對/絕對路徑) |
| 可配置檔名 | 否 | 是 (`settings.json` → `context.fileName`) |
| Ignore 檔案 | `.claudeignore` | `.geminiignore` |
| 管理指令 | — | `/memory show`, `/memory refresh`, `/memory add` |

### Claude Code → Codex CLI

| 特性 | Claude Code (`CLAUDE.md`) | Codex CLI (`AGENTS.md`) |
|------|--------------------------|-------------------------|
| 全域檔案 | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` |
| 覆蓋檔案 | — | `AGENTS.override.md`（優先於 `AGENTS.md`）|
| 階層載入 | 父目錄到 root | Git root 到 CWD 的目錄走訪 |
| 備用檔名 | — | `project_doc_fallback_filenames` (config.toml) |
| 大小限制 | 無文件限制 | 32 KiB default (`project_doc_max_bytes`) |
| 自訂指令檔 | — | `model_instructions_file` (完全覆蓋 AGENTS.md) |

> **AGENTS.md 開放標準**：由 Linux Foundation / Agentic AI Foundation (AAIF) 主導，
> 60,000+ 開源專案採用。支援 Claude Code、Gemini CLI、GitHub Copilot、Cursor 等 20+ 工具。

## Skill SKILL.md 格式

三者格式幾乎一致：

```yaml
---
name: skill-name
description: This skill should be used when...
---

# Skill Title

Instructions here...
```

差異：
- Claude Code: 支援 `tools`, `context`, `disable-model-invocation`, `user-invocable`
- Gemini CLI: 基本相同，透過 extension 的 `gemini-extension.json` 做額外設定
- Codex CLI: 支援 `name`, `description`，可搭配 `agents/openai.yaml` 做 UI 元資料

### Skills 目錄差異

| CLI | 全域路徑 | 專案路徑 |
|-----|---------|---------|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Gemini CLI | `~/.gemini/skills/` | `.gemini/skills/` |
| Codex CLI | `$HOME/.agents/skills/` | `.agents/skills/` |

> **注意**：Codex CLI 的 Skills 路徑是 `$HOME/.agents/skills/`，不是 `~/.codex/skills/`。
> 也搜尋 `/etc/codex/skills/`（系統管理員級別）。

## Codex CLI Hooks（有限支援）

Codex CLI 目前僅有 `notify` 機制：

```toml
# ~/.codex/config.toml
notify = ["bash", "-lc", "afplay /System/Library/Sounds/Blow.aiff"]
```

- 唯一事件：`agent-turn-complete`
- 接收 JSON payload
- 完整 hooks 系統在 Issue #2109 (395+ 👍) 強烈要求中，多個 PR 進行中
- 未來可能新增完整生命週期 hooks（BeforeTool, AfterTool 等）
