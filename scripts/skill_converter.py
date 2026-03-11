#!/usr/bin/env python3
"""Convert Claude SKILL.md to UNIVERSAL.md for Codex/Gemini CLIs.

Strips Claude-specific sections and remaps tool names for cross-CLI compatibility.

Usage:
    python3 skill_converter.py --skill pdf
    python3 skill_converter.py --skill pdf --target gemini
    python3 skill_converter.py --all --target codex
    python3 skill_converter.py --all --target gemini --dry-run
"""

import argparse
import os
import re
import sys
from pathlib import Path

SKILLS_DIR = Path(os.path.expanduser("~/.claude/skills"))

# Import cold-skill description fallback
sys.path.insert(0, os.path.expanduser("~/.claude/data/skill-index"))
try:
    from resolve_description import resolve_from_frontmatter
except ImportError:

    def resolve_from_frontmatter(fm, name):
        return fm.get("description", "")


# Output directories per target CLI
TARGET_DIRS = {
    "gemini": Path(os.path.expanduser("~/.gemini/skills")),
    "codex": Path(os.path.expanduser("~/.agents/skills")),
}

# Claude tool → universal tool name mapping
TOOL_MAP = {
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "edit_file",
    "Bash": "run_shell_command",
    "Glob": "find_files",
    "Grep": "search_content",
    "WebSearch": "web_search",
    "WebFetch": "web_fetch",
    "Task": "delegate_task",
    "AskUserQuestion": "ask_user",
    "NotebookEdit": "edit_notebook",
}

# Sections to strip entirely (case-insensitive header match)
STRIP_SECTIONS = [
    "agent delegation",
    "continuous improvement",
    "additional resources",
]

# Patterns to remove from body text
STRIP_PATTERNS = [
    r"Delegate.*?to `\w+` agent\.?\n?",  # Delegate to worker agent.
    r"/[\w-]+\b",  # /skill-name references
    r"Use the `Task` tool.*?\n",  # Task tool delegation instructions
]


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter and return (metadata dict, body text)."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
    if not match:
        return {}, content

    fm = {}
    raw = match.group(1)
    body = match.group(2)

    current_key = None
    current_val = []

    for line in raw.split("\n"):
        kv = re.match(r"^(\w[\w-]*):\s*(.*)", line)
        if kv:
            if current_key and current_val:
                fm[current_key] = " ".join(current_val).strip()
            current_key = kv.group(1)
            val = kv.group(2).strip()
            if val and val != ">-":
                current_val = [val]
            else:
                current_val = []
        elif current_key and line.strip():
            current_val.append(line.strip())

    if current_key and current_val:
        fm[current_key] = " ".join(current_val).strip()

    return fm, body


def strip_sections(body: str) -> str:
    """Remove Claude-specific sections by header."""
    lines = body.split("\n")
    result = []
    skip = False
    skip_level = 0

    for line in lines:
        header_match = re.match(r"^(#{1,3})\s+(.*)", line)
        if header_match:
            level = len(header_match.group(1))
            title = header_match.group(2).strip().lower()

            if any(s in title for s in STRIP_SECTIONS):
                skip = True
                skip_level = level
                continue

            if skip and level <= skip_level:
                skip = False

        if not skip:
            result.append(line)

    return "\n".join(result)


def remap_tools(body: str) -> str:
    """Replace Claude tool names with universal equivalents.

    Only replaces backtick-wrapped tool names to avoid false positives
    (e.g., 'Read a PDF' should NOT become 'read_file a PDF').
    """
    for claude_name, universal_name in TOOL_MAP.items():
        # Only match backtick-wrapped tool names (safe, no false positives)
        body = body.replace(f"`{claude_name}`", f"`{universal_name}`")
    return body


def strip_patterns(body: str) -> str:
    """Remove Claude-specific inline patterns."""
    for pattern in STRIP_PATTERNS:
        body = re.sub(pattern, "", body)
    # Clean up multiple blank lines
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body


def build_universal_frontmatter(fm: dict, target: str) -> str:
    """Build universal frontmatter for target CLI."""
    parts = ["---"]

    if "name" in fm:
        parts.append(f"name: {fm['name']}")
    if "description" in fm:
        # Trim description to first sentence
        desc = fm["description"]
        first_sent = desc.split(".")[0] + "." if "." in desc else desc
        if len(first_sent) > 200:
            first_sent = first_sent[:200] + "..."
        parts.append(f"description: {first_sent}")
    if "version" in fm:
        parts.append(f"version: {fm['version']}")
    if "tools" in fm:
        tools = fm["tools"]
        for claude_name, universal_name in TOOL_MAP.items():
            tools = tools.replace(claude_name, universal_name)
        parts.append(f"tools: {tools}")

    parts.append("source: claude-code")
    parts.append(f"target: {target}")
    parts.append("---")

    return "\n".join(parts)


def convert_skill(skill_name: str, target: str, dry_run: bool = False) -> str:
    """Convert a single SKILL.md to UNIVERSAL.md."""
    skill_dir = SKILLS_DIR / skill_name
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.exists():
        return f"  SKIP {skill_name}: SKILL.md not found"

    content = skill_md.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    if not fm:
        return f"  SKIP {skill_name}: no frontmatter"

    # Resolve cold-skill description
    fm["description"] = resolve_from_frontmatter(fm, skill_name)

    # Transform body
    body = strip_sections(body)
    body = strip_patterns(body)
    body = remap_tools(body)

    # Build output
    new_fm = build_universal_frontmatter(fm, target)
    output = f"{new_fm}\n\n{body.strip()}\n"

    if dry_run:
        line_count = len(output.split("\n"))
        return f"  DRY-RUN {skill_name}: {line_count} lines → {target}"

    # Write to target directory
    target_dir = TARGET_DIRS[target] / skill_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "UNIVERSAL.md"
    target_file.write_text(output, encoding="utf-8")

    # Copy scripts if they exist
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.exists():
        target_scripts = target_dir / "scripts"
        target_scripts.mkdir(exist_ok=True)
        for script in scripts_dir.iterdir():
            if script.is_file() and script.name != ".gitkeep":
                (target_scripts / script.name).write_text(
                    script.read_text(encoding="utf-8"), encoding="utf-8"
                )

    return f"  OK {skill_name} → {target_file}"


def main():
    parser = argparse.ArgumentParser(description="Convert SKILL.md to UNIVERSAL.md")
    parser.add_argument("--skill", help="Single skill name to convert")
    parser.add_argument("--all", action="store_true", help="Convert all skills")
    parser.add_argument(
        "--target",
        choices=["gemini", "codex"],
        default="gemini",
        help="Target CLI (default: gemini)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if not args.skill and not args.all:
        parser.error("Specify --skill NAME or --all")

    results = []

    if args.all:
        for d in sorted(SKILLS_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and (d / "SKILL.md").exists():
                results.append(convert_skill(d.name, args.target, args.dry_run))
    else:
        results.append(convert_skill(args.skill, args.target, args.dry_run))

    for r in results:
        print(r, file=sys.stderr)

    ok_count = sum(1 for r in results if r.strip().startswith("OK"))
    skip_count = sum(1 for r in results if "SKIP" in r)
    print(
        f"\nConverted: {ok_count}, Skipped: {skip_count}, Target: {args.target}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
