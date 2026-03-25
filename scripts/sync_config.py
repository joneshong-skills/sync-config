#!/usr/bin/env python3
"""sync_config.py - Sync Claude Code configuration to other CLI tools.

Usage:
    python3 sync_config.py sync mcp          [--target gemini|codex|copilot|opencode|all]
    python3 sync_config.py sync skills       [--target ...] [--include a,b] [--exclude a,b]
    python3 sync_config.py sync commands     [--target gemini|codex|copilot|opencode|all]
    python3 sync_config.py sync instructions [--target ...] [--cwd /path] [--global]
    python3 sync_config.py sync agents       [--target gemini|opencode]
    python3 sync_config.py sync hooks        [--target gemini]
    python3 sync_config.py sync all          [--target gemini|codex|copilot|opencode|all]
    python3 sync_config.py status
"""

import argparse
import json
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
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"
CLAUDE_MCP_USER = HOME / ".claude" / "mcp.json"
CLAUDE_MCP_GLOBAL = HOME / ".claude.json"  # ← top-level config (actual location)
CLAUDE_MCP_PROJECT = Path(".claude") / "mcp.json"

# Skip list: only self-referential skill
# Headless skills (claude-code-headless, gemini-cli-headless, codex-cli-headless)
# are intentionally synced to ALL CLIs — cross-CLI dispatch requires each CLI
# to know how to invoke the others (e.g., Gemini calling `claude -p`).
SKIP_SKILLS_PATTERNS = [
    "sync-config",  # this skill itself
]

# ---------------------------------------------------------------------------
# Claude Config Readers
# ---------------------------------------------------------------------------


def read_claude_mcp_from_files():
    """Try to read MCP servers from known config files."""
    for path in [CLAUDE_MCP_USER, CLAUDE_MCP_GLOBAL, CLAUDE_MCP_PROJECT]:
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
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return {}

        # Parse server names from list output
        # Format: "name: url_or_cmd (TYPE) - status"
        for line in result.stdout.splitlines():
            line = line.strip()
            m = re.match(r"^(\S+):\s+(.+?)(?:\s+\((\w+)\))?\s+-\s+", line)
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
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Type:"):
                info["type"] = line.split(":", 1)[1].strip().lower()
            elif line.startswith("URL:"):
                info["url"] = line.split(":", 1)[1].strip()
                # URL may contain ":" so rejoin
                if "://" not in info["url"]:
                    info["url"] = (
                        line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else ""
                    )
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
            capture_output=True,
            text=True,
            timeout=10,
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


def read_claude_commands():
    """List command .md files under ~/.claude/commands/."""
    cmds_dir = HOME / ".claude" / "commands"
    if not cmds_dir.is_dir():
        return []
    commands = []
    for f in sorted(cmds_dir.iterdir()):
        if f.is_file() and f.suffix == ".md":
            commands.append(f)
        elif f.is_dir():
            # Subdirectory commands (e.g., pm/create.md → /pm:create)
            for sub in sorted(f.glob("*.md")):
                commands.append(sub)
    return commands


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
    """Find CLAUDE.md in given directory or current directory (project-level)."""
    search_dir = Path(cwd) if cwd else Path.cwd()
    for candidate in [search_dir / "CLAUDE.md", search_dir / ".claude" / "CLAUDE.md"]:
        if candidate.exists():
            return candidate
    return None


def read_claude_global_instructions():
    """Find the global ~/.claude/CLAUDE.md file."""
    global_claude_md = HOME / ".claude" / "CLAUDE.md"
    if global_claude_md.exists():
        return global_claude_md
    return None


def read_claude_rules():
    """Read all global rules from ~/.claude/rules/*.md."""
    rules_dir = HOME / ".claude" / "rules"
    if not rules_dir.is_dir():
        return []
    return sorted(rules_dir.glob("*.md"))


def read_project_rules(cwd=None):
    """Read project-level rules from .claude/rules/*.md."""
    project_dir = Path(cwd) if cwd else Path.cwd()
    rules_dir = project_dir / ".claude" / "rules"
    if not rules_dir.is_dir():
        return []
    return sorted(rules_dir.glob("*.md"))


def read_project_knowledge(cwd=None):
    """Read project memory/knowledge topic files."""
    project_dir = Path(cwd) if cwd else Path.cwd()
    abs_path = str(project_dir.resolve()).replace("/", "-")
    memory_dir = HOME / ".claude" / "projects" / abs_path / "memory"
    if not memory_dir.is_dir():
        return []
    return [f for f in sorted(memory_dir.glob("*.md")) if f.name != "MEMORY.md"]


