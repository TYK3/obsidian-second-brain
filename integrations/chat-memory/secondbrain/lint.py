"""Mechanical vault health check - free, no model calls. The night shift runs this before the librarian."""
from __future__ import annotations

import re
from collections import Counter

from .ops import distill_queue
from .vault import Vault, now, parse_frontmatter

LINK = re.compile(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")
REQUIRED = ("type", "title", "created", "updated")


def lint(vault: Vault) -> dict:
    stems: dict[str, list[str]] = {}
    for p in vault.root.rglob("*.md"):
        if ".raw" in p.parts or ".brain" in p.parts:
            continue
        rel = p.relative_to(vault.root).as_posix()
        stems.setdefault(p.stem, []).append(rel)
        stems.setdefault(rel.removesuffix(".md"), []).append(rel)

    broken, inbound, missing_fm, no_preamble, conflicts = [], Counter(), [], [], []
    notes = list(vault.iter_notes())
    for p in notes:
        rel = p.relative_to(vault.root).as_posix()
        text = p.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        body_no_code = re.sub(r"```[\s\S]*?```", "", body)
        for target in LINK.findall(body_no_code):
            target = target.strip()
            if target in stems:
                for t in stems[target]:
                    inbound[t] += 1
            else:
                broken.append((rel, target))
        top = rel.split("/")[0]
        if top in ("Projects", "Decisions", "Concepts", "People"):
            miss = [k for k in REQUIRED if k not in fm]
            if miss:
                missing_fm.append((rel, miss))
            if "## For future agent" not in body:
                no_preamble.append(rel)
        if "[!conflict]" in body:
            conflicts.append(rel)
    orphans = [p.relative_to(vault.root).as_posix() for p in notes
               if p.relative_to(vault.root).as_posix().split("/")[0] in ("Projects", "Decisions", "Concepts", "People")
               and inbound[p.relative_to(vault.root).as_posix()] == 0]
    queue = distill_queue(vault, 10**6)

    day = now().date().isoformat()
    md = [f"# Mechanical lint {day}", "",
          f"- Knowledge notes: {len(notes)}", f"- Broken links: {len(broken)}", f"- Orphans: {len(orphans)}",
          f"- Missing frontmatter: {len(missing_fm)}", f"- Missing 'For future agent': {len(no_preamble)}",
          f"- Open conflicts: {len(conflicts)}", f"- Conversations waiting to be distilled: {len(queue)}", ""]

    def section(title, rows):
        if rows:
            md.extend([f"## {title}", "", *[f"- {r}" for r in rows[:100]], ""])

    section("Broken links", [f"`{a}` → [[{b}]]" for a, b in broken])
    section("Orphans (nothing links here)", [f"`{o}`" for o in orphans])
    section("Missing frontmatter", [f"`{a}`: {', '.join(b)}" for a, b in missing_fm])
    section("Missing '## For future agent'", [f"`{a}`" for a in no_preamble])
    section("Open conflicts", [f"`{a}`" for a in conflicts])
    return {"date": day, "broken": broken, "orphans": orphans, "missing_frontmatter": missing_fm,
            "no_preamble": no_preamble, "conflicts": conflicts, "undistilled": len(queue), "markdown": "\n".join(md)}
