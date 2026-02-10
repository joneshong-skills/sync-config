#!/usr/bin/env python3
"""sync_codex.py - Codex CLI adapter for sync-config.

Handles: MCP servers, Skills, Instructions (AGENTS.md).
Does NOT support: Custom Agents (user-level), Hooks, Plugins.
Config: ~/.codex/config.toml, ~/.codex/skills/
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
CODEX_CONFIG  = HOME / ".codex" / "config.toml"
CODEX_SKILLS  = HOME / ".codex" / "skills"


class CodexAdapter:
    """Sync adapter for Codex CLI."""

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
        """Sync MCP servers to Codex CLI."""
        for name, info in servers.items():
            if self._try_cli_mcp_add(name, info):
                continue
            self._file_mcp_add(name, info)

    def _try_cli_mcp_add(self, name, info):
        """Try using `codex mcp add` CLI command."""
        try:
            server_type = info.get("type", "stdio")

            if server_type in ("http", "streamable_http", "sse"):
                url = info.get("url", "")
                if not url:
                    return False
                # Remove existing first
                subprocess.run(["codex", "mcp", "remove", name],
                               capture_output=True, timeout=10)
                result = subprocess.run(
                    ["codex", "mcp", "add", name, "--url", url],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    print(f"  ✅ {name} (URL: {url})")
                    return True
                return False

            else:  # stdio
                command = info.get("command", "")
                args = info.get("args", [])
                if not command:
                    return False
                subprocess.run(["codex", "mcp", "remove", name],
                               capture_output=True, timeout=10)
                cmd = ["codex", "mcp", "add", name, "--", command] + args
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    print(f"  ✅ {name} (stdio: {command})")
                    return True
                return False

        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _file_mcp_add(self, name, info):
        """Fallback: directly edit ~/.codex/config.toml."""
        content = ""
        if CODEX_CONFIG.exists():
            content = CODEX_CONFIG.read_text(encoding="utf-8")

        # Check if section already exists
        section_header = f"[mcp_servers.{name}]"
        if section_header in content:
            # Remove existing section (up to next [...] or end)
            pattern = re.escape(section_header) + r"\n(?:(?!\[)[^\n]*\n)*"
            content = re.sub(pattern, "", content)

        # Build new TOML section
        server_type = info.get("type", "stdio")
        lines = [f"\n{section_header}"]

        if server_type in ("http", "streamable_http"):
            lines.append(f'transport = "streamable_http"')
            lines.append(f'url = "{info.get("url", "")}"')
        elif server_type == "sse":
            lines.append(f'transport = "sse"')
            lines.append(f'url = "{info.get("url", "")}"')
        else:  # stdio
            command = info.get("command", "")
            args = info.get("args", [])
            lines.append(f'command = "{command}"')
            if args:
                args_str = ", ".join(f'"{a}"' for a in args)
                lines.append(f"args = [{args_str}]")

        content = content.rstrip() + "\n" + "\n".join(lines) + "\n"

        CODEX_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CODEX_CONFIG.write_text(content, encoding="utf-8")
        print(f"  ✅ {name} (寫入 config.toml)")

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def sync_skills(self, source_dir: Path, skill_names: list):
        """Copy skill directories to ~/.codex/skills/."""
        CODEX_SKILLS.mkdir(parents=True, exist_ok=True)

        for name in skill_names:
            src = source_dir / name
            dst = CODEX_SKILLS / name

            if dst.exists():
                shutil.rmtree(dst)

            shutil.copytree(src, dst)
            print(f"  ✅ {name} → {dst}")

        print(f"  📁 共同步 {len(skill_names)} 個 skills")

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path):
        """Copy CLAUDE.md → AGENTS.md with header note."""
        content = source.read_text(encoding="utf-8")

        header = (
            "<!-- Synced from CLAUDE.md by sync-config -->\n"
            "<!-- 手動修改可能在下次同步時被覆蓋 -->\n\n"
        )

        target = target_dir / "AGENTS.md"
        target.write_text(header + content, encoding="utf-8")
        print(f"  ✅ {source.name} → {target}")
