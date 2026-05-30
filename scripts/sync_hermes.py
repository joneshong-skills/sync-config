#!/usr/bin/env python3
"""sync_hermes.py - Hermes Agent adapter for sync-config.

Hermes Agent (~/.hermes/) is JonesHong's own Python agent. It uses YAML
configuration (~/.hermes/config.yaml) and a different mental model from
the Anthropic / Google / OpenAI CLIs:

  - Skills are categorized: ~/.hermes/skills/<category>/<name>/SKILL.md
  - Skills.external_dirs accepts read-only external paths (perfect for
    sharing ~/.agents/skills without copying)
  - MCP servers are at top-level `mcp_servers:` (snake_case, like Codex)
  - No file-based "custom agents" — hermes uses personalities + toolsets
  - Instructions: hermes reads its own AGENTS.md (development guide for
    its own codebase), NOT a user-level instruction file

Handles: MCP servers, Skills (via external_dirs registration only).
Does NOT support: Custom agents (no equivalent), Hooks, Commands,
                  user-level instructions (no equivalent concept).

This adapter is non-destructive: it preserves all other config.yaml fields.
"""

from pathlib import Path

import yaml

HOME = Path.home()
HERMES_CONFIG = HOME / ".hermes" / "config.yaml"
AGENTS_SKILLS = HOME / ".agents" / "skills"


class HermesAdapter:
    """Sync adapter for Hermes Agent."""

    # Skills are referenced via external_dirs — no copy target needed.
    skills_dir = None

    # ------------------------------------------------------------------
    # MCP — write ~/.hermes/config.yaml `mcp_servers:` (snake_case)
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
        config = self._read_config()
        old_mcps = set((config.get("mcp_servers") or {}).keys())
        new_mcps = {}

        for name, info in servers.items():
            server_type = info.get("type", "stdio")
            entry = {}

            if server_type in ("http", "streamable_http", "sse"):
                url = info.get("url", "")
                if url:
                    entry["url"] = url
            else:  # stdio
                command = info.get("command", "")
                args = info.get("args", [])
                if command:
                    entry["command"] = command
                    if args:
                        entry["args"] = list(args)

            env_vars = info.get("env", {})
            if env_vars:
                entry["env"] = dict(env_vars)

            if entry:
                new_mcps[name] = entry
                print(f"  ✅ {name}")

        stale = old_mcps - set(new_mcps.keys())
        for name in sorted(stale):
            print(f"  🗑️  移除過時 MCP: {name}")

        config["mcp_servers"] = new_mcps
        self._write_config(config)

    # ------------------------------------------------------------------
    # Skills — register ~/.agents/skills as a Hermes external dir
    #
    # Hermes reads skills from:
    #   ~/.hermes/skills/                       (primary, mutable)
    #   skills.external_dirs[*]                 (read-only, expanded)
    #
    # We don't copy skills here. We just ensure ~/.agents/skills is in
    # external_dirs so the same skill set Codex/Gemini use is visible
    # to Hermes too.
    # ------------------------------------------------------------------
    def sync_skills(self, source_dir: Path, skill_names: list):
        config = self._read_config()
        skills_cfg = config.setdefault("skills", {})
        external = list(skills_cfg.get("external_dirs") or [])

        target = "~/.agents/skills"
        # Normalize comparison — accept both ~ and absolute forms
        normalized = {str(Path(p).expanduser().resolve()) for p in external if p}
        target_abs = str(AGENTS_SKILLS.resolve())

        if target_abs in normalized:
            print(
                f"  ⏭️  ~/.agents/skills 已在 external_dirs（{len(skill_names)} 個 skills 可見）"
            )
        else:
            external.append(target)
            skills_cfg["external_dirs"] = external
            config["skills"] = skills_cfg
            self._write_config(config)
            print(
                f"  ✅ 已註冊 ~/.agents/skills → external_dirs（{len(skill_names)} 個 skills 可見）"
            )

    # ------------------------------------------------------------------
    # Config I/O — preserve unknown keys, write valid YAML
    # ------------------------------------------------------------------
    def _read_config(self):
        if HERMES_CONFIG.exists():
            try:
                with HERMES_CONFIG.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    return data if isinstance(data, dict) else {}
            except (yaml.YAMLError, OSError):
                pass
        return {}

    def _write_config(self, data):
        HERMES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        # Backup before write — Hermes config has user customizations
        if HERMES_CONFIG.exists():
            backup = HERMES_CONFIG.with_suffix(".yaml.bak-sync")
            backup.write_bytes(HERMES_CONFIG.read_bytes())
        HERMES_CONFIG.write_text(
            yaml.safe_dump(
                data, sort_keys=False, allow_unicode=True, default_flow_style=False
            ),
            encoding="utf-8",
        )
