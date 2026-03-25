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
GEMINI_SKILLS = HOME / ".gemini" / "skills"
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

# Claude → Gemini tool name mapping (common ones)
TOOL_NAME_MAP = {
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "edit_file",
    "Bash": "run_shell_command",
    "Glob": "glob_search",
    "Grep": "grep_search",
    "WebFetch": "web_fetch",
    "WebSearch": "web_search",
}


# Claude → Gemini path mapping (order: longer/more specific first)
GEMINI_PATH_MAP = [
    ("~/.claude/skills/", "~/.gemini/skills/"),
    ("~/.claude/agents/", "~/.gemini/agents/"),
    ("~/.claude/CLAUDE.md", "~/.gemini/GEMINI.md"),
    ("~/.claude/mcp.json", "~/.gemini/settings.json"),
    ("~/.claude/settings.json", "~/.gemini/settings.json"),
    ("~/.claude/data/", "~/.gemini/data/"),
    (".claude/skills/", ".gemini/skills/"),
    (".claude/agents/", ".gemini/agents/"),
    (".claudeignore", ".geminiignore"),
]

# Standalone file name replacements (only when clearly a file reference)
GEMINI_FILENAME_MAP = {
    "CLAUDE.md": "GEMINI.md",
}


class GeminiAdapter:
    """Sync adapter for Gemini CLI."""

    skills_dir = str(GEMINI_SKILLS)

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
                subprocess.run(["gemini", "mcp", "remove", name], capture_output=True, timeout=10)
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
                subprocess.run(["gemini", "mcp", "remove", name], capture_output=True, timeout=10)
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
                subprocess.run(["gemini", "mcp", "remove", name], capture_output=True, timeout=10)
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
        """Copy skill directories to ~/.gemini/skills/.

        Gemini CLI 0.28+ also reads ~/.agents/skills/ as an alias
        (priority 3.1, higher than ~/.gemini/skills/ priority 3).
        To avoid 'Skill conflict detected' warnings, skip skills
        that already exist in ~/.agents/skills/ (synced by Codex adapter).
        Gemini-exclusive skills still land in ~/.gemini/skills/.
        """
        GEMINI_SKILLS.mkdir(parents=True, exist_ok=True)
        agents_skills_dir = HOME / ".agents" / "skills"
        synced = 0
        skipped = 0

        for name in skill_names:
            src = source_dir / name
            dst = GEMINI_SKILLS / name

            # Skip if Codex already has this skill (Gemini reads both)
            if (agents_skills_dir / name / "SKILL.md").exists():
                skipped += 1
                continue

            if dst.exists():
                shutil.rmtree(dst)

            shutil.copytree(src, dst)
            print(f"  ✅ {name} → {dst}")
            synced += 1

        if skipped:
            print(
                f"  ⏭️  {skipped} 個 skills 已透過 ~/.agents/skills/ symlink 共享（Gemini 自動讀取）"
            )
        print(f"  📁 共同步 {synced} 個 Gemini 專屬 skills")

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

    def _convert_agent_frontmatter(self, content):
        """Convert Claude agent frontmatter to Gemini format."""
        # Translate tool names in allowed-tools
        for claude_name, gemini_name in TOOL_NAME_MAP.items():
            content = content.replace(f"  - {claude_name}", f"  - {gemini_name}")

        # Rename frontmatter fields
        content = content.replace("allowed-tools:", "tools:")
        content = content.replace(
            "permission-mode: plan", "# permission-mode: plan (not supported)"
        )
        content = content.replace(
            "disallowed-tools:", "# disallowed-tools (use excludeTools in extension):"
        )

        # Add kind field if missing
        if "kind:" not in content:
            content = content.replace("---\n\n", "kind: local\n---\n\n", 1)

        return content

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------
    def sync_hooks(self, claude_hooks: dict):
        """Convert Claude hooks to Gemini format and merge into settings."""
        settings = self._read_settings()
        gemini_hooks = settings.setdefault("hooks", {})

        converted_count = 0
        skipped_events = []

        for event, hook_list in claude_hooks.items():
            gemini_event = HOOK_EVENT_MAP.get(event)
            if not gemini_event:
                skipped_events.append(event)
                continue

            # Claude format: [{"hooks": [{"type":"command","command":"..."}]}]
            # Gemini format: [{"matcher":"*","hooks":[{"name":"...","type":"command","command":"..."}]}]
            converted_entries = []
            for entry in hook_list:
                hooks = entry.get("hooks", [])
                converted_hooks = []
                for h in hooks:
                    gh = {
                        "name": f"synced-{event.lower()}",
                        "type": h.get("type", "command"),
                        "command": h.get("command", ""),
                    }
                    if h.get("timeout"):
                        # Claude Code: seconds, Gemini CLI: milliseconds
                        gh["timeout"] = h["timeout"] * 1000
                    converted_hooks.append(gh)

                if converted_hooks:
                    converted_entries.append(
                        {
                            "matcher": entry.get("matcher", "*"),
                            "hooks": converted_hooks,
                        }
                    )

            if converted_entries:
                gemini_hooks[gemini_event] = converted_entries
                converted_count += 1
                print(f"  ✅ {event} → {gemini_event}")

        if skipped_events:
            print(f"  ⏭️  跳過 (Gemini 不支援): {', '.join(skipped_events)}")

        self._write_settings(settings)
        print(f"  📝 共轉換 {converted_count} 個 hook 事件")

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
