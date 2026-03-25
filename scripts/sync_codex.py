#!/usr/bin/env python3
"""sync_codex.py - Codex CLI adapter for sync-config.

Handles: MCP servers, Skills, Instructions (AGENTS.md).
Does NOT support: Custom Agents (user-level), Full Hooks (only notify).
Config: ~/.codex/config.toml
Skills: $HOME/.agents/skills/ (Codex standard discovery path)
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
CODEX_CONFIG = HOME / ".codex" / "config.toml"
# Codex CLI standard skill discovery: $HOME/.agents/skills/
# See: https://developers.openai.com/codex/skills
CODEX_SKILLS = HOME / ".agents" / "skills"

# Claude → Codex path mapping (order: longer/more specific first)
CODEX_PATH_MAP = [
    ("~/.claude/skills/", "~/.agents/skills/"),
    ("~/.claude/CLAUDE.md", "~/.codex/AGENTS.md"),
    ("~/.claude/mcp.json", "~/.codex/config.toml"),
    ("~/.claude/settings.json", "~/.codex/config.toml"),
    ("~/.claude/data/", "~/.codex/data/"),
    ("~/.claude/", "~/.codex/"),
    (".claude/skills/", ".agents/skills/"),
    (".claude/", ".codex/"),
    (".claudeignore", ".codexignore"),
]

# Standalone file name replacements (backtick-wrapped)
CODEX_FILENAME_MAP = {
    "CLAUDE.md": "AGENTS.md",
}


def _get_skill_md_hash(skill_dir: Path) -> str:
    """Get git commit hash for SKILL.md in the skill directory."""
    try:
        result = subprocess.run(
            ["git", "-C", str(skill_dir), "log", "-1", "--format=%H", "--", "SKILL.md"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    # Fallback: use mtime as pseudo-hash
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        return f"mtime-{skill_md.stat().st_mtime}"
    return ""


DESCRIPTION_BACKUP = HOME / ".claude" / "data" / "skill-index" / "description-backup.json"


def _get_full_skill_md(skill_dir: Path) -> str:
    """Get full SKILL.md with description restored if cold-stripped.

    Priority: git HEAD → working copy, then patch description from backup if empty.
    """
    content = ""
    try:
        result = subprocess.run(
            ["git", "-C", str(skill_dir), "show", "HEAD:SKILL.md"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            content = result.stdout
    except (subprocess.TimeoutExpired, OSError):
        pass

    if not content:
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text(encoding="utf-8")

    if not content:
        return ""

    # Check if description is empty (cold-stripped) and restore from backup
    content = _restore_description_if_empty(skill_dir.name, content)
    return content


def _restore_description_if_empty(skill_name: str, content: str) -> str:
    """If SKILL.md has description: "", restore it from backup."""
    import re as _re

    if not _re.search(r'^description:\s*""', content, _re.MULTILINE):
        # description is present and non-empty — no-op
        # Also match multi-line description (description: >- ...)
        if _re.search(r"^description:\s*\S", content, _re.MULTILINE):
            return content

    # Try to load backup
    if not DESCRIPTION_BACKUP.exists():
        return content

    try:
        backup = json.loads(DESCRIPTION_BACKUP.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return content

    desc = backup.get(skill_name, "")
    if not desc:
        return content

    # Replace empty description with backup value
    # Escape for YAML multi-line block scalar
    escaped = desc.replace('"', '\\"')
    if "\n" in desc or len(desc) > 120:
        # Use YAML block scalar >-
        indent = "  "
        lines = desc.split("\n")
        block = f"description: >-\n{indent}" + f"\n{indent}".join(lines)
        content = _re.sub(r'^description:\s*""', block, content, count=1, flags=_re.MULTILINE)
    else:
        content = _re.sub(
            r'^description:\s*""',
            f'description: "{escaped}"',
            content,
            count=1,
            flags=_re.MULTILINE,
        )

    return content


class CodexAdapter:
    """Sync adapter for Codex CLI."""

    skills_dir = str(CODEX_SKILLS)

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
        """Sync MCP servers to Codex CLI (add/update + remove stale)."""
        # Add or update servers from Claude Code
        for name, info in servers.items():
            if self._try_cli_mcp_add(name, info):
                continue
            self._file_mcp_add(name, info)

        # Remove stale MCPs that no longer exist in Claude Code
        if CODEX_CONFIG.exists():
            content = CODEX_CONFIG.read_text(encoding="utf-8")
            existing = set(re.findall(r"\[mcp_servers\.([^\]\.]+)\]", content))
            stale = existing - set(servers.keys())
            if stale:
                for name in stale:
                    # Remove the [mcp_servers.name] block and its [mcp_servers.name.env] sub-block
                    for suffix in [f".{name}.env", f".{name}"]:
                        pattern = rf"\n?\[mcp_servers{re.escape(suffix)}\]\n(?:(?!\[)[^\n]*\n)*"
                        content = re.sub(pattern, "\n", content)
                    print(f"  🗑️  移除過時 MCP: {name}")
                content = re.sub(r"\n{3,}", "\n\n", content)
                CODEX_CONFIG.write_text(content, encoding="utf-8")

    def _try_cli_mcp_add(self, name, info):
        """Try using `codex mcp add` CLI command."""
        try:
            server_type = info.get("type", "stdio")

            if server_type in ("http", "streamable_http", "sse"):
                url = info.get("url", "")
                if not url:
                    return False
                # Remove existing first
                subprocess.run(["codex", "mcp", "remove", name], capture_output=True, timeout=10)
                result = subprocess.run(
                    ["codex", "mcp", "add", name, "--url", url],
                    capture_output=True,
                    text=True,
                    timeout=15,
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
                subprocess.run(["codex", "mcp", "remove", name], capture_output=True, timeout=10)
                cmd = ["codex", "mcp", "add", name, "--", command] + args
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
        """Fallback: directly edit ~/.codex/config.toml."""
        content = ""
        if CODEX_CONFIG.exists():
            content = CODEX_CONFIG.read_text(encoding="utf-8")

        # Remove existing section + its .env sub-section
        for suffix in [f"[mcp_servers.{name}.env]", f"[mcp_servers.{name}]"]:
            if suffix in content:
                pattern = re.escape(suffix) + r"\n(?:(?!\[)[^\n]*\n)*"
                content = re.sub(pattern, "", content)

        # Build new TOML section
        server_type = info.get("type", "stdio")
        lines = [f"\n[mcp_servers.{name}]"]

        if server_type in ("http", "streamable_http"):
            lines.append('transport = "streamable_http"')
            lines.append(f'url = "{info.get("url", "")}"')
        elif server_type == "sse":
            lines.append('transport = "sse"')
            lines.append(f'url = "{info.get("url", "")}"')
        else:  # stdio
            command = info.get("command", "")
            args = info.get("args", [])
            lines.append(f'command = "{command}"')
            if args:
                args_str = ", ".join(f'"{a}"' for a in args)
                lines.append(f"args = [{args_str}]")

        # Write env vars as [mcp_servers.name.env] sub-section
        env_vars = info.get("env", {})
        if env_vars:
            lines.append(f"\n[mcp_servers.{name}.env]")
            for k, v in env_vars.items():
                lines.append(f'{k} = "{v}"')

        content = content.rstrip() + "\n" + "\n".join(lines) + "\n"

        CODEX_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CODEX_CONFIG.write_text(content, encoding="utf-8")
        print(f"  ✅ {name} (寫入 config.toml)")

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def sync_skills(self, source_dir: Path, skill_names: list):
        """Hybrid sync: copy SKILL.md (full version), symlink subdirs."""
        CODEX_SKILLS.mkdir(parents=True, exist_ok=True)
        synced = 0
        unchanged = 0

        for name in skill_names:
            src = source_dir / name
            dst = CODEX_SKILLS / name

            # Freshness check: compare git commit hash
            current_hash = _get_skill_md_hash(src)
            meta_file = dst / ".sync-meta"
            if meta_file.exists() and not dst.is_symlink():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    if meta.get("hash") == current_hash and current_hash:
                        unchanged += 1
                        continue
                except (json.JSONDecodeError, OSError):
                    pass

            # Remove old structure (whole-dir symlink or stale copy)
            if dst.is_symlink():
                dst.unlink()
            elif dst.exists():
                shutil.rmtree(dst)

            dst.mkdir(parents=True, exist_ok=True)

            # SKILL.md — get full version (bypass cold stripping)
            skill_md_content = _get_full_skill_md(src)
            (dst / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

            # Remaining items — symlink
            for item in src.iterdir():
                if item.name == "SKILL.md":
                    continue
                link = dst / item.name
                if not link.exists():
                    link.symlink_to(item)

            # Write sync metadata
            meta_file.write_text(json.dumps({"hash": current_hash}), encoding="utf-8")

            print(f"  📦 {name}")
            synced += 1

        if unchanged:
            print(f"  ⏭️  {unchanged} 個 skill 已是最新")
        print(f"  📦 共同步 {synced} 個 skills（共 {len(skill_names)} 個）")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def sync_commands(self, command_files: list):
        """Symlink command .md files to ~/.codex/commands/."""
        codex_cmds = HOME / ".codex" / "commands"
        codex_cmds.mkdir(parents=True, exist_ok=True)
        synced = 0

        for src in command_files:
            rel = src.relative_to(HOME / ".claude" / "commands")
            dst = codex_cmds / rel
            dst.parent.mkdir(parents=True, exist_ok=True)

            if dst.is_symlink() and dst.resolve() == src.resolve():
                continue
            if dst.is_symlink():
                dst.unlink()
            elif dst.exists():
                dst.unlink()

            dst.symlink_to(src)
            print(f"  🔗 {rel}")
            synced += 1

        print(f"  🔗 共建立 {synced} 個 command symlinks")

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path, extra_files=None):
        """Copy CLAUDE.md + extra files → AGENTS.md with header note (project-level)."""
        self._write_agents_md(source, target_dir / "AGENTS.md", extra_files=extra_files)

    def sync_global_instructions(self, source: Path, extra_files=None):
        """Copy ~/.claude/CLAUDE.md + rules → ~/.codex/AGENTS.md."""
        target = HOME / ".codex" / "AGENTS.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_agents_md(source, target, extra_files=extra_files)

    def _write_agents_md(self, source: Path, target: Path, extra_files=None):
        """Transform CLAUDE.md content for Codex CLI and write as AGENTS.md."""
        content = source.read_text(encoding="utf-8")

        # Append extra files (rules, knowledge)
        if extra_files:
            content += "\n\n"
            for ef in extra_files:
                section = ef.stem.replace("-", " ").replace("_", " ").title()
                ef_content = ef.read_text(encoding="utf-8")
                content += f"\n---\n\n# {section}\n\n{ef_content}\n"

        content = self._transform_for_codex(content)

        header = (
            "<!-- Synced from CLAUDE.md by sync-config -->\n"
            "<!-- 手動修改可能在下次同步時被覆蓋 -->\n\n"
        )

        target.write_text(header + content, encoding="utf-8")
        print(f"  ✅ {source.name} → {target}")

    def _transform_for_codex(self, content: str) -> str:
        """Apply all Claude → Codex mappings to instruction content."""
        # 1. Path mappings (longer patterns first to avoid partial matches)
        for claude_path, codex_path in CODEX_PATH_MAP:
            content = content.replace(claude_path, codex_path)

        # 2. File name references: `CLAUDE.md` → `AGENTS.md` (backtick-wrapped)
        for claude_name, codex_name in CODEX_FILENAME_MAP.items():
            content = content.replace(f"`{claude_name}`", f"`{codex_name}`")

        # 3. CLI command references
        content = content.replace("`claude mcp ", "`codex mcp ")
        content = content.replace("claude mcp list", "codex mcp list")
        content = content.replace("claude mcp add", "codex mcp add")
        content = content.replace("claude mcp get", "codex mcp get")

        # Note: Codex tool names differ significantly from Claude Code
        # and are not user-configurable in skill frontmatter, so we skip
        # tool name mapping. Hook events are also not mapped (Codex only
        # supports `notify` with `agent-turn-complete`).

        return content
