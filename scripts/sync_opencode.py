#!/usr/bin/env python3
"""sync_opencode.py - OpenCode CLI adapter for sync-config.

Handles: MCP servers, Skills, Instructions (AGENTS.md), Agents (config-based).
Does NOT support: Hooks (use OpenCode plugins instead), Custom Commands.
Config: ~/.config/opencode/opencode.json
Skills: ~/.config/opencode/skills/<name>/SKILL.md (added in OpenCode v1.14+)

Notes (verified against OpenCode v1.14.41, 2026-05):
  - MCP env-var key is `environment` (not `env`)
  - Instructions: AGENTS.md takes precedence over the legacy OPENCODE.md
  - Skills are discovered from ~/.config/opencode/skills/ + project .opencode/skills/
"""

import json
import shutil
from pathlib import Path

HOME = Path.home()
OPENCODE_CONFIG_DIR = HOME / ".config" / "opencode"
OPENCODE_CONFIG = OPENCODE_CONFIG_DIR / "opencode.json"
OPENCODE_SKILLS = OPENCODE_CONFIG_DIR / "skills"

# Claude -> OpenCode path mapping (longer/more specific first)
OPENCODE_PATH_MAP = [
    ("~/.claude/skills/", "~/.config/opencode/skills/"),
    ("~/.claude/CLAUDE.md", "~/.config/opencode/AGENTS.md"),
    ("~/.claude/mcp.json", "~/.config/opencode/opencode.json"),
    ("~/.claude/settings.json", "~/.config/opencode/opencode.json"),
    ("~/.claude/data/", "~/.local/share/opencode/"),
    ("~/.claude/agents/", "~/.config/opencode/ (agent key)"),
    ("~/.claude/", "~/.config/opencode/"),
    (".claude/CLAUDE.md", "AGENTS.md"),
    (".claude/skills/", ".opencode/skills/"),
    (".claude/", ".opencode/"),
    (".claudeignore", ".opencodeignore"),
]

OPENCODE_FILENAME_MAP = {
    "CLAUDE.md": "AGENTS.md",
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
        """Sync skills to ~/.config/opencode/skills/<name>/SKILL.md.

        OpenCode v1.14+ discovers skills from this dir plus project-level
        .opencode/skills/. We only write the global location.
        """
        OPENCODE_SKILLS.mkdir(parents=True, exist_ok=True)
        synced = 0

        for name in skill_names:
            src = source_dir / name
            dst = OPENCODE_SKILLS / name

            if dst.is_symlink() or dst.exists():
                if dst.is_symlink() or not dst.is_dir():
                    dst.unlink()
                else:
                    shutil.rmtree(dst)

            shutil.copytree(src, dst)
            synced += 1

        print(
            f"  \U0001f4c1 \u5171\u540c\u6b65 {synced} \u500b skills \u2192 ~/.config/opencode/skills/"
        )

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path, extra_files=None):
        """Write project-level AGENTS.md (OpenCode v1.14+ format).

        Legacy OPENCODE.md is removed if present to avoid stale duplicates.
        """
        target = target_dir / "AGENTS.md"
        self._write_opencode_md(source, target, extra_files=extra_files)

        legacy = target_dir / "OPENCODE.md"
        if legacy.exists():
            legacy.unlink()
            print("  [legacy] \u5df2\u79fb\u9664\u820a\u7248 OPENCODE.md")

    def sync_global_instructions(self, source: Path, extra_files=None):
        """Write global ~/.config/opencode/AGENTS.md (preferred over instructions.md)."""
        OPENCODE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        target = OPENCODE_CONFIG_DIR / "AGENTS.md"
        self._write_opencode_md(source, target, extra_files=extra_files)

        # Clean up legacy global instructions file + its registration
        legacy = OPENCODE_CONFIG_DIR / "instructions.md"
        config = self._read_config()
        instructions = config.get("instructions", []) or []
        legacy_str = str(legacy)
        if legacy.exists() or legacy_str in instructions:
            if legacy.exists():
                legacy.unlink()
            if legacy_str in instructions:
                instructions.remove(legacy_str)
                config["instructions"] = instructions
                self._write_config(config)
            print(
                "  [legacy] \u5df2\u6e05\u9664\u820a\u7248 instructions.md \u8207\u8a3b\u518a"
            )

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
        content = content.replace(
            "claude mcp add", "(edit ~/.config/opencode/opencode.json)"
        )

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
