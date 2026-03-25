#!/usr/bin/env python3
"""sync_opencode.py - OpenCode CLI adapter for sync-config.

Handles: MCP servers, Instructions (OPENCODE.md), Agents (config-based).
Does NOT support: Skills (no discovery), Hooks, Custom Commands.
Config: ~/.config/opencode/opencode.json
"""

import json
from pathlib import Path

HOME = Path.home()
OPENCODE_CONFIG_DIR = HOME / ".config" / "opencode"
OPENCODE_CONFIG = OPENCODE_CONFIG_DIR / "opencode.json"

# Claude -> OpenCode path mapping (longer/more specific first)
OPENCODE_PATH_MAP = [
    ("~/.claude/skills/", "(no skill system)"),
    ("~/.claude/CLAUDE.md", "OPENCODE.md"),
    ("~/.claude/mcp.json", "~/.config/opencode/opencode.json"),
    ("~/.claude/settings.json", "~/.config/opencode/opencode.json"),
    ("~/.claude/data/", "~/.local/share/opencode/"),
    ("~/.claude/agents/", "~/.config/opencode/ (agent key)"),
    ("~/.claude/", "~/.config/opencode/"),
    (".claude/CLAUDE.md", "OPENCODE.md"),
    (".claude/", ".opencode/"),
    (".claudeignore", ".opencodeignore"),
]

OPENCODE_FILENAME_MAP = {
    "CLAUDE.md": "OPENCODE.md",
}


