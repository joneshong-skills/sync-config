#!/usr/bin/env python3
"""sync_antigravity.py - Antigravity CLI adapter for sync-config.

Handles: MCP servers, Skills, Instructions (GEMINI.md), Custom Agents, Hooks.
Config: ~/.gemini/settings.json, ~/.gemini/skills/, ~/.gemini/agents/
"""

import json
import shutil
from pathlib import Path

HOME = Path.home()
ANTIGRAVITY_SETTINGS = HOME / ".gemini" / "settings.json"
ANTIGRAVITY_SKILLS = HOME / ".gemini" / "skills"  # legacy, kept for reference
AGENTS_SKILLS = (
    HOME / ".agents" / "skills"
)  # unified target (Antigravity auto-discovers)
ANTIGRAVITY_AGENTS = HOME / ".gemini" / "agents"

# Claude → Antigravity hook event name mapping
ANTIGRAVITY_HOOK_EVENT_MAP = {
    "SessionStart": "SessionStart",
    "UserPromptSubmit": "BeforeAgent",
    "PreToolUse": "BeforeTool",
    "PostToolUse": "AfterTool",
    "PreCompact": "PreCompress",
    "Stop": "AfterAgent",
    "SessionEnd": "SessionEnd",
    "Notification": "Notification",
    # Claude-only (no Antigravity equivalent):
    # "SubagentStart", "SubagentStop", "PermissionRequest"
}

# Claude → Antigravity tool name mapping (verified against Antigravity CLI 0.41 builtin names)
ANTIGRAVITY_TOOL_NAME_MAP = {
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "replace",
    "Bash": "run_shell_command",
    "Glob": "glob",
    "Grep": "grep_search",
    "LS": "list_directory",
    "WebFetch": "web_fetch",
    "WebSearch": "google_web_search",
    "TodoWrite": "write_todos",
    "Task": "invoke_agent",
}


# Claude → Antigravity path mapping (order: longer/more specific first)
ANTIGRAVITY_PATH_MAP = [
    ("~/.claude/skills/", "~/.agents/skills/"),
    ("~/.claude/agents/", "~/.gemini/agents/"),
    ("~/.claude/CLAUDE.md", "~/.gemini/GEMINI.md"),
    ("~/.claude/mcp.json", "~/.gemini/settings.json"),
    ("~/.claude/settings.json", "~/.gemini/settings.json"),
    ("~/.claude/data/", "~/.gemini/data/"),
    (".claude/skills/", ".agents/skills/"),
    (".claude/agents/", ".gemini/agents/"),
    (".claudeignore", ".geminiignore"),
]

# Standalone file name replacements (only when clearly a file reference)
ANTIGRAVITY_FILENAME_MAP = {
    "CLAUDE.md": "GEMINI.md",
}


