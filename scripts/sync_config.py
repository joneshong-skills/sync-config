#!/usr/bin/env python3
"""sync_config.py - Sync Claude Code configuration to Gemini CLI and Codex CLI.

Usage:
    python3 sync_config.py sync mcp    [--target gemini|codex|all]
    python3 sync_config.py sync skills [--target ...] [--include a,b] [--exclude a,b]
    python3 sync_config.py sync instructions [--target ...] [--cwd /path]
    python3 sync_config.py sync agents [--target gemini]
    python3 sync_config.py sync hooks  [--target gemini]
    python3 sync_config.py sync all    [--target gemini|codex|all]
    python3 sync_config.py status
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOME = Path.home()
CLAUDE_SKILLS_DIR = HOME / ".claude" / "skills"
CLAUDE_AGENTS_DIR = HOME / ".claude" / "agents"
CLAUDE_SETTINGS   = HOME / ".claude" / "settings.json"
CLAUDE_MCP_USER   = HOME / ".claude" / "mcp.json"
CLAUDE_MCP_PROJECT = Path(".claude") / "mcp.json"

# Skip list: skills that are CLI-specific or self-referential
SKIP_SKILLS_PATTERNS = [
    "sync-config",       # this skill itself
    "claude-code-*",     # claude-specific
    "gemini-cli-*",      # gemini-specific
    "codex-*",           # codex-specific
]

# ---------------------------------------------------------------------------
# Claude Config Readers
# ---------------------------------------------------------------------------

def read_claude_mcp_from_files():
    """Try to read MCP servers from known config files."""
    for path in [CLAUDE_MCP_USER, CLAUDE_MCP_PROJECT]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                servers = data.get("mcpServers", {})
                if servers:
                    return servers
            except (json.JSONDecodeError, OSError):
                continue
    return {}


def read_claude_mcp_from_cli():
    """Parse `claude mcp list` + `claude mcp get <name>` output."""
    servers = {}
    try:
        result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {}

        # Parse server names from list output
        # Format: "name: url_or_cmd (TYPE) - status"
        for line in result.stdout.splitlines():
            line = line.strip()
            m = re.match(r"^(\S+):\s+(.+?)\s+\((\w+)\)\s+-\s+", line)
            if not m:
                continue
            name = m.group(1)
            servers[name] = _get_server_detail(name)

    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return servers


def _get_server_detail(name):
    """Parse `claude mcp get <name>` output into a dict."""
    info = {"name": name}
    try:
        result = subprocess.run(
            ["claude", "mcp", "get", name],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Type:"):
                info["type"] = line.split(":", 1)[1].strip().lower()
            elif line.startswith("URL:"):
                info["url"] = line.split(":", 1)[1].strip()
                # URL may contain ":" so rejoin
                if "://" not in info["url"]:
                    info["url"] = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else ""
            elif line.startswith("Command:"):
                cmd_str = line.split(":", 1)[1].strip()
                parts = cmd_str.split()
                if parts:
                    info["command"] = parts[0]
                    info["args"] = parts[1:] if len(parts) > 1 else []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Fix URL parsing (rejoin full URL from get output)
    if "url" in info and not info["url"].startswith("http"):
        # Try to extract URL from raw output
        raw = subprocess.run(
            ["claude", "mcp", "get", name],
            capture_output=True, text=True, timeout=10,
        ).stdout
        url_match = re.search(r"(https?://\S+)", raw)
        if url_match:
            info["url"] = url_match.group(1)

    return info


def read_claude_mcp():
    """Read MCP server configs from Claude Code (file or CLI)."""
    servers = read_claude_mcp_from_files()
    if servers:
        return servers
    return read_claude_mcp_from_cli()


def read_claude_skills():
    """List skill directories under ~/.claude/skills/."""
    if not CLAUDE_SKILLS_DIR.is_dir():
        return []
    skills = []
    for d in sorted(CLAUDE_SKILLS_DIR.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            skills.append(d.name)
    return skills


def read_claude_agents():
    """List agent .md files under ~/.claude/agents/."""
    agents = []
    for agents_dir in [CLAUDE_AGENTS_DIR, Path(".claude") / "agents"]:
        if agents_dir.is_dir():
            for f in sorted(agents_dir.glob("*.md")):
                agents.append(f)
    return agents


def read_claude_hooks():
    """Read hooks config from ~/.claude/settings.json."""
    if not CLAUDE_SETTINGS.exists():
        return {}
    try:
        data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
        return data.get("hooks", {})
    except (json.JSONDecodeError, OSError):
        return {}


def read_claude_instructions(cwd=None):
    """Find CLAUDE.md in given directory or current directory."""
    search_dir = Path(cwd) if cwd else Path.cwd()
    for candidate in [search_dir / "CLAUDE.md", search_dir / ".claude" / "CLAUDE.md"]:
        if candidate.exists():
            return candidate
    # Also check global
    global_claude_md = HOME / ".claude" / "CLAUDE.md"
    if global_claude_md.exists():
        return global_claude_md
    return None


# ---------------------------------------------------------------------------
# Skill filtering
# ---------------------------------------------------------------------------

def should_skip_skill(name, target):
    """Check if a skill should be skipped for the given target."""
    import fnmatch
    for pattern in SKIP_SKILLS_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    # Don't sync target-specific headless skills TO the same target
    if target == "gemini" and "gemini" in name.lower():
        return True
    if target == "codex" and "codex" in name.lower():
        return True
    return False


def filter_skills(all_skills, target, include=None, exclude=None):
    """Filter skills based on include/exclude lists and target."""
    result = []
    for name in all_skills:
        if include and name not in include:
            continue
        if exclude and name in exclude:
            continue
        if should_skip_skill(name, target):
            continue
        result.append(name)
    return result


# ---------------------------------------------------------------------------
# Adapter loading
# ---------------------------------------------------------------------------

def get_adapters(target):
    """Return list of (name, adapter) tuples based on target."""
    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))

    adapters = []
    if target in ("gemini", "all"):
        from sync_gemini import GeminiAdapter
        adapters.append(("gemini", GeminiAdapter()))
    if target in ("codex", "all"):
        from sync_codex import CodexAdapter
        adapters.append(("codex", CodexAdapter()))
    return adapters


# ---------------------------------------------------------------------------
# Sync commands
# ---------------------------------------------------------------------------

def cmd_sync_mcp(args):
    servers = read_claude_mcp()
    if not servers:
        print("⚠️  未找到 Claude Code MCP 設定")
        return

    print(f"📡 找到 {len(servers)} 個 MCP server：{', '.join(servers.keys())}")
    for name, adapter in get_adapters(args.target):
        print(f"\n🔄 同步 MCP → {name.capitalize()}")
        adapter.sync_mcp(servers)


def cmd_sync_skills(args):
    all_skills = read_claude_skills()
    if not all_skills:
        print("⚠️  未找到 Claude Code Skills")
        return

    include = args.include.split(",") if args.include else None
    exclude = args.exclude.split(",") if args.exclude else None

    for name, adapter in get_adapters(args.target):
        filtered = filter_skills(all_skills, name, include, exclude)
        if not filtered:
            print(f"⚠️  沒有適合同步到 {name} 的 skills")
            continue
        print(f"\n🔄 同步 {len(filtered)} 個 Skills → {name.capitalize()}: {', '.join(filtered)}")
        adapter.sync_skills(CLAUDE_SKILLS_DIR, filtered)


def cmd_sync_instructions(args):
    source = read_claude_instructions(args.cwd)
    if not source:
        print("⚠️  未找到 CLAUDE.md")
        return

    target_dir = Path(args.cwd) if args.cwd else Path.cwd()
    print(f"📄 來源: {source}")
    for name, adapter in get_adapters(args.target):
        print(f"\n🔄 同步指令 → {name.capitalize()}")
        adapter.sync_instructions(source, target_dir)


def cmd_sync_agents(args):
    agents = read_claude_agents()
    if not agents:
        print("⚠️  未找到 Custom Agents")
        return

    print(f"🤖 找到 {len(agents)} 個 agents: {', '.join(a.stem for a in agents)}")

    for name, adapter in get_adapters(args.target):
        if not hasattr(adapter, "sync_agents"):
            print(f"  ⏭️  {name} 不支援 Custom Agents 同步")
            continue
        print(f"\n🔄 同步 Agents → {name.capitalize()}")
        adapter.sync_agents(agents)


def cmd_sync_hooks(args):
    hooks = read_claude_hooks()
    if not hooks:
        print("⚠️  未找到 Hooks 設定")
        return

    print(f"🪝 找到 {len(hooks)} 個 hook 事件: {', '.join(hooks.keys())}")

    for name, adapter in get_adapters(args.target):
        if not hasattr(adapter, "sync_hooks"):
            print(f"  ⏭️  {name} 不支援 Hooks 同步")
            continue
        print(f"\n🔄 同步 Hooks → {name.capitalize()}")
        adapter.sync_hooks(hooks)


def cmd_sync_all(args):
    print("=" * 50)
    print("🔄 全面同步 Claude Code → 其他 CLI")
    print("=" * 50)

    print("\n── MCP Servers ──")
    cmd_sync_mcp(args)

    print("\n── Skills ──")
    cmd_sync_skills(args)

    print("\n── 專案指令 ──")
    cmd_sync_instructions(args)

    print("\n── Custom Agents ──")
    cmd_sync_agents(args)

    print("\n── Hooks ──")
    cmd_sync_hooks(args)

    print("\n" + "=" * 50)
    print("✅ 同步完成")


def cmd_status(_args):
    """Show current config status across all CLIs."""
    print("=" * 60)
    print("📊 跨 CLI 設定狀態")
    print("=" * 60)

    # MCP
    print("\n── MCP Servers ──")
    claude_mcp = read_claude_mcp()
    print(f"  Claude Code: {len(claude_mcp)} 個 ({', '.join(claude_mcp.keys()) if claude_mcp else '無'})")

    for cli, cmd in [("Gemini CLI", ["gemini", "mcp", "list"]), ("Codex CLI", ["codex", "mcp", "list"])]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            # Count non-empty non-header lines
            count = sum(1 for line in r.stdout.splitlines()
                        if line.strip() and not line.startswith("Checking")
                        and not line.startswith("Loaded")
                        and not line.startswith("Name")
                        and not line.startswith("Configured")
                        and "---" not in line)
            print(f"  {cli}: {count} 個")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(f"  {cli}: ❌ CLI 未安裝")

    # Skills
    print("\n── Skills ──")
    claude_skills = read_claude_skills()
    print(f"  Claude Code: {len(claude_skills)} 個 ({', '.join(claude_skills)})")

    for cli_name, skills_dir in [
        ("Gemini CLI", HOME / ".gemini" / "skills"),
        ("Codex CLI", HOME / ".codex" / "skills"),
    ]:
        if skills_dir.is_dir():
            skills = [d.name for d in sorted(skills_dir.iterdir()) if d.is_dir() and (d / "SKILL.md").exists()]
            print(f"  {cli_name}: {len(skills)} 個 ({', '.join(skills) if skills else '無'})")
        else:
            print(f"  {cli_name}: 0 個 (目錄不存在)")

    # Instructions
    print("\n── 專案指令 ──")
    cwd = Path.cwd()
    for fname, cli_name in [("CLAUDE.md", "Claude Code"), ("GEMINI.md", "Gemini CLI"), ("AGENTS.md", "Codex CLI")]:
        fpath = cwd / fname
        if fpath.exists():
            size = fpath.stat().st_size
            print(f"  {cli_name}: ✅ {fname} ({size} bytes)")
        else:
            print(f"  {cli_name}: ❌ {fname} 不存在")

    # Agents
    print("\n── Custom Agents ──")
    agents = read_claude_agents()
    print(f"  Claude Code: {len(agents)} 個")
    gemini_agents_dir = HOME / ".gemini" / "agents"
    if gemini_agents_dir.is_dir():
        ga = list(gemini_agents_dir.glob("*.md"))
        print(f"  Gemini CLI: {len(ga)} 個")
    else:
        print(f"  Gemini CLI: 0 個")
    print(f"  Codex CLI: ⏭️ 不支援使用者自訂 agents")

    # Hooks
    print("\n── Hooks ──")
    hooks = read_claude_hooks()
    print(f"  Claude Code: {len(hooks)} 個事件 ({', '.join(hooks.keys()) if hooks else '無'})")
    gemini_settings = HOME / ".gemini" / "settings.json"
    if gemini_settings.exists():
        try:
            gs = json.loads(gemini_settings.read_text(encoding="utf-8"))
            gh = gs.get("hooks", {})
            print(f"  Gemini CLI: {len(gh)} 個事件 ({', '.join(gh.keys()) if gh else '無'})")
        except (json.JSONDecodeError, OSError):
            print(f"  Gemini CLI: ❓ 無法讀取")
    else:
        print(f"  Gemini CLI: 0 個事件")
    print(f"  Codex CLI: ⏭️ 不支援 hooks")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sync Claude Code configuration to Gemini CLI and Codex CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # sync
    sync_parser = sub.add_parser("sync", help="同步設定")
    sync_sub = sync_parser.add_subparsers(dest="what")

    for name in ["mcp", "skills", "instructions", "agents", "hooks", "all"]:
        p = sync_sub.add_parser(name)
        p.add_argument("--target", default="all", choices=["gemini", "codex", "all"],
                        help="同步目標 (default: all)")
        if name in ("skills", "all"):
            p.add_argument("--include", default=None, help="只同步指定 skills (逗號分隔)")
            p.add_argument("--exclude", default=None, help="排除指定 skills (逗號分隔)")
        if name in ("instructions", "all"):
            p.add_argument("--cwd", default=None, help="專案目錄 (default: 當前目錄)")

    # status
    sub.add_parser("status", help="顯示跨 CLI 設定狀態")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "sync":
        # Ensure include/exclude/cwd exist on args even if not defined for this subcommand
        if not hasattr(args, "include"):
            args.include = None
        if not hasattr(args, "exclude"):
            args.exclude = None
        if not hasattr(args, "cwd"):
            args.cwd = None

        dispatch = {
            "mcp": cmd_sync_mcp,
            "skills": cmd_sync_skills,
            "instructions": cmd_sync_instructions,
            "agents": cmd_sync_agents,
            "hooks": cmd_sync_hooks,
            "all": cmd_sync_all,
        }
        fn = dispatch.get(args.what)
        if fn:
            fn(args)
        else:
            sync_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
