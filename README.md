# sync-config

Synchronize Claude Code configuration to Gemini CLI and Codex CLI, ensuring a consistent tooling and knowledge environment when switching between AI coding assistants.

## What It Does

This skill syncs the following items from Claude Code to other CLIs:

| Item | Gemini CLI | Codex CLI |
|------|:----------:|:---------:|
| MCP Servers | Yes | Yes |
| Skills (SKILL.md) | Yes | Yes |
| Project Instructions (CLAUDE.md) | Yes (GEMINI.md) | Yes (AGENTS.md) |
| Custom Agents | Yes | No |
| Hooks | Yes (event name mapping) | No |

Key behaviors:
- **MCP**: Prefers the target CLI's `mcp add` command; falls back to editing config files directly.
- **Skills**: Copies entire skill directories, preserving `scripts/` and `references/`. Automatically skips `sync-config` itself and CLI-specific skills.
- **Instructions**: Copies `CLAUDE.md` as `GEMINI.md` / `AGENTS.md` with a sync marker comment.
- **Agents**: Converts frontmatter (tool names, structure) to Gemini format.
- **Hooks**: Maps Claude Code event names to Gemini equivalents (e.g., `PreToolUse` to `BeforeTool`).

## Installation

Clone this repository into your Claude Code skills directory:

```bash
git clone https://github.com/joneshong-skills/sync-config.git ~/.claude/skills/sync-config
```

Requires Python 3.

## Usage

Set up the shortcut:

```bash
SC="python3 ~/.claude/skills/sync-config/scripts/sync_config.py"
```

### Common Commands

```bash
# View cross-CLI sync status
$SC status

# Sync MCP servers to all targets
$SC sync mcp

# Sync skills (all portable ones)
$SC sync skills

# Sync project instructions (run inside a project directory)
$SC sync instructions

# Sync everything at once
$SC sync all

# Target a specific CLI
$SC sync mcp --target gemini
$SC sync all --target codex
```

### Selective Skill Sync

```bash
# Only sync specific skills
$SC sync skills --include team-tasks,openclaw-mentor

# Exclude specific skills
$SC sync skills --exclude create-skill
```

## Project Structure

```
sync-config/
├── SKILL.md                        # Skill definition
├── README.md                       # This file
├── scripts/
│   ├── sync_config.py              # Main entry point
│   ├── sync_gemini.py              # Gemini CLI sync logic
│   └── sync_codex.py               # Codex CLI sync logic
├── references/
│   └── format-mapping.md           # Config format mapping reference
└── examples/
    └── sync-demo.sh                # Full sync workflow demo
```

## License

MIT