class AntigravityAdapter:
    """Sync adapter for Antigravity CLI."""

    skills_dir = str(AGENTS_SKILLS)

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
        """Sync MCP servers to Antigravity CLI via direct settings.json edit.

        agy has no mcp subcommand — always writes directly to ~/.gemini/settings.json.
        Idempotent: full replacement of mcpServers block. Fails loud on write error.
        """
        settings = self._read_settings()
        old_mcps = set(settings.get("mcpServers", {}).keys())
        new_mcps = {}

        for name, info in servers.items():
            server_type = info.get("type", "stdio")
            entry = {}
            if server_type in ("http", "streamable_http"):
                entry["httpUrl"] = info.get("url", "")
            elif server_type == "sse":
                entry["url"] = info.get("url", "")
            else:  # stdio
                entry["command"] = info.get("command", "")
                if info.get("args"):
                    entry["args"] = info["args"]
                if info.get("env"):
                    entry["env"] = info["env"]
            new_mcps[name] = entry
            print(f"  ✅ {name}")

        # Report stale removals
        stale = old_mcps - set(new_mcps.keys())
        for name in sorted(stale):
            print(f"  🗑️  移除過時 MCP: {name}")

        settings["mcpServers"] = new_mcps
        self._write_settings(settings)

    def _add_mcp_server(self, name: str, info: dict):
        """Add or update a single MCP server entry in ~/.gemini/settings.json.

        agy has no mcp subcommand — directly edits the JSON file.
        Idempotent: overwrites existing entry with same name.
        Fails loud: raises on write error.
        """
        settings = self._read_settings()
        mcp = settings.setdefault("mcpServers", {})

        server_type = info.get("type", "stdio")
        entry = {}

        if server_type in ("http", "streamable_http"):
            entry["httpUrl"] = info.get("url", "")
        elif server_type == "sse":
            entry["url"] = info.get("url", "")
        else:  # stdio
            entry["command"] = info.get("command", "")
            if info.get("args"):
                entry["args"] = info["args"]
            if info.get("env"):
                entry["env"] = info["env"]

        mcp[name] = entry
        self._write_settings(settings)
        print(f"  ✅ {name} (寫入 settings.json)")

    def _remove_mcp_server(self, name: str):
        """Remove a single MCP server entry from ~/.gemini/settings.json.

        agy has no mcp subcommand — directly edits the JSON file.
        No-op if entry does not exist. Fails loud on write error.
        """
        settings = self._read_settings()
        mcp = settings.get("mcpServers", {})
        if name in mcp:
            del mcp[name]
            settings["mcpServers"] = mcp
            self._write_settings(settings)
            print(f"  🗑️  已移除 MCP: {name}")
        else:
            print(f"  ℹ️  MCP 不存在，略過: {name}")

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def sync_skills(self, source_dir: Path, skill_names: list):
        """Sync skills to ~/.agents/skills/ (unified target).

        Antigravity CLI hardcodes discovery from both ~/.gemini/skills/ and
        ~/.agents/skills/. To avoid 'Skill conflict detected' warnings,
        we write ONLY to ~/.agents/skills/ and keep ~/.gemini/skills/ empty.
        """
        AGENTS_SKILLS.mkdir(parents=True, exist_ok=True)
        synced = 0

        for name in skill_names:
            src = source_dir / name
            dst = AGENTS_SKILLS / name

            if dst.exists():
                shutil.rmtree(dst)

            shutil.copytree(src, dst)

            # Transform SKILL.md: translate tool names for Antigravity
            skill_md = dst / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                content = self._transform_skill_md(content)
                skill_md.write_text(content, encoding="utf-8")

            synced += 1

        print(f"  📁 共同步 {synced} 個 skills → ~/.agents/skills/")
        print(
            "  ℹ️  Antigravity CLI 從 ~/.agents/skills/ 自動探索（~/.gemini/skills/ 已清空）"
        )

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path, extra_files=None):
        """Copy CLAUDE.md + extra files → GEMINI.md with header note (project-level)."""
        self._write_antigravity_md(
            source, target_dir / "GEMINI.md", extra_files=extra_files
        )

    def sync_global_instructions(self, source: Path, extra_files=None):
        """Copy ~/.claude/CLAUDE.md + rules → ~/.gemini/GEMINI.md."""
        target = HOME / ".gemini" / "GEMINI.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_antigravity_md(source, target, extra_files=extra_files)

    def _write_antigravity_md(self, source: Path, target: Path, extra_files=None):
        """Transform CLAUDE.md content for Antigravity CLI and write as GEMINI.md."""
        content = source.read_text(encoding="utf-8")

        # Append extra files (rules, knowledge)
        if extra_files:
            content += "\n\n"
            for ef in extra_files:
                section = ef.stem.replace("-", " ").replace("_", " ").title()
                ef_content = ef.read_text(encoding="utf-8")
                content += f"\n---\n\n# {section}\n\n{ef_content}\n"

        content = self._transform_for_antigravity(content)

        header = (
            "<!-- Synced from CLAUDE.md by sync-config -->\n"
            "<!-- 手動修改可能在下次同步時被覆蓋 -->\n\n"
        )

        target.write_text(header + content, encoding="utf-8")
        print(f"  ✅ {source.name} → {target}")

    def _transform_for_antigravity(self, content: str) -> str:
        """Apply all Claude → Antigravity mappings to instruction content."""
        import re

        # 1. Path mappings (longer patterns first to avoid partial matches)
        for claude_path, antigravity_path in ANTIGRAVITY_PATH_MAP:
            content = content.replace(claude_path, antigravity_path)

        # 2. File name references: `CLAUDE.md` → `GEMINI.md` (backtick-wrapped)
        for claude_name, antigravity_name in ANTIGRAVITY_FILENAME_MAP.items():
            content = content.replace(f"`{claude_name}`", f"`{antigravity_name}`")

        # 3. Tool name mappings (backtick-wrapped to avoid false positives)
        for claude_tool, antigravity_tool in ANTIGRAVITY_TOOL_NAME_MAP.items():
            content = content.replace(f"`{claude_tool}`", f"`{antigravity_tool}`")
            # Also handle "the X tool" pattern
            content = re.sub(
                rf"\bthe {claude_tool} tool\b",
                f"the {antigravity_tool} tool",
                content,
            )

        # 4. Hook event name mappings (backtick-wrapped)
        for claude_event, antigravity_event in ANTIGRAVITY_HOOK_EVENT_MAP.items():
            if claude_event != antigravity_event:
                content = content.replace(f"`{claude_event}`", f"`{antigravity_event}`")

        # 5. CLI command references (agy has no mcp subcommand — preserve for doc purposes)
        content = content.replace("`claude mcp ", "`agy mcp ")
        content = content.replace("claude mcp list", "agy mcp list")
        content = content.replace("claude mcp add", "agy mcp add")
        content = content.replace("claude mcp get", "agy mcp get")

        return content

    def _transform_skill_md(self, content: str) -> str:
        """Transform SKILL.md for Antigravity: translate tool names + paths."""
        import re as _re

        try:
            import sys as _sys

            _sys.path.insert(0, str(HOME / "workshop" / "libs" / "cli-dic"))
            from cli_dic import get

            antigravity_entry = get("antigravity")
        except (ImportError, KeyError):
            return content  # cli-dic not available, skip translation

        # Translate tools: line in YAML frontmatter
        def _replace_tools(m):
            original = m.group(1)
            translated = antigravity_entry.tool_names.translate_list(original)
            return f"tools: {translated}"

        content = _re.sub(
            r"^tools:\s*(.+)$", _replace_tools, content, count=1, flags=_re.MULTILINE
        )

        # Apply path and content mappings
        content = self._transform_for_antigravity(content)

        return content

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def sync_commands(self, command_files: list):
        """Copy command .md files to ~/.gemini/commands/, preserving subdirectories."""
        antigravity_cmds = HOME / ".gemini" / "commands"
        antigravity_cmds.mkdir(parents=True, exist_ok=True)
        synced = 0

        for src in command_files:
            # Preserve subdirectory structure (e.g., pm/create.md)
            rel = src.relative_to(HOME / ".claude" / "commands")
            dst = antigravity_cmds / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  ✅ {rel}")
            synced += 1

        print(f"  📁 共同步 {synced} 個 commands")

    # ------------------------------------------------------------------
    # Custom Agents
    # ------------------------------------------------------------------
    def sync_agents(self, agent_files: list):
        """Copy and convert agent .md files to ~/.gemini/agents/."""
        ANTIGRAVITY_AGENTS.mkdir(parents=True, exist_ok=True)

        for src in agent_files:
            content = src.read_text(encoding="utf-8")
            converted = self._convert_agent_frontmatter(content)

            dst = ANTIGRAVITY_AGENTS / src.name
            dst.write_text(converted, encoding="utf-8")
            print(f"  ✅ {src.name} → {dst}")

    # Frontmatter keys Antigravity's agent schema rejects (Claude-only metadata)
    _ANTIGRAVITY_AGENT_DROP_KEYS = frozenset(
        {
            "color",
            "maxTurns",
            "max_turns",
            "memory",
            "skills",
            "disallowed-tools",
            "permission-mode",
            "argument-hint",
        }
    )

    def _convert_agent_frontmatter(self, content):
        """Convert Claude agent frontmatter to Antigravity-compatible YAML.

        - tools: accept "A, B, C" string or YAML list, emit YAML flow array
          with Claude→Antigravity tool name mapping.
        - Drop Claude-only fields the Antigravity schema rejects.
        - Always emit `kind: local`.
        """
        import re

        import yaml

        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
        if not m:
            return content
        fm_text, body = m.group(1), m.group(2)

        try:
            fm = yaml.safe_load(fm_text) or {}
            if not isinstance(fm, dict):
                return content
        except yaml.YAMLError:
            return content

        # Normalize tools → list, then map names
        tools_raw = fm.pop("tools", None)
        if tools_raw is None:
            tools_raw = fm.pop("allowed-tools", None)
        else:
            fm.pop("allowed-tools", None)

        tools_list = []
        if isinstance(tools_raw, str):
            tools_list = [t.strip() for t in tools_raw.split(",") if t.strip()]
        elif isinstance(tools_raw, list):
            tools_list = [str(t).strip() for t in tools_raw if str(t).strip()]
        mapped_tools = [ANTIGRAVITY_TOOL_NAME_MAP.get(t, t) for t in tools_list]

        # Drop Claude-only keys
        for k in list(fm.keys()):
            if k in self._ANTIGRAVITY_AGENT_DROP_KEYS:
                fm.pop(k, None)

        # Re-emit in a stable, schema-friendly order
        ordered = {}
        for key in ("name", "description"):
            if key in fm:
                ordered[key] = fm.pop(key)
        if mapped_tools:
            ordered["tools"] = mapped_tools
        for key in ("model",):
            if key in fm:
                ordered[key] = fm.pop(key)
        ordered["kind"] = "local"
        for key, val in fm.items():
            ordered[key] = val

        new_fm = yaml.safe_dump(
            ordered,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=None,
        ).rstrip("\n")

        return f"---\n{new_fm}\n---\n\n{body.lstrip(chr(10))}"

    # ------------------------------------------------------------------
    # Hooks — DISABLED (2026-04-14)
    # ------------------------------------------------------------------
    # 不再同步任何 Claude Code hooks 到 Antigravity CLI。
    #
    # 原因：Claude Code 的 BeforeAgent/UserPromptSubmit hook 會呼叫
    # ~/.claude/hooks/dispatcher.py，內部執行 memvault cascade recall。
    # 當 memvault extract.py spawn agy CLI 時，CLI 啟動的 hook 會
    # 反向呼叫 memvault，形成循環依賴 → 進程卡死 5 分鐘後 timeout。
    #
    # 此方法現在也主動清除舊有 hooks 區塊，避免殘留設定繼續觸發循環。
    def sync_hooks(self, claude_hooks: dict):
        """No-op: hooks are no longer synced to Antigravity (prevents memvault → agy → memvault loop)."""
        settings = self._read_settings()
        removed = False
        if "hooks" in settings:
            del settings["hooks"]
            removed = True
            self._write_settings(settings)
        if removed:
            print("  🗑️  已清除 ~/.gemini/settings.json 中殘留的 hooks 區塊")
        print("  ⏭️  Antigravity hooks 同步已停用（循環依賴風險）")

    # ------------------------------------------------------------------
    # Settings I/O
    # ------------------------------------------------------------------
    def _read_settings(self):
        if ANTIGRAVITY_SETTINGS.exists():
            try:
                return json.loads(ANTIGRAVITY_SETTINGS.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_settings(self, data):
        ANTIGRAVITY_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        try:
            ANTIGRAVITY_SETTINGS.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            print(f"  ❌ 寫入 ~/.gemini/settings.json 失敗: {e}")
            raise
