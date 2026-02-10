#!/usr/bin/env python3
"""sync_gemini.py - Gemini CLI adapter for sync-config.

Handles: MCP servers, Skills, Instructions (GEMINI.md), Custom Agents, Hooks.
Config: ~/.gemini/settings.json, ~/.gemini/skills/, ~/.gemini/agents/
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
GEMINI_SETTINGS = HOME / ".gemini" / "settings.json"
GEMINI_SKILLS   = HOME / ".gemini" / "skills"
GEMINI_AGENTS   = HOME / ".gemini" / "agents"

# Claude → Gemini hook event name mapping
HOOK_EVENT_MAP = {
    "SessionStart":      "SessionStart",
    "UserPromptSubmit":  "BeforeAgent",
    "PreToolUse":        "BeforeTool",
    "PostToolUse":       "AfterTool",
    "PreCompact":        "PreCompress",
    "Stop":              "AfterAgent",
    "SessionEnd":        "SessionEnd",
    "Notification":      "Notification",
    # Claude-only (no Gemini equivalent):
    # "SubagentStart", "SubagentStop", "PermissionRequest"
}

# Claude → Gemini tool name mapping (common ones)
TOOL_NAME_MAP = {
    "Read":         "read_file",
    "Write":        "write_file",
    "Edit":         "edit_file",
    "Bash":         "run_shell_command",
    "Glob":         "glob_search",
    "Grep":         "grep_search",
    "WebFetch":     "web_fetch",
    "WebSearch":    "web_search",
}


class GeminiAdapter:
    """Sync adapter for Gemini CLI."""

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------
    def sync_mcp(self, servers: dict):
        """Sync MCP servers to Gemini CLI."""
        for name, info in servers.items():
            if self._try_cli_mcp_add(name, info):
                continue
            self._file_mcp_add(name, info)

    def _try_cli_mcp_add(self, name, info):
        """Try using `gemini mcp add` CLI command."""
        try:
            server_type = info.get("type", "stdio")

            if server_type in ("http", "streamable_http"):
                url = info.get("url", "")
                if not url:
                    return False
                # Remove existing first (ignore errors)
                subprocess.run(["gemini", "mcp", "remove", name],
                               capture_output=True, timeout=10)
                result = subprocess.run(
                    ["gemini", "mcp", "add", name, url, "-t", "http"],
                    capture_output=True, text=True, timeout=15,
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
                subprocess.run(["gemini", "mcp", "remove", name],
                               capture_output=True, timeout=10)
                result = subprocess.run(
                    ["gemini", "mcp", "add", name, url, "-t", "sse"],
                    capture_output=True, text=True, timeout=15,
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
                subprocess.run(["gemini", "mcp", "remove", name],
                               capture_output=True, timeout=10)
                cmd = ["gemini", "mcp", "add", name, command] + args + ["-t", "stdio"]
                env_vars = info.get("env", {})
                for k, v in env_vars.items():
                    cmd.extend(["-e", f"{k}={v}"])
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
        """Copy skill directories to ~/.gemini/skills/."""
        GEMINI_SKILLS.mkdir(parents=True, exist_ok=True)

        for name in skill_names:
            src = source_dir / name
            dst = GEMINI_SKILLS / name

            if dst.exists():
                shutil.rmtree(dst)

            shutil.copytree(src, dst)
            print(f"  ✅ {name} → {dst}")

        print(f"  📁 共同步 {len(skill_names)} 個 skills")

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------
    def sync_instructions(self, source: Path, target_dir: Path):
        """Copy CLAUDE.md → GEMINI.md with header note."""
        content = source.read_text(encoding="utf-8")

        header = (
            "<!-- Synced from CLAUDE.md by sync-config -->\n"
            "<!-- 手動修改可能在下次同步時被覆蓋 -->\n\n"
        )

        target = target_dir / "GEMINI.md"
        target.write_text(header + content, encoding="utf-8")
        print(f"  ✅ {source.name} → {target}")

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
        content = content.replace("permission-mode: plan", "# permission-mode: plan (not supported)")
        content = content.replace("disallowed-tools:", "# disallowed-tools (use excludeTools in extension):")

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
                        gh["timeout"] = h["timeout"]
                    converted_hooks.append(gh)

                if converted_hooks:
                    converted_entries.append({
                        "matcher": entry.get("matcher", "*"),
                        "hooks": converted_hooks,
                    })

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
