#!/usr/bin/env python3
"""sync_qwen.py - Qwen Code CLI adapter for sync-config.

Qwen Code is a fork of Gemini CLI by Alibaba (QwenLM/qwen-code). It shares
most of Gemini CLI's settings schema and tool names. Differences vs Gemini:

  - Config dir is ~/.qwen/ (not ~/.gemini/)
  - Instructions file is QWEN.md (not GEMINI.md)
  - No file-based custom agents (Qwen uses prompt-driven subagents);
    therefore sync_agents is intentionally not implemented.
  - Skills live under ~/.qwen/skills/ — NOT auto-discovered from
    ~/.agents/skills/, so we sync them directly into ~/.qwen/skills/.

Handles: MCP servers, Skills, Instructions (QWEN.md), Commands.
Does NOT support: Custom agents (no equivalent), Hooks (loop-risk: skipped).
"""

import json
import shutil
from pathlib import Path

HOME = Path.home()
QWEN_SETTINGS = HOME / ".qwen" / "settings.json"
QWEN_SKILLS = HOME / ".qwen" / "skills"
QWEN_COMMANDS = HOME / ".qwen" / "commands"

# Claude → Qwen tool name mapping — same as Gemini (Qwen inherits the white-list)
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

# Claude → Qwen path mapping
QWEN_PATH_MAP = [
    ("~/.claude/skills/", "~/.qwen/skills/"),
    ("~/.claude/CLAUDE.md", "~/.qwen/QWEN.md"),
    ("~/.claude/mcp.json", "~/.qwen/settings.json"),
    ("~/.claude/settings.json", "~/.qwen/settings.json"),
    ("~/.claude/data/", "~/.qwen/data/"),
    (".claude/skills/", ".qwen/skills/"),
    (".claudeignore", ".qwenignore"),
]

QWEN_FILENAME_MAP = {
    "CLAUDE.md": "QWEN.md",
}


class QwenAdapter:
    """Sync adapter for Qwen Code CLI."""

    skills_dir = str(QWEN_SKILLS)

    # ------------------------------------------------------------------
    # MCP — same schema as Gemini CLI (mcpServers, command/args/env, url, httpUrl)
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
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

        stale = old_mcps - set(new_mcps.keys())
        for name in sorted(stale):
            print(f"  🗑️  移除過時 MCP: {name}")

        settings["mcpServers"] = new_mcps
        self._write_settings(settings)

    # ------------------------------------------------------------------
    # Skills — Qwen reads ~/.qwen/skills/ (not ~/.agents/skills/)
    # ------------------------------------------------------------------
    def sync_skills(self, source_dir: Path, skill_names: list):
        QWEN_SKILLS.mkdir(parents=True, exist_ok=True)
        synced = 0

        for name in skill_names:
            src = source_dir / name
            dst = QWEN_SKILLS / name

            if dst.exists() or dst.is_symlink():
                if dst.is_symlink() or not dst.is_dir():
                    dst.unlink()
                else:
                    shutil.rmtree(dst)

            shutil.copytree(src, dst)

            skill_md = dst / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                content = self._transform_skill_md(content)
                skill_md.write_text(content, encoding="utf-8")
            synced += 1

        print(f"  📁 共同步 {synced} 個 skills → ~/.qwen/skills/")

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path, extra_files=None):
        self._write_qwen_md(source, target_dir / "QWEN.md", extra_files=extra_files)

    def sync_global_instructions(self, source: Path, extra_files=None):
        target = HOME / ".qwen" / "QWEN.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_qwen_md(source, target, extra_files=extra_files)

    def _write_qwen_md(self, source: Path, target: Path, extra_files=None):
        content = source.read_text(encoding="utf-8")

        if extra_files:
            content += "\n\n"
            for ef in extra_files:
                section = ef.stem.replace("-", " ").replace("_", " ").title()
                ef_content = ef.read_text(encoding="utf-8")
                content += f"\n---\n\n# {section}\n\n{ef_content}\n"

        content = self._transform_for_qwen(content)

        header = (
            "<!-- Synced from CLAUDE.md by sync-config -->\n"
            "<!-- 手動修改可能在下次同步時被覆蓋 -->\n\n"
        )

        target.write_text(header + content, encoding="utf-8")
        print(f"  ✅ {source.name} → {target}")

    def _transform_for_qwen(self, content: str) -> str:
        import re

        for claude_path, qwen_path in QWEN_PATH_MAP:
            content = content.replace(claude_path, qwen_path)

        for claude_name, qwen_name in QWEN_FILENAME_MAP.items():
            content = content.replace(f"`{claude_name}`", f"`{qwen_name}`")

        for claude_tool, qwen_tool in TOOL_NAME_MAP.items():
            content = content.replace(f"`{claude_tool}`", f"`{qwen_tool}`")
            content = re.sub(
                rf"\bthe {claude_tool} tool\b",
                f"the {qwen_tool} tool",
                content,
            )

        content = content.replace("`claude mcp ", "`qwen mcp ")
        content = content.replace("claude mcp list", "qwen mcp list")
        content = content.replace("claude mcp add", "qwen mcp add")

        return content

    def _transform_skill_md(self, content: str) -> str:
        import re as _re

        try:
            import sys as _sys

            _sys.path.insert(0, str(HOME / "workshop" / "libs" / "cli-dic"))
            from cli_dic import get

            qwen_entry = get("qwen")
        except (ImportError, KeyError, AttributeError):
            qwen_entry = None

        if qwen_entry is not None:

            def _replace_tools(m):
                original = m.group(1)
                translated = qwen_entry.tool_names.translate_list(original)
                return f"tools: {translated}"

            content = _re.sub(
                r"^tools:\s*(.+)$",
                _replace_tools,
                content,
                count=1,
                flags=_re.MULTILINE,
            )

        content = self._transform_for_qwen(content)
        return content

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def sync_commands(self, command_files: list):
        QWEN_COMMANDS.mkdir(parents=True, exist_ok=True)
        synced = 0

        for src in command_files:
            rel = src.relative_to(HOME / ".claude" / "commands")
            dst = QWEN_COMMANDS / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  ✅ {rel}")
            synced += 1

        print(f"  📁 共同步 {synced} 個 commands")

    # ------------------------------------------------------------------
    # Hooks — DISABLED (same loop-risk reasoning as Gemini adapter)
    # ------------------------------------------------------------------
    def sync_hooks(self, claude_hooks: dict):
        """No-op: hooks are not synced to Qwen (same memvault loop risk as Gemini)."""
        settings = self._read_settings()
        if "hooks" in settings:
            del settings["hooks"]
            self._write_settings(settings)
            print("  🗑️  已清除 ~/.qwen/settings.json 中殘留的 hooks 區塊")
        print("  ⏭️  Qwen hooks 同步已停用（循環依賴風險，與 Gemini 相同）")

    # ------------------------------------------------------------------
    # Settings I/O — preserve $version and other Qwen-specific top-level keys
    # ------------------------------------------------------------------
    def _read_settings(self):
        if QWEN_SETTINGS.exists():
            try:
                return json.loads(QWEN_SETTINGS.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_settings(self, data):
        QWEN_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        QWEN_SETTINGS.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
