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
