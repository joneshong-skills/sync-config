#!/usr/bin/env python3
"""sync_copilot.py - Copilot CLI adapter for sync-config.

Handles: MCP servers, Instructions (.github/copilot-instructions.md).
Does NOT support: Skills (no discovery), Hooks, Custom Commands.
Config: ~/.copilot/mcp-config.json
Instructions: .github/copilot-instructions.md (project) | ~/.copilot/instructions.md (global)
"""

import json
from pathlib import Path

HOME = Path.home()
COPILOT_DIR = HOME / ".copilot"
COPILOT_MCP_CONFIG = COPILOT_DIR / "mcp-config.json"

# Claude -> Copilot path mapping (longer/more specific first)
COPILOT_PATH_MAP = [
    ("~/.claude/skills/", "~/.agents/skills/"),
    ("~/.claude/CLAUDE.md", ".github/copilot-instructions.md"),
    ("~/.claude/mcp.json", "~/.copilot/mcp-config.json"),
    ("~/.claude/settings.json", "~/.copilot/settings"),
    ("~/.claude/data/", "~/.copilot/data/"),
    ("~/.claude/agents/", "~/.copilot/agents/"),
    ("~/.claude/", "~/.copilot/"),
    (".claude/CLAUDE.md", ".github/copilot-instructions.md"),
    (".claude/skills/", ".agents/skills/"),
    (".claude/", ".copilot/"),
    (".claudeignore", ".copilotignore"),
]

COPILOT_FILENAME_MAP = {
    "CLAUDE.md": "copilot-instructions.md",
}


class CopilotAdapter:
    """Sync adapter for GitHub Copilot CLI."""

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
        """Sync MCP servers to ~/.copilot/mcp-config.json.

        Copilot uses array format: {"mcpServers": [{"name": ..., ...}]}
        """
        # Read existing config to preserve non-MCP fields
        existing = {}
        if COPILOT_MCP_CONFIG.exists():
            try:
                existing = json.loads(COPILOT_MCP_CONFIG.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        mcp_list = []
        for name, info in servers.items():
            server_type = info.get("type", "stdio")
            entry = {"name": name}

            if server_type in ("http", "streamable_http", "sse"):
                url = info.get("url", "")
                if url:
                    entry["url"] = url
                if server_type == "sse":
                    entry["transport"] = "sse"
            else:  # stdio
                command = info.get("command", "")
                args = info.get("args", [])
                if command:
                    entry["command"] = command
                    if args:
                        entry["args"] = args

            env_vars = info.get("env", {})
            if env_vars:
                entry["env"] = env_vars

            mcp_list.append(entry)
            print(f"  \u2705 {name}")

        # Report removals
        old_names = {s.get("name") for s in existing.get("mcpServers", []) if isinstance(s, dict)}
        new_names = {s["name"] for s in mcp_list}
        for stale in sorted(old_names - new_names):
            print(f"  \U0001f5d1\ufe0f  \u79fb\u9664\u904e\u6642 MCP: {stale}")

        existing["mcpServers"] = mcp_list
        COPILOT_DIR.mkdir(parents=True, exist_ok=True)
        COPILOT_MCP_CONFIG.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  \U0001f4e1 \u5df2\u5beb\u5165 {COPILOT_MCP_CONFIG}")

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def sync_skills(self, source_dir: Path, skill_names: list):
        """Copilot CLI has no native skill discovery system.

        Skills synced to ~/.agents/skills/ by Codex adapter are accessible
        if referenced in AGENTS.md instructions.
        """
        agents_skills = HOME / ".agents" / "skills"
        if agents_skills.is_dir():
            existing = [d.name for d in agents_skills.iterdir() if d.is_dir()]
            print(
                f"  \u23ed\ufe0f  Copilot \u7121 Skill \u767c\u73fe\u7cfb\u7d71\uff0c"
                f"\u4f46 ~/.agents/skills/ \u5df2\u6709 {len(existing)} \u500b\uff08\u7531 Codex \u540c\u6b65\uff09"
            )
        else:
            print("  \u23ed\ufe0f  Copilot CLI \u4e0d\u652f\u63f4 Skill \u767c\u73fe\u7cfb\u7d71")

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path, extra_files=None):
        """Write .github/copilot-instructions.md (project-level)."""
        github_dir = target_dir / ".github"
        github_dir.mkdir(parents=True, exist_ok=True)
        target = github_dir / "copilot-instructions.md"
        self._write_instructions(source, target, extra_files=extra_files)

    def sync_global_instructions(self, source: Path, extra_files=None):
        """Write ~/.copilot/instructions.md (global-level).

        Requires COPILOT_CUSTOM_INSTRUCTIONS_DIRS=$HOME/.copilot in shell env.
        """
        COPILOT_DIR.mkdir(parents=True, exist_ok=True)
        target = COPILOT_DIR / "instructions.md"
        self._write_instructions(source, target, extra_files=extra_files)
        print(
            "  \U0001f4a1 \u63d0\u793a\uff1a"
            "\u8acb\u78ba\u8a8d ~/.zshenv \u5305\u542b "
            "COPILOT_CUSTOM_INSTRUCTIONS_DIRS=$HOME/.copilot"
        )

    def _write_instructions(self, source: Path, target: Path, extra_files=None):
        """Transform CLAUDE.md content for Copilot CLI."""
        content = source.read_text(encoding="utf-8")

        # Append extra files (rules, knowledge)
        if extra_files:
            content += "\n\n"
            for ef in extra_files:
                section = ef.stem.replace("-", " ").replace("_", " ").title()
                ef_content = ef.read_text(encoding="utf-8")
                content += f"\n---\n\n# {section}\n\n{ef_content}\n"

        content = self._transform_for_copilot(content)

        header = (
            "<!-- Synced from CLAUDE.md by sync-config -->\n"
            "<!-- \u624b\u52d5\u4fee\u6539\u53ef\u80fd\u5728\u4e0b\u6b21\u540c\u6b65\u6642\u88ab\u8986\u84cb -->\n\n"
        )

        target.write_text(header + content, encoding="utf-8")
        print(f"  \u2705 {source.name} \u2192 {target}")

    def _transform_for_copilot(self, content: str) -> str:
        """Apply all Claude -> Copilot mappings to instruction content."""
        # 1. Path mappings (longer patterns first)
        for claude_path, copilot_path in COPILOT_PATH_MAP:
            content = content.replace(claude_path, copilot_path)

        # 2. File name references (backtick-wrapped)
        for claude_name, copilot_name in COPILOT_FILENAME_MAP.items():
            content = content.replace(f"`{claude_name}`", f"`{copilot_name}`")

        # 3. CLI command references
        content = content.replace("`claude mcp ", "`copilot mcp ")
        content = content.replace("claude mcp list", "copilot (MCP via mcp-config.json)")
        content = content.replace("claude mcp add", "(edit ~/.copilot/mcp-config.json)")

        return content
