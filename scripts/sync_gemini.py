#!/usr/bin/env python3
"""sync_gemini.py - Gemini CLI adapter for sync-config.

Handles: MCP servers, Skills, Instructions (GEMINI.md), Custom Agents, Hooks.
Config: ~/.gemini/settings.json, ~/.gemini/skills/, ~/.gemini/agents/
"""

import json
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
GEMINI_SETTINGS = HOME / ".gemini" / "settings.json"
GEMINI_SKILLS = HOME / ".gemini" / "skills"  # legacy, kept for reference
AGENTS_SKILLS = HOME / ".agents" / "skills"  # unified target (Gemini auto-discovers)
GEMINI_AGENTS = HOME / ".gemini" / "agents"

# Claude → Gemini hook event name mapping
HOOK_EVENT_MAP = {
    "SessionStart": "SessionStart",
    "UserPromptSubmit": "BeforeAgent",
    "PreToolUse": "BeforeTool",
    "PostToolUse": "AfterTool",
    "PreCompact": "PreCompress",
    "Stop": "AfterAgent",
    "SessionEnd": "SessionEnd",
    "Notification": "Notification",
    # Claude-only (no Gemini equivalent):
    # "SubagentStart", "SubagentStop", "PermissionRequest"
}

# Claude → Gemini tool name mapping (verified against Gemini CLI 0.41 builtin names)
TOOL_NAME_MAP = {
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


# Claude → Gemini path mapping (order: longer/more specific first)
GEMINI_PATH_MAP = [
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
GEMINI_FILENAME_MAP = {
    "CLAUDE.md": "GEMINI.md",
}


class GeminiAdapter:
    """Sync adapter for Gemini CLI."""

    skills_dir = str(AGENTS_SKILLS)

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
        """Sync MCP servers to Gemini CLI (file-based, atomic write).

        Always writes directly to settings.json instead of using `gemini mcp add`
        CLI, which silently drops entries for servers with complex arg lists.
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

    def _try_cli_mcp_add(self, name, info):
        """Try using `gemini mcp add` CLI command."""
        try:
            server_type = info.get("type", "stdio")

            if server_type in ("http", "streamable_http"):
                url = info.get("url", "")
                if not url:
                    return False
                # Remove existing first (ignore errors)
                subprocess.run(
                    ["gemini", "mcp", "remove", name], capture_output=True, timeout=10
                )
                result = subprocess.run(
                    ["gemini", "mcp", "add", name, url, "-t", "http"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    print(f"  ✅ {name} (HTTP: {url})")
                    return True
                # May fail if already exists, try file-based
                return False

            elif server_type == "sse":
                url = info.get("url", "")
                if not url:
                    return False
                subprocess.run(
                    ["gemini", "mcp", "remove", name], capture_output=True, timeout=10
                )
                result = subprocess.run(
                    ["gemini", "mcp", "add", name, url, "-t", "sse"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    print(f"  ✅ {name} (SSE: {url})")
                    return True
                return False

            else:  # stdio
                command = info.get("command", "")
                args = info.get("args", [])
                if not command:
                    return False
                subprocess.run(
                    ["gemini", "mcp", "remove", name], capture_output=True, timeout=10
                )
                cmd = ["gemini", "mcp", "add", name, command] + args + ["-t", "stdio"]
                env_vars = info.get("env", {})
                for k, v in env_vars.items():
                    cmd.extend(["-e", f"{k}={v}"])
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    print(f"  ✅ {name} (stdio: {command})")
                    return True
                return False

        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _file_mcp_add(self, name, info):
        """Fallback: directly edit ~/.gemini/settings.json."""
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

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def sync_skills(self, source_dir: Path, skill_names: list):
        """Sync skills to ~/.agents/skills/ (unified target).

        Gemini CLI hardcodes discovery from both ~/.gemini/skills/ and
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

            # Transform SKILL.md: translate tool names for Gemini
            skill_md = dst / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                content = self._transform_skill_md(content)
                skill_md.write_text(content, encoding="utf-8")

            synced += 1

        print(f"  📁 共同步 {synced} 個 skills → ~/.agents/skills/")
        print(
            "  ℹ️  Gemini CLI 從 ~/.agents/skills/ 自動探索（~/.gemini/skills/ 已清空）"
        )

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path, extra_files=None):
        """Copy CLAUDE.md + extra files → GEMINI.md with header note (project-level)."""
        self._write_gemini_md(source, target_dir / "GEMINI.md", extra_files=extra_files)

    def sync_global_instructions(self, source: Path, extra_files=None):
        """Copy ~/.claude/CLAUDE.md + rules → ~/.gemini/GEMINI.md."""
        target = HOME / ".gemini" / "GEMINI.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_gemini_md(source, target, extra_files=extra_files)

    def _write_gemini_md(self, source: Path, target: Path, extra_files=None):
        """Transform CLAUDE.md content for Gemini CLI and write as GEMINI.md."""
        content = source.read_text(encoding="utf-8")

        # Append extra files (rules, knowledge)
        if extra_files:
            content += "\n\n"
            for ef in extra_files:
                section = ef.stem.replace("-", " ").replace("_", " ").title()
                ef_content = ef.read_text(encoding="utf-8")
                content += f"\n---\n\n# {section}\n\n{ef_content}\n"

        content = self._transform_for_gemini(content)

        header = (
            "<!-- Synced from CLAUDE.md by sync-config -->\n"
            "<!-- 手動修改可能在下次同步時被覆蓋 -->\n\n"
        )

        target.write_text(header + content, encoding="utf-8")
        print(f"  ✅ {source.name} → {target}")

    def _transform_for_gemini(self, content: str) -> str:
        """Apply all Claude → Gemini mappings to instruction content."""
        import re

        # 1. Path mappings (longer patterns first to avoid partial matches)
        for claude_path, gemini_path in GEMINI_PATH_MAP:
            content = content.replace(claude_path, gemini_path)

        # 2. File name references: `CLAUDE.md` → `GEMINI.md` (backtick-wrapped)
        for claude_name, gemini_name in GEMINI_FILENAME_MAP.items():
            content = content.replace(f"`{claude_name}`", f"`{gemini_name}`")

        # 3. Tool name mappings (backtick-wrapped to avoid false positives)
        for claude_tool, gemini_tool in TOOL_NAME_MAP.items():
            content = content.replace(f"`{claude_tool}`", f"`{gemini_tool}`")
            # Also handle "the X tool" pattern
            content = re.sub(
                rf"\bthe {claude_tool} tool\b",
                f"the {gemini_tool} tool",
                content,
            )

        # 4. Hook event name mappings (backtick-wrapped)
        for claude_event, gemini_event in HOOK_EVENT_MAP.items():
            if claude_event != gemini_event:
                content = content.replace(f"`{claude_event}`", f"`{gemini_event}`")

        # 5. CLI command references
        content = content.replace("`claude mcp ", "`gemini mcp ")
        content = content.replace("claude mcp list", "gemini mcp list")
        content = content.replace("claude mcp add", "gemini mcp add")
        content = content.replace("claude mcp get", "gemini mcp get")

        return content

    def _transform_skill_md(self, content: str) -> str:
        """Transform SKILL.md for Gemini: translate tool names + paths."""
        import re as _re

        try:
            import sys as _sys

            _sys.path.insert(0, str(HOME / "workshop" / "libs" / "cli-dic"))
            from cli_dic import get

            gemini_entry = get("gemini")
        except (ImportError, KeyError):
            return content  # cli-dic not available, skip translation

        # Translate tools: line in YAML frontmatter
        def _replace_tools(m):
            original = m.group(1)
            translated = gemini_entry.tool_names.translate_list(original)
            return f"tools: {translated}"

        content = _re.sub(
            r"^tools:\s*(.+)$", _replace_tools, content, count=1, flags=_re.MULTILINE
        )

        # Apply path and content mappings
        content = self._transform_for_gemini(content)

        return content

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def sync_commands(self, command_files: list):
        """Copy command .md files to ~/.gemini/commands/, preserving subdirectories."""
        gemini_cmds = HOME / ".gemini" / "commands"
        gemini_cmds.mkdir(parents=True, exist_ok=True)
        synced = 0

        for src in command_files:
            # Preserve subdirectory structure (e.g., pm/create.md)
            rel = src.relative_to(HOME / ".claude" / "commands")
            dst = gemini_cmds / rel
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
        GEMINI_AGENTS.mkdir(parents=True, exist_ok=True)

        for src in agent_files:
            content = src.read_text(encoding="utf-8")
            converted = self._convert_agent_frontmatter(content)

            dst = GEMINI_AGENTS / src.name
            dst.write_text(converted, encoding="utf-8")
            print(f"  ✅ {src.name} → {dst}")

    # Frontmatter keys Gemini's agent schema rejects (Claude-only metadata)
    _GEMINI_AGENT_DROP_KEYS = frozenset(
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
        """Convert Claude agent frontmatter to Gemini-compatible YAML.

        - tools: accept "A, B, C" string or YAML list, emit YAML flow array
          with Claude→Gemini tool name mapping.
        - Drop Claude-only fields the Gemini schema rejects.
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
        mapped_tools = [TOOL_NAME_MAP.get(t, t) for t in tools_list]

        # Drop Claude-only keys
        for k in list(fm.keys()):
            if k in self._GEMINI_AGENT_DROP_KEYS:
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
    # 不再同步任何 Claude Code hooks 到 Gemini CLI。
    #
    # 原因：Claude Code 的 BeforeAgent/UserPromptSubmit hook 會呼叫
    # ~/.claude/hooks/dispatcher.py，內部執行 memvault cascade recall。
    # 當 memvault extract.py spawn gemini CLI 時，CLI 啟動的 hook 會
    # 反向呼叫 memvault，形成循環依賴 → 進程卡死 5 分鐘後 timeout。
    #
    # 此方法現在也主動清除舊有 hooks 區塊，避免殘留設定繼續觸發循環。
    def sync_hooks(self, claude_hooks: dict):
        """No-op: hooks are no longer synced to Gemini (prevents memvault → gemini → memvault loop)."""
        settings = self._read_settings()
        removed = False
        if "hooks" in settings:
            del settings["hooks"]
            removed = True
            self._write_settings(settings)
        if removed:
            print("  🗑️  已清除 ~/.gemini/settings.json 中殘留的 hooks 區塊")
        print("  ⏭️  Gemini hooks 同步已停用（循環依賴風險）")

    # ------------------------------------------------------------------
    # Settings I/O
    # ------------------------------------------------------------------
    def _read_settings(self):
        if GEMINI_SETTINGS.exists():
            try:
                return json.loads(GEMINI_SETTINGS.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_settings(self, data):
        GEMINI_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        GEMINI_SETTINGS.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
