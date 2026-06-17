#!/usr/bin/env python3
"""check-skill-parity.py — drift canary for dual-copy skills.

Workshop keeps two intentional copies of many skills:
  ~/.claude/skills/<slug>/SKILL.md   (Claude Code wording)
  ~/.agents/skills/<slug>/SKILL.md   (Copilot CLI wording — write_file/replace_file, ~/.agents paths)

The two are NOT byte-equal by design, so a full diff would scream false drift
every run. This follows the ponytail check-rule-copies.js technique: assert a
small set of *invariants* that MUST hold across both copies, not full equality.

Invariant contract (the load-bearing things a CLI-reword must never drop):
  1. SYMMETRIC PRESENCE  — a slug present on one side must exist on the other.
  2. NAME MATCH          — frontmatter `name:` identical (it IS the slug, not prose).
  3. DESCRIPTION NOT DEGENERATE — the Copilot copy's description must not have
     collapsed to a placeholder (e.g. "Cannibalize"); trigger keywords are
     load-bearing for skill activation and must survive the reword.

# ponytail: substring/ratio canary, not semantic equality. Catches dropped
#   triggers + missing copies; will NOT catch a reworded-but-wrong description.
#   Upgrade path: add a per-skill INVARIANT_TRIGGERS list (the exact phrases
#   that must appear in both descriptions) when a real drift slips past ratio.

Exit 0 = clean, exit 1 = drift found. Read-only; changes nothing.
"""

import re
import sys
from pathlib import Path

CLAUDE = Path.home() / ".claude" / "skills"
AGENTS = Path.home() / ".agents" / "skills"
DEGENERATE_RATIO = 0.30  # agents desc shorter than 30% of claude desc => suspected placeholder


def slugs(root: Path) -> set[str]:
    return (
        {p.name for p in root.iterdir() if (p / "SKILL.md").is_file()} if root.is_dir() else set()
    )


def frontmatter(skill_md: Path) -> dict[str, str]:
    """Pull name/description from the top YAML frontmatter, handling block
    scalars (`>-`, `|`, etc.). A plain `^key: (.+)$` regex reads those as ">-"
    and reports false drift (the anvil _parse_frontmatter incident).
    # ponytail: handles inline + folded/literal block scalars; not full YAML
    #   (no anchors/nested maps). Upgrade path: import yaml if a skill needs it."""
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fm = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    lines = (fm.group(1) if fm else text).splitlines()
    out = {}
    for key in ("name", "description"):
        for i, line in enumerate(lines):
            m = re.match(rf"{key}:\s*(.*)$", line)
            if not m:
                continue
            val = m.group(1).strip()
            if re.fullmatch(r"[>|][+-]?", val):  # block scalar indicator -> read indented body
                indent = len(line) - len(line.lstrip())
                body = []
                for nxt in lines[i + 1 :]:
                    if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                        break
                    body.append(nxt.strip())
                val = " ".join(b for b in body if b)
            out[key] = val.strip().strip('"').strip()
            break
    return out


def main() -> int:
    c_slugs, a_slugs = slugs(CLAUDE), slugs(AGENTS)
    drifts: list[str] = []

    # Invariant 1: symmetric presence (only for slugs that exist in at least one dual context).
    # A skill living only in ~/.claude is fine (Claude-only); we only flag ones that
    # exist on one side but were clearly meant to be dual (present in agents but not claude
    # is the dangerous direction — an orphaned copilot copy).
    for s in sorted(a_slugs - c_slugs):
        drifts.append(
            f"PRESENCE [{s}]: in ~/.agents but missing from ~/.claude (orphaned Copilot copy)"
        )

    # Invariants 2 & 3: for every dual-present skill.
    for s in sorted(c_slugs & a_slugs):
        cf = frontmatter(CLAUDE / s / "SKILL.md")
        af = frontmatter(AGENTS / s / "SKILL.md")

        if cf.get("name") != af.get("name"):
            drifts.append(f"NAME [{s}]: claude={cf.get('name')!r} agents={af.get('name')!r}")

        cd, ad = cf.get("description", ""), af.get("description", "")
        if cd and (not ad or len(ad) < len(cd) * DEGENERATE_RATIO):
            drifts.append(
                f"DESC [{s}]: agents description looks degenerate "
                f"({len(ad)} vs {len(cd)} chars) -> {ad[:40]!r}"
            )

    dual = len(c_slugs & a_slugs)
    if drifts:
        print(f"DRIFT — {len(drifts)} issue(s) across {dual} dual-copy skills:\n")
        print("\n".join(f"  - {d}" for d in drifts))
        print("\nFix the ~/.agents copy (or ~/.claude) so the invariants match.")
        return 1
    print(f"Parity OK — {dual} dual-copy skills, all invariants hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
