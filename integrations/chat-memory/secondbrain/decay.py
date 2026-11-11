"""Memory tiers: notes fade unless they are used. Deterministic, no model calls.

Each note has a retention score R = exp(-age_days / S), where age counts from the last time
the note was read or updated, and the strength S = half_life(type) * (1 + ln(1 + reads)):
every read slows forgetting (the Ebbinghaus-style curve from agent-second-brain's autograph,
with the access-aging idea from ai-memory). Tiers:

    core     pinned (`tier: core` / `pinned: true` in frontmatter, or linked from CRITICAL_FACTS)
    active   R >= 0.6     loaded first into context packs
    warm     R >= 0.3     found by normal search
    cold     R >= 0.1     found by deep search
    archive  R <  0.1     almost gone; one is resurfaced at random each day for creative recall

Reads are recorded in `.brain/access.json` (gitignored, rebuildable); notes are never
rewritten, so a nightly run causes no git churn. `brain decay` writes `_brain/memory-tiers.md`
for agents and `.brain/tiers.json` for tools.
"""
from __future__ import annotations

import json
import math
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from .model import parse_ts
from .vault import KNOWLEDGE_DIRS, Vault, now, parse_frontmatter

ACCESS_FILE = ".brain/access.json"
TIERS_FILE = ".brain/tiers.json"
REPORT = "_brain/memory-tiers.md"
# Days for retention to fall to 1/e with no reads; people and decisions are slow to fade.
HALF_LIFE = {"person": 100, "decision": 120, "project": 60, "concept": 90, "daily": 25,
             "conversation": 25, "source": 45, "note": 45}
FOLDER_KIND = {"People": "person", "Decisions": "decision", "Projects": "project",
               "Concepts": "concept", "Daily": "daily", "Conversations": "conversation"}
THRESHOLDS = (("active", 0.6), ("warm", 0.3), ("cold", 0.1))
ORDER = ["core", "active", "warm", "cold", "archive"]


def _load(vault: Vault) -> dict:
    p = vault.root / ACCESS_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_access(vault: Vault, rel: str, when: datetime | None = None) -> None:
    """Count one read of a vault note. Never raises: tracking must not break a read."""
    try:
        rel = Path(rel).as_posix().lstrip("/")
        data = _load(vault)
        entry = data.get(rel) or {"count": 0}
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last"] = (when or now()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data[rel] = entry
        p = vault.root / ACCESS_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
    except Exception:  # noqa: BLE001 - best effort by design
        pass


def strength(kind: str, reads: int) -> float:
    return HALF_LIFE.get(kind, HALF_LIFE["note"]) * (1 + math.log1p(max(reads, 0)))


def retention(age_days: float, s: float) -> float:
    return math.exp(-max(age_days, 0.0) / s)


def tier_for(r: float) -> str:
    for name, floor in THRESHOLDS:
        if r >= floor:
            return name
    return "archive"


def _pinned_titles(vault: Vault) -> set[str]:
    p = vault.root / "_brain" / "CRITICAL_FACTS.md"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    return {m.split("|")[0].split("/")[-1].strip().lower() for m in re.findall(r"\[\[([^\]]+)\]\]", text)}


def _candidates(vault: Vault):
    for d in KNOWLEDGE_DIRS:
        base = vault.root / d
        if base.exists():
            yield from sorted(base.rglob("*.md"))
    yield from vault.iter_conversations()


def compute(vault: Vault, at: datetime | None = None) -> list[dict]:
    at = at or now()
    access = _load(vault)
    pinned = _pinned_titles(vault)
    rows = []
    for p in _candidates(vault):
        rel = p.relative_to(vault.root).as_posix()
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8")[:4000] + "\n---")
        except OSError:
            continue
        kind = str(fm.get("type") or FOLDER_KIND.get(rel.split("/")[0], "note")).lower()
        if kind not in HALF_LIFE:
            kind = FOLDER_KIND.get(rel.split("/")[0], "note")
        a = access.get(rel) or {}
        reads = int(a.get("count", 0))
        stamps = [parse_ts(a.get("last")), parse_ts(fm.get("updated")), parse_ts(fm.get("date")),
                  parse_ts(fm.get("created"))]
        stamps = [s for s in stamps if s]
        last = max(stamps) if stamps else datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        age = (at - last).total_seconds() / 86400
        r = retention(age, strength(kind, reads))
        title = str(fm.get("title") or p.stem)
        is_core = str(fm.get("tier", "")).lower() == "core" or fm.get("pinned") is True \
            or p.stem.lower() in pinned or title.lower() in pinned
        rows.append({"path": rel, "title": title, "kind": kind, "reads": reads,
                     "last": last.strftime("%Y-%m-%d"), "retention": round(r, 3),
                     "tier": "core" if is_core else tier_for(r)})
    rows.sort(key=lambda x: (ORDER.index(x["tier"]), -x["retention"]))
    return rows


def resurface(rows: list[dict], day: str) -> dict | None:
    """One archived (else cold) knowledge note, stable for the day: random recall for creative collisions."""
    for tier in ("archive", "cold"):
        pool = [x for x in rows if x["tier"] == tier and x["kind"] != "conversation"]
        if pool:
            return random.Random(day).choice(pool)
    return None


def run(vault: Vault, at: datetime | None = None) -> dict:
    """Compute tiers, write the agent report and the tool-readable JSON. Returns tier counts."""
    at = at or now()
    rows = compute(vault, at)
    counts = {t: sum(1 for x in rows if x["tier"] == t) for t in ORDER}
    pick = resurface(rows, at.strftime("%Y-%m-%d"))
    (vault.root / ".brain").mkdir(exist_ok=True)
    (vault.root / TIERS_FILE).write_text(json.dumps({"generated": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                     "counts": counts, "resurface": pick, "notes": rows},
                                                    indent=1), encoding="utf-8")

    def link(x):
        return f"- [[{Path(x['path']).stem}]] ({x['kind']}, last touched {x['last']}, {x['reads']} reads)"

    knowledge = [x for x in rows if x["kind"] != "conversation"]
    lines = [
        "---", 'type: "meta"', f"date: {at:%Y-%m-%d}", "tags:", '  - "meta"', '  - "memory-tiers"',
        "ai-first: true", "---", "", "# Memory tiers", "",
        "## For future agent",
        "Generated nightly by `brain decay` (no model calls). Notes fade from active to archive unless "
        "they are read or updated; each read slows the fade. Prefer core and active notes as context; "
        "treat cold and archive notes as possibly stale and check them before relying on them. "
        "Pin a note with `tier: core` in its frontmatter. Do not edit this file; it is regenerated.",
        "",
        "## Counts",
        " | ".join(f"{t}: {counts[t]}" for t in ORDER),
        "",
        "## Core and active knowledge",
        *([link(x) for x in knowledge if x["tier"] in ("core", "active")][:40] or ["- (none yet)"]),
        "",
        "## Fading (cold) - review or let go",
        *([link(x) for x in knowledge if x["tier"] == "cold"][:20] or ["- (none)"]),
        "",
        "## Resurfaced today",
        link(pick) if pick else "- (nothing archived yet)",
        "",
    ]
    (vault.root / REPORT).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {"counts": counts, "resurface": pick["path"] if pick else None, "report": REPORT}


def active_knowledge(vault: Vault, limit: int = 12) -> tuple[list[dict], dict | None]:
    """For context packs: the latest computed core/active knowledge notes and today's resurfaced note."""
    p = vault.root / TIERS_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    notes = [x for x in data.get("notes", []) if x.get("kind") != "conversation"
             and x.get("tier") in ("core", "active")]
    return notes[:limit], data.get("resurface")