class OpenCodeAdapter:
    """Sync adapter for OpenCode CLI."""

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
        """Sync MCP servers into opencode.json under "mcp" key.

        OpenCode format:
          local:  {"type": "local", "command": [...], "enabled": true}
          remote: {"type": "remote", "url": "...", "enabled": true}
        """
        config = self._read_config()
        old_mcps = set(config.get("mcp", {}).keys())
        new_mcps = {}

        for name, info in servers.items():
            server_type = info.get("type", "stdio")

            if server_type in ("http", "streamable_http", "sse"):
                url = info.get("url", "")
                entry = {
                    "type": "remote",
                    "url": url,
                    "enabled": True,
                }
            else:  # stdio
                command = info.get("command", "")
                args = info.get("args", [])
                cmd_list = [command] + args if command else []
                entry = {
                    "type": "local",
                    "command": cmd_list,
                    "enabled": True,
                }
                env_vars = info.get("env", {})
                if env_vars:
                    entry["environment"] = env_vars

            new_mcps[name] = entry
            print(f"  \u2705 {name}")

        # Report removals
        stale = old_mcps - set(new_mcps.keys())
        for name in sorted(stale):
            print(f"  \U0001f5d1\ufe0f  \u79fb\u9664\u904e\u6642 MCP: {name}")

        config["mcp"] = new_mcps
        self._write_config(config)
        print(f"  \U0001f4e1 \u5df2\u5beb\u5165 {OPENCODE_CONFIG}")

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def sync_skills(self, source_dir: Path, skill_names: list):
        """OpenCode has no native skill discovery system."""
        print("  \u23ed\ufe0f  OpenCode \u4e0d\u652f\u63f4 Skill \u767c\u73fe\u7cfb\u7d71")

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path, extra_files=None):
        """Write OPENCODE.md in project directory."""
        target = target_dir / "OPENCODE.md"
        self._write_opencode_md(source, target, extra_files=extra_files)

    def sync_global_instructions(self, source: Path, extra_files=None):
        """Write global instructions file and register in opencode.json."""
        OPENCODE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        target = OPENCODE_CONFIG_DIR / "instructions.md"
        self._write_opencode_md(source, target, extra_files=extra_files)

        # Also register in config's instructions array
        config = self._read_config()
        instructions = config.get("instructions", [])
        target_str = str(target)
        if target_str not in instructions:
            instructions.append(target_str)
            config["instructions"] = instructions
            self._write_config(config)
            print("  \U0001f4dd \u5df2\u8a3b\u518a\u5230 opencode.json instructions \u9663\u5217")

    def _write_opencode_md(self, source: Path, target: Path, extra_files=None):
        """Transform CLAUDE.md content for OpenCode and write."""
        content = source.read_text(encoding="utf-8")

        # Append extra files (rules, knowledge)
        if extra_files:
            content += "\n\n"
            for ef in extra_files:
                section = ef.stem.replace("-", " ").replace("_", " ").title()
                ef_content = ef.read_text(encoding="utf-8")
                content += f"\n---\n\n# {section}\n\n{ef_content}\n"

        content = self._transform_for_opencode(content)

        header = (
            "<!-- Synced from CLAUDE.md by sync-config -->\n"
            "<!-- \u624b\u52d5\u4fee\u6539\u53ef\u80fd\u5728\u4e0b\u6b21\u540c\u6b65\u6642\u88ab\u8986\u84cb -->\n\n"
        )

        target.write_text(header + content, encoding="utf-8")
        print(f"  \u2705 {source.name} \u2192 {target}")

    def _transform_for_opencode(self, content: str) -> str:
        """Apply all Claude -> OpenCode mappings to instruction content."""
        # 1. Path mappings (longer patterns first)
        for claude_path, opencode_path in OPENCODE_PATH_MAP:
            content = content.replace(claude_path, opencode_path)

        # 2. File name references (backtick-wrapped)
        for claude_name, opencode_name in OPENCODE_FILENAME_MAP.items():
            content = content.replace(f"`{claude_name}`", f"`{opencode_name}`")

        # 3. CLI command references
        content = content.replace("`claude mcp ", "`opencode mcp ")
        content = content.replace("claude mcp list", "opencode (MCP via opencode.json)")
        content = content.replace("claude mcp add", "(edit ~/.config/opencode/opencode.json)")

        return content

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------
    def sync_agents(self, agent_files: list):
        """Convert Claude agent .md files to OpenCode agent config entries."""
        import re

        config = self._read_config()
        agents = config.get("agent", {})

        for src in agent_files:
            content = src.read_text(encoding="utf-8")
            agent_name = src.stem

            # Parse YAML frontmatter
            fm = self._parse_frontmatter(content)
            if not fm:
                print(
                    f"  \u26a0\ufe0f  {agent_name}: \u7121\u6cd5\u89e3\u6790 frontmatter\uff0c\u8df3\u904e"
                )
                continue

            # Convert to OpenCode agent config
            entry = {}

            # Model mapping: Claude model names -> provider/model format
            model = fm.get("model", "")
            if model:
                entry["model"] = self._map_model(model)

            # Description
            desc = fm.get("description", "")
            if desc:
                entry["description"] = desc

            # Max turns -> maxSteps
            max_turns = fm.get("maxTurns") or fm.get("max_turns")
            if max_turns:
                entry["maxSteps"] = int(max_turns)

            # Extract prompt from body (after frontmatter)
            body_match = re.search(r"^---\s*\n.*?\n---\s*\n(.+)", content, re.DOTALL)
            if body_match:
                body = body_match.group(1).strip()
                if body:
                    entry["prompt"] = body[:2000]  # Truncate to reasonable length

            agents[agent_name] = entry
            print(f"  \u2705 {agent_name}")

        config["agent"] = agents
        self._write_config(config)

    def _parse_frontmatter(self, content: str) -> dict:
        """Parse YAML frontmatter from markdown content."""
        import re

        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return {}

        fm = {}
        for line in match.group(1).splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip("'\"")
                if value:
                    fm[key] = value
        return fm

    def _map_model(self, claude_model: str) -> str:
        """Map Claude model shorthand to OpenCode provider/model format."""
        model_map = {
            "opus": "anthropic/claude-opus-4-6",
            "sonnet": "anthropic/claude-sonnet-4-6",
            "haiku": "anthropic/claude-haiku-4-5",
        }
        return model_map.get(claude_model, f"anthropic/{claude_model}")

    # ------------------------------------------------------------------
    # Config I/O
    # ------------------------------------------------------------------
    def _read_config(self) -> dict:
        if OPENCODE_CONFIG.exists():
            try:
                return json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_config(self, data: dict):
        OPENCODE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Preserve $schema if present
        if "$schema" not in data:
            data["$schema"] = "https://opencode.ai/config.json"
        OPENCODE_CONFIG.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
