[English](README.md) | [繁體中文](README.zh.md)

# sync-config

將 Claude Code 設定同步到 Gemini CLI 和 Codex CLI，確保在切換 AI 程式設計助手時擁有一致的工具和知識環境。

## 功能特色

此技能將以下項目從 Claude Code 同步到其他 CLI：

| 項目 | Gemini CLI | Codex CLI |
|------|:----------:|:---------:|
| MCP 伺服器 | 是 | 是 |
| 技能（SKILL.md） | 是 | 是 |
| 專案指示（CLAUDE.md） | 是（GEMINI.md） | 是（AGENTS.md） |
| 自訂代理 | 是 | 否 |
| 鉤子（Hooks） | 是（事件名稱對應） | 否 |

關鍵行為：
- **MCP**：優先使用目標 CLI 的 `mcp add` 命令；退回至直接編輯設定檔。
- **技能**：複製整個技能目錄，保留 `scripts/` 和 `references/`。自動跳過 `sync-config` 本身和 CLI 專屬技能。
- **指示**：複製 `CLAUDE.md` 為 `GEMINI.md` / `AGENTS.md`，附帶同步標記註解。
- **代理**：轉換 frontmatter（工具名稱、結構）為 Gemini 格式。
- **鉤子**：將 Claude Code 事件名稱對應到 Gemini 等效名稱（例如 `PreToolUse` 對應 `BeforeTool`）。

## 安裝

將此倉庫 clone 到 Claude Code 技能目錄：

```bash
git clone https://github.com/joneshong-skills/sync-config.git ~/.claude/skills/sync-config
```

需要 Python 3。

## 使用方式

設定快捷方式：

```bash
SC="~/.local/bin/python3 ~/.claude/skills/sync-config/scripts/sync_config.py"
```

### 常用命令

```bash
# 檢視跨 CLI 同步狀態
$SC status

# 同步 MCP 伺服器到所有目標
$SC sync mcp

# 同步技能（所有可移植的技能）
$SC sync skills

# 同步專案指示（在專案目錄中執行）
$SC sync instructions

# 一次同步所有項目
$SC sync all

# 指定特定 CLI
$SC sync mcp --target gemini
$SC sync all --target codex
```

### 選擇性技能同步

```bash
# 只同步特定技能
$SC sync skills --include team-tasks,openclaw-mentor

# 排除特定技能
$SC sync skills --exclude create-skill
```

## 專案結構

```
sync-config/
├── SKILL.md                        # 技能定義
├── README.md                       # 英文說明
├── README.zh.md                    # 繁體中文說明（本檔案）
├── scripts/
│   ├── sync_config.py              # 主要入口點
│   ├── sync_gemini.py              # Gemini CLI 同步邏輯
│   └── sync_codex.py               # Codex CLI 同步邏輯
├── references/
│   └── format-mapping.md           # 設定格式對應參考
└── examples/
    └── sync-demo.sh                # 完整同步流程示範
```

## 授權

MIT
