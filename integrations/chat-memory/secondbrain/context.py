"""Build a portable context pack: paste it (or upload it) into any AI chat to "load" your brain."""
from __future__ import annotations

import re

from .search import Index
from .vault import Vault, now, parse_frontmatter

CHARS_PER_TOKEN = 4


def _section(vault: Vault, rel: str) -> str:
    p = vault.root / rel
    if not p.exists():
        return ""
    _, body = parse_frontmatter(p.read_text(encoding="utf-8"))
    return compact(body)


def compact(md: str) -> str:
    """Drop what costs tokens but carries nothing: comments, agent preambles, empty template slots."""
    md = re.sub(r"<!--[\s\S]*?-->", "", md)
    md = re.sub(r"^## For future agent\n[\s\S]*?(?=^## |\Z)", "", md, flags=re.M)
    md = re.sub(r"^# .*\n", "", md, flags=re.M)  # page H1s; the pack has its own headings
    lines = [l for l in md.splitlines() if not re.fullmatch(r"\s*-\s*([^:]{1,40}:)?\s*", l)]
    out = []
    for i, line in enumerate(lines):  # drop headings whose section ended up empty
        if line.startswith("#"):
            nxt = next((l for l in lines[i + 1:] if l.strip()), "")
            if not nxt or (nxt.startswith("#") and nxt.count("#") <= line.count("#")):
                continue
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"^## ", "### ", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_context(vault: Vault, query: str | None = None, budget_tokens: int = 4000, days: int = 7) -> str:
    budget = budget_tokens * CHARS_PER_TOKEN
    idx = Index(vault)
    idx.refresh()
    parts = [
        "# Context from my second brain",
        f"_Generated {now():%Y-%m-%d %H:%M} UTC. This is my persistent memory across AI tools "
        "(Claude, Codex, ChatGPT, Gemini, Grok). Use it as background; ask me before assuming anything it doesn't say._",
    ]
    facts = _section(vault, "_brain/CRITICAL_FACTS.md")
    if facts:
        parts += ["## About me", facts]
    hot = _section(vault, "_brain/hot.md")
    if hot:
        hot = hot.replace("<!-- brain:auto:start -->", "").replace("<!-- brain:auto:end -->", "")
        parts += ["## Recent activity", hot]
    projects = sorted((vault.root / "Projects").glob("*.md"))
    if projects:
        lines = []
        for p in projects:
            fm, body = parse_frontmatter(p.read_text(encoding="utf-8"))
            if str(fm.get("status", "active")) in ("archived", "done"):
                continue
            blurb = fm.get("summary") or next((l for l in body.splitlines() if l.strip() and not l.startswith("#")), "")
            lines.append(f"- **{fm.get('title', p.stem)}** - {str(blurb)[:200]}")
        if lines:
            parts += ["## Active projects", "\n".join(lines)]
    if query:
        hits = idx.search(query, limit=8)
        lines = []
        for h in hits:
            what = h["summary"] or " / ".join(h["snippets"])
            lines.append(f"- [{h['platform'] or h['kind']}] **{h['title']}** ({h['updated'][:10]}): {what[:400]}")
        parts += [f"## Relevant to: {query}", "\n".join(lines) or "_No matches in the vault._"]
    idx.close()
    text = "\n\n".join(parts)
    if len(text) > budget:
        text = text[:budget].rsplit("\n", 1)[0] + "\n\n_[context truncated to budget]_"
    return text
