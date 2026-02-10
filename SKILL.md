---
name: sync-config
description: >
  This skill should be used when the user asks to "sync config to gemini",
  "sync MCP to codex", "sync skills across CLIs", "synchronize settings",
  "copy CLAUDE.md to GEMINI.md", or discusses cross-CLI configuration
  synchronization, MCP sharing, or multi-CLI setup.
version: 0.1.0
tools: Read, Edit, Bash
---

# Sync Config — 跨 CLI 設定同步

將 Claude Code 的設定同步到 Gemini CLI 和 Codex CLI，確保切換 CLI 時擁有一致的工具和知識。

## 支援的同步項目

| 項目 | → Gemini CLI | → Codex CLI |
|------|:-----------:|:----------:|
| MCP Servers | ✅ | ✅ |
| Skills (SKILL.md) | ✅ | ✅ |
| 專案指令 (CLAUDE.md) | ✅ → GEMINI.md | ✅ → AGENTS.md |
| Custom Agents | ✅ | ❌ 不支援 |
| Hooks | ✅ (事件名轉換) | ❌ 不支援 |

## CLI 路徑

```bash
SC="python3 ~/.claude/skills/sync-config/scripts/sync_config.py"
```

## 快速使用

### 查看跨 CLI 狀態

```bash
$SC status
```

### 同步 MCP Servers

```bash
# 同步到所有 CLI
$SC sync mcp

# 只同步到 Gemini
$SC sync mcp --target gemini

# 只同步到 Codex
$SC sync mcp --target codex
```

### 同步 Skills

```bash
# 同步所有可攜式 skills
$SC sync skills

# 只同步指定 skills
$SC sync skills --include team-tasks,openclaw-mentor

# 排除特定 skills
$SC sync skills --exclude create-skill
```

自動過濾規則：
- 跳過 `sync-config` 本身
- 跳過 CLI 專屬 skills（`claude-code-*`, `gemini-cli-*`, `codex-*`）
- 跳過目標 CLI 已有的同名 headless skills

### 同步專案指令

```bash
# 在專案目錄中執行
$SC sync instructions

# 指定專案目錄
$SC sync instructions --cwd /path/to/project
```

將 `CLAUDE.md` 複製為 `GEMINI.md` 和 `AGENTS.md`，自動加入同步標記。

### 同步 Custom Agents（僅 Gemini）

```bash
$SC sync agents --target gemini
```

自動轉換：
- `allowed-tools` → `tools`
- 工具名稱映射（`Read` → `read_file`, `Bash` → `run_shell_command` 等）
- 補充 `kind: local` 欄位

### 同步 Hooks（僅 Gemini）

```bash
$SC sync hooks --target gemini
```

事件名稱自動映射：

| Claude Code | Gemini CLI |
|-------------|------------|
| PreToolUse | BeforeTool |
| PostToolUse | AfterTool |
| Stop | AfterAgent |
| PreCompact | PreCompress |
| SessionStart | SessionStart |
| SessionEnd | SessionEnd |

### 全部同步

```bash
$SC sync all
$SC sync all --target gemini
```

## 同步策略

- **MCP**：優先使用目標 CLI 的 `mcp add` 指令，失敗時直接編輯設定檔
- **Skills**：整個目錄複製（覆蓋既有），保留 scripts/ 和 references/
- **Instructions**：加入 `<!-- Synced from CLAUDE.md -->` 標記
- **Agents**：複製並轉換 frontmatter 格式
- **Hooks**：轉換事件名稱和結構，合併到目標設定檔

## 格式對照

### MCP 設定檔位置

| CLI | 檔案 | 格式 |
|-----|------|------|
| Claude Code | `~/.claude/mcp.json` 或 CLI 內部 | JSON |
| Gemini CLI | `~/.gemini/settings.json` → `mcpServers` | JSON |
| Codex CLI | `~/.codex/config.toml` → `[mcp_servers]` | TOML |

### Skills 目錄

| CLI | 全域 | 專案 |
|-----|------|------|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Gemini CLI | `~/.gemini/skills/` | `.gemini/skills/` |
| Codex CLI | `~/.codex/skills/` | `agents/skills/` |

## Additional Resources

### Reference Files

- **`references/format-mapping.md`** — 完整的設定格式對照與轉換規則

### Example Files

- **`examples/sync-demo.sh`** — 完整同步流程範例