# ---------------------------------------------------------------------------
# Skill filtering
# ---------------------------------------------------------------------------


def should_skip_skill(name, target):
    """Check if a skill should be skipped for the given target."""
    import fnmatch

    for pattern in SKIP_SKILLS_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
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
    # Codex first: writes to ~/.agents/skills/
    # Gemini second: skips skills already in ~/.agents/skills/ (Gemini reads both)
    # Copilot/OpenCode: no skill discovery, but MCP and instructions sync
    if target in ("codex", "all"):
        from sync_codex import CodexAdapter

        adapters.append(("codex", CodexAdapter()))
    if target in ("gemini", "all"):
        from sync_gemini import GeminiAdapter

        adapters.append(("gemini", GeminiAdapter()))
    if target in ("copilot", "all"):
        from sync_copilot import CopilotAdapter

        adapters.append(("copilot", CopilotAdapter()))
    if target in ("opencode", "all"):
        from sync_opencode import OpenCodeAdapter

        adapters.append(("opencode", OpenCodeAdapter()))
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


def _prune_orphan_skills(target_dir: Path, source_skills: list[str]):
    """Remove skills from target that no longer exist in Claude source."""
    if not target_dir.is_dir():
        return
    removed = 0
    for d in sorted(target_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if d.name not in source_skills:
            import shutil

            if d.is_symlink():
                d.unlink()
            else:
                shutil.rmtree(d)
            print(f"  🗑️  孤兒已移除: {d.name}")
            removed += 1
    if removed:
        print(f"  清理 {removed} 個孤兒 skill")


def cmd_sync_skills(args):
    all_skills = read_claude_skills()
    if not all_skills:
        print("⚠️  未找到 Claude Code Skills")
        return

    include = args.include.split(",") if args.include else None
    exclude = args.exclude.split(",") if args.exclude else None

    # Skill target directories per adapter (copilot/opencode have no skill dirs)
    target_dirs = {
        "codex": [HOME / ".agents" / "skills", HOME / ".codex" / "skills"],
        "gemini": [HOME / ".gemini" / "skills"],
    }

    for name, adapter in get_adapters(args.target):
        filtered = filter_skills(all_skills, name, include, exclude)
        if not filtered:
            print(f"⚠️  沒有適合同步到 {name} 的 skills")
            continue
        print(f"\n🔄 同步 {len(filtered)} 個 Skills → {name.capitalize()}: {', '.join(filtered)}")
        adapter.sync_skills(CLAUDE_SKILLS_DIR, filtered)
        # Prune orphans from all target directories for this adapter
        for td in target_dirs.get(name, []):
            _prune_orphan_skills(td, all_skills)


def cmd_sync_instructions(args):
    do_global = getattr(args, "do_global", False)

    if do_global:
        # Global-level: ~/.claude/CLAUDE.md → ~/.gemini/GEMINI.md, ~/.codex/AGENTS.md
        _sync_global_instructions(args)
    else:
        # Project-level: CLAUDE.md in CWD → GEMINI.md, AGENTS.md in CWD
        _sync_project_instructions(args)


def _sync_project_instructions(args):
    """Sync project-level CLAUDE.md + .claude/rules/ + knowledge → other CLIs."""
    source = read_claude_instructions(args.cwd)
    if not source:
        print("⚠️  未找到專案級 CLAUDE.md")
        return

    # Skip if project source resolves to the global file (avoids writing ~/GEMINI.md)
    global_source = read_claude_global_instructions()
    if global_source and source.resolve() == global_source.resolve():
        print("⏭️  專案 CLAUDE.md 即全域檔案，已由全域同步處理")
        return

    target_dir = Path(args.cwd) if args.cwd else Path.cwd()
    project_rules = read_project_rules(args.cwd)
    knowledge = read_project_knowledge(args.cwd)
    extra = project_rules + knowledge

    print(f"📄 來源: {source}")
    if project_rules:
        print(
            f"📜 專案 Rules: {len(project_rules)} 個 ({', '.join(r.stem for r in project_rules)})"
        )
    if knowledge:
        print(f"📚 專案知識: {len(knowledge)} 個 ({', '.join(k.stem for k in knowledge)})")

    for name, adapter in get_adapters(args.target):
        print(f"\n🔄 同步專案指令 + Rules + 知識 → {name.capitalize()}")
        adapter.sync_instructions(source, target_dir, extra_files=extra)


def _sync_global_instructions(args):
    """Sync ~/.claude/CLAUDE.md + ~/.claude/rules/*.md → other CLIs."""
    source = read_claude_global_instructions()
    if not source:
        print("⚠️  未找到全域 ~/.claude/CLAUDE.md")
        return

    rules = read_claude_rules()
    print(f"📄 全域來源: {source}")
    if rules:
        print(f"📜 全域 Rules: {len(rules)} 個 ({', '.join(r.stem for r in rules)})")

    for name, adapter in get_adapters(args.target):
        if not hasattr(adapter, "sync_global_instructions"):
            print(f"  ⏭️  {name} 不支援全域指令同步")
            continue
        print(f"\n🔄 同步全域指令 + Rules → {name.capitalize()}")
        adapter.sync_global_instructions(source, extra_files=rules)


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


def cmd_sync_commands(args):
    commands = read_claude_commands()
    if not commands:
        print("⚠️  未找到 Custom Commands")
        return

    print(f"⌨️  找到 {len(commands)} 個 commands: {', '.join(c.stem for c in commands)}")

    for name, adapter in get_adapters(args.target):
        if not hasattr(adapter, "sync_commands"):
            print(f"  ⏭️  {name} 不支援 Commands 同步")
            continue
        print(f"\n🔄 同步 Commands → {name.capitalize()}")
        adapter.sync_commands(commands)


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

    print("\n── 全域指令 ──")
    args.do_global = True
    _sync_global_instructions(args)

    print("\n── 專案指令 ──")
    args.do_global = False
    _sync_project_instructions(args)

    print("\n── Custom Commands ──")
    cmd_sync_commands(args)

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
    print(
        f"  Claude Code: {len(claude_mcp)} 個 ({', '.join(claude_mcp.keys()) if claude_mcp else '無'})"
    )

    # Read MCP counts from config files directly (avoids CLI timeout)
    gemini_settings = HOME / ".gemini" / "settings.json"
    if gemini_settings.exists():
        try:
            gs = json.loads(gemini_settings.read_text(encoding="utf-8"))
            gm = gs.get("mcpServers", {})
            print(f"  Gemini CLI: {len(gm)} 個")
        except (json.JSONDecodeError, OSError):
            print("  Gemini CLI: ❓ 無法讀取設定")
    else:
        print("  Gemini CLI: ❌ 設定檔不存在")

    codex_config = HOME / ".codex" / "config.toml"
    if codex_config.exists():
        try:
            content = codex_config.read_text(encoding="utf-8")
            # Count [mcp_servers.*] sections in TOML
            count = len(re.findall(r"^\[mcp_servers\.\w", content, re.MULTILINE))
            print(f"  Codex CLI: {count} 個")
        except OSError:
            print("  Codex CLI: ❓ 無法讀取設定")
    else:
        print("  Codex CLI: ❌ 設定檔不存在")

    copilot_mcp = HOME / ".copilot" / "mcp-config.json"
    if copilot_mcp.exists():
        try:
            cm = json.loads(copilot_mcp.read_text(encoding="utf-8"))
            count = len(cm.get("mcpServers", []))
            print(f"  Copilot CLI: {count} 個")
        except (json.JSONDecodeError, OSError):
            print("  Copilot CLI: ❓ 無法讀取設定")
    else:
        print("  Copilot CLI: ❌ 設定檔不存在")

    opencode_config = HOME / ".config" / "opencode" / "opencode.json"
    if opencode_config.exists():
        try:
            oc = json.loads(opencode_config.read_text(encoding="utf-8"))
            count = len(oc.get("mcp", {}))
            print(f"  OpenCode: {count} 個")
        except (json.JSONDecodeError, OSError):
            print("  OpenCode: ❓ 無法讀取設定")
    else:
        print("  OpenCode: ❌ 設定檔不存在")

    # Skills
    print("\n── Skills ──")
    claude_skills = read_claude_skills()
    print(f"  Claude Code: {len(claude_skills)} 個 ({', '.join(claude_skills)})")

    for cli_name, skills_dir in [
        ("Gemini CLI", HOME / ".gemini" / "skills"),
        ("Codex CLI", HOME / ".agents" / "skills"),
    ]:
        if skills_dir.is_dir():
            skills = [
                d.name
                for d in sorted(skills_dir.iterdir())
                if d.is_dir() and (d / "SKILL.md").exists()
            ]
            symlinked = sum(1 for d in skills_dir.iterdir() if d.is_symlink())
            copied = len(skills) - symlinked
            mode = f"🔗 {symlinked} symlink" if symlinked else ""
            if copied:
                mode += (", " if mode else "") + f"📁 {copied} copy"
            print(f"  {cli_name}: {len(skills)} 個 ({mode})")
        else:
            print(f"  {cli_name}: 0 個 (目錄不存在)")

    # Instructions
    print("\n── 專案指令 ──")
    cwd = Path.cwd()
    for fname, cli_name in [
        ("CLAUDE.md", "Claude Code"),
        ("GEMINI.md", "Gemini CLI"),
        ("AGENTS.md", "Codex CLI / Copilot CLI"),
        ("OPENCODE.md", "OpenCode"),
    ]:
        fpath = cwd / fname
        if fpath.exists():
            size = fpath.stat().st_size
            print(f"  {cli_name}: ✅ {fname} ({size} bytes)")
        else:
            print(f"  {cli_name}: ❌ {fname} 不存在")
    # Copilot-specific: .github/copilot-instructions.md
    copilot_instr = cwd / ".github" / "copilot-instructions.md"
    if copilot_instr.exists():
        size = copilot_instr.stat().st_size
        print(f"  Copilot CLI: ✅ .github/copilot-instructions.md ({size} bytes)")
    else:
        print("  Copilot CLI: ❌ .github/copilot-instructions.md 不存在")

    # Agents
    print("\n── Custom Agents ──")
    agents = read_claude_agents()
    print(f"  Claude Code: {len(agents)} 個")
    gemini_agents_dir = HOME / ".gemini" / "agents"
    if gemini_agents_dir.is_dir():
        ga = list(gemini_agents_dir.glob("*.md"))
        print(f"  Gemini CLI: {len(ga)} 個")
    else:
        print("  Gemini CLI: 0 個")
    print("  Codex CLI: ⏭️ 不支援使用者自訂 agents")
    print("  Copilot CLI: ⏭️ agents 定義於 AGENTS.md 內")
    opencode_config = HOME / ".config" / "opencode" / "opencode.json"
    if opencode_config.exists():
        try:
            oc = json.loads(opencode_config.read_text(encoding="utf-8"))
            oa = oc.get("agent", {})
            print(f"  OpenCode: {len(oa)} 個")
        except (json.JSONDecodeError, OSError):
            print("  OpenCode: ❓ 無法讀取")
    else:
        print("  OpenCode: 0 個")

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
            print("  Gemini CLI: ❓ 無法讀取")
    else:
        print("  Gemini CLI: 0 個事件")
    print("  Codex CLI: ⏭️ 不支援 hooks")
    print("  Copilot CLI: ⏭️ 不支援 hooks")
    print("  OpenCode: ⏭️ 不支援 hooks")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Sync Claude Code configuration to Gemini, Codex, Copilot, and OpenCode CLIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # sync
    sync_parser = sub.add_parser("sync", help="同步設定")
    sync_sub = sync_parser.add_subparsers(dest="what")

    for name in ["mcp", "skills", "commands", "instructions", "agents", "hooks", "all"]:
        p = sync_sub.add_parser(name)
        p.add_argument(
            "--target",
            default="all",
            choices=["gemini", "codex", "copilot", "opencode", "all"],
            help="同步目標 (default: all)",
        )
        if name in ("skills", "all"):
            p.add_argument("--include", default=None, help="只同步指定 skills (逗號分隔)")
            p.add_argument("--exclude", default=None, help="排除指定 skills (逗號分隔)")
        if name in ("instructions", "all"):
            p.add_argument("--cwd", default=None, help="專案目錄 (default: 當前目錄)")
        if name == "instructions":
            p.add_argument(
                "--global",
                dest="do_global",
                action="store_true",
                help="同步全域指令 (~/.claude/CLAUDE.md → ~/.gemini/GEMINI.md / ~/.codex/AGENTS.md)",
            )

    # status
    sub.add_parser("status", help="顯示跨 CLI 設定狀態")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "sync":
        # Ensure include/exclude/cwd/do_global exist on args even if not defined for this subcommand
        if not hasattr(args, "include"):
            args.include = None
        if not hasattr(args, "exclude"):
            args.exclude = None
        if not hasattr(args, "cwd"):
            args.cwd = None
        if not hasattr(args, "do_global"):
            args.do_global = False

        dispatch = {
            "mcp": cmd_sync_mcp,
            "skills": cmd_sync_skills,
            "instructions": cmd_sync_instructions,
            "commands": cmd_sync_commands,
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
