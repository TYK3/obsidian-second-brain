"""Operations shared by the CLI and the MCP server."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import config
from .importers import LOCAL, SKIP_NAMES, import_path
from .model import Conversation, Message, parse_ts
from .search import Index
from .vault import KNOWLEDGE_DIRS, Vault, dump_frontmatter, now, parse_frontmatter, slugify


def ingest(vault: Vault, convs, counts: Counter | None = None) -> Counter:
    counts = counts if counts is not None else Counter()
    for conv in convs:
        status = vault.write_conversation(conv)
        counts[status] += 1
        if status != "unchanged":
            counts[f"{status}:{conv.platform}"] += 1
    return counts


def import_source(vault: Vault, path: Path, importer: str | None = None, platform: str | None = None,
                  tools: bool = True, stash: bool = True) -> Counter:
    path = Path(path).expanduser()
    if stash and path.is_file():
        vault.stash_raw(path)
    return ingest(vault, import_path(path, importer, platform, tools))


def sync(vault: Vault, only: list[str] | None = None, commit: bool = True, push: bool | None = None) -> dict:
    """Pull every local CLI history + inbox exports into the vault, reindex, commit."""
    cfg = config.load()
    tools = cfg.get("include_tools", True)
    counts: Counter = Counter()
    scanned = []
    for imp in LOCAL:
        if only and imp.name not in only:
            continue
        for p in imp.local_paths:
            root = Path(p).expanduser()
            if root.exists():
                scanned.append(str(root))
                ingest(vault, import_path(root, imp.name, tools=tools), counts)
    for src, imp_name in (cfg.get("sources") or {}).items():
        root = Path(src).expanduser()
        if root.exists() and not only:
            scanned.append(str(root))
            ingest(vault, import_path(root, None if imp_name in (None, "", "auto") else imp_name, tools=tools), counts)
    inbox = vault.root / "inbox"
    if inbox.exists() and not only:
        for f in sorted(inbox.iterdir()):
            if f.name.startswith(".") or f.name in SKIP_NAMES or not f.is_file():
                continue
            _, seen = vault.stash_raw(f)
            if seen:
                continue  # this exact export was already imported
            scanned.append(str(f))
            ingest(vault, import_path(f, tools=tools), counts)
    idx = Index(vault)
    idx_stats = idx.refresh()
    idx.close()
    vault.refresh_hot()
    vault.refresh_index()
    changed = {k: v for k, v in counts.items() if ":" in k}
    if changed:
        vault.log("sync", "\n".join(f"- {k.replace(':', ' ')}: {v}" for k, v in sorted(changed.items())))
    git = "skipped"
    if commit:
        msg = "brain sync: " + (", ".join(f"{k} {v}" for k, v in sorted(changed.items())) or "refresh")
        git = vault.commit(msg, push=cfg.get("auto_push", False) if push is None else push)
    return {"scanned": scanned, "new": counts["new"], "updated": counts["updated"],
            "unchanged": counts["unchanged"], "by_platform": changed, "index": idx_stats, "git": git}


def save_conversation(vault: Vault, platform: str, title: str, messages: list[dict],
                      session_id: str | None = None, model: str | None = None, project: str | None = None) -> str:
    """For agents with no local log files (Grok Bot, web chats): push a transcript in directly."""
    platform = slugify(platform.lower(), 30).replace(" ", "-")
    conv = Conversation(platform=platform, native_id=session_id or f"{now():%Y%m%dT%H%M%S}-{slugify(title, 30)}",
                        title=title, model=model, project=project, source="mcp")
    for m in messages:
        role = "user" if str(m.get("role", "")).lower() in ("user", "human", "you") else "assistant"
        conv.messages.append(Message(role, str(m.get("content") or m.get("text") or ""), parse_ts(m.get("timestamp"))))
    conv.finalize()
    if not conv.messages:
        raise ValueError("no messages with text")
    if not any(m.ts for m in conv.messages):
        conv.created = conv.updated = now()
    vault.write_conversation(conv)
    path = vault.conversation_path(conv)
    _reindex(vault)
    return path.relative_to(vault.root).as_posix()


def save_note(vault: Vault, folder: str, title: str, content: str, tags: list[str] | None = None,
              sources: list[str] | None = None, mode: str = "overwrite") -> str:
    """Write a knowledge note. mode: overwrite | append."""
    folder = folder.strip("/") or "Concepts"
    if folder.split("/")[0] not in [*KNOWLEDGE_DIRS, "_brain"]:
        raise ValueError(f"folder must be one of {KNOWLEDGE_DIRS} (or _brain)")
    path = vault.safe_path(f"{folder}/{slugify(title, 100)}.md")
    today = now().date().isoformat()
    kind = {"Projects": "project", "Decisions": "decision", "Concepts": "concept", "People": "person",
            "Daily": "daily"}.get(folder.split("/")[0], "note")
    if path.exists():
        fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        fm["updated"] = today
        if tags:
            fm["tags"] = sorted(set(fm.get("tags") or []) | set(tags))
        if sources:
            fm["sources"] = sorted(set(fm.get("sources") or []) | set(sources))
        body = (body.rstrip() + f"\n\n## Update {today}\n\n" + content.strip()) if mode == "append" else content.strip()
    else:
        fm = {"type": kind, "title": title, "created": today, "updated": today,
              "tags": tags or [kind], "sources": sources or []}
        body = content.strip()
        if not body.startswith("#"):
            body = f"# {title}\n\n{body}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontmatter(fm) + "\n" + body + "\n", encoding="utf-8")
    vault.log("save-note", f"- [[{path.stem}]] ({folder}, {mode})")
    _reindex(vault)
    return path.relative_to(vault.root).as_posix()


def remember(vault: Vault, fact: str, where: str = "facts") -> str:
    """Append a dated durable fact to CRITICAL_FACTS (facts) or the current-focus list in hot.md (focus)."""
    rel = "_brain/CRITICAL_FACTS.md" if where == "facts" else "_brain/hot.md"
    path = vault.root / rel
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    bullet = f"- {fact.strip()} _(as of {now().date().isoformat()})_"
    anchor = "## Learned facts" if where == "facts" else "## Current focus"
    if anchor in text:
        head, _, tail = text.partition(anchor)
        nxt = tail.find("\n## ")
        section, rest = (tail, "") if nxt < 0 else (tail[:nxt], tail[nxt:])
        section = re.sub(r"\n- *\n", "\n", section.rstrip() + "\n") + bullet + "\n"
        text = head + anchor + section + rest
    else:
        text = text.rstrip() + f"\n\n{anchor}\n{bullet}\n"
    path.write_text(text, encoding="utf-8")
    return rel


def resolve(vault: Vault, ref: str) -> Path:
    """Accept a vault-relative path, a conversation id, or a note title."""
    ref = ref.strip()
    m = re.search(r"\(([0-9a-f]{10})\)", ref) or re.fullmatch(r"([0-9a-f]{10})", ref)
    if m:
        p = vault.find_conversation(m.group(1))
        if p:
            return p
    for cand in (ref, ref + ".md"):
        try:
            p = vault.safe_path(cand)
        except ValueError:
            continue
        if p.is_file():
            return p
    stem = ref.removesuffix(".md").strip("[]").split("|")[0]
    hits = [p for p in vault.root.rglob(f"{stem}.md") if ".raw" not in p.parts]
    if hits:
        return hits[0]
    raise FileNotFoundError(f"no note or conversation matches {ref!r}")


def read(vault: Vault, ref: str, max_chars: int = 30000, offset: int = 0) -> str:
    p = resolve(vault, ref)
    text = p.read_text(encoding="utf-8")
    chunk = text[offset:offset + max_chars]
    if offset + max_chars < len(text):
        chunk += f"\n\n[... {len(text) - offset - max_chars} more chars; call again with offset={offset + max_chars}]"
    return f"<!-- {p.relative_to(vault.root).as_posix()} -->\n{chunk}"


def set_summary(vault: Vault, ref: str, summary: str, topics: list[str] | None = None,
                projects: list[str] | None = None) -> str:
    """Record the distilled summary of a conversation (frontmatter + visible Summary section)."""
    p = resolve(vault, ref)
    vault.update_frontmatter(p, summary=summary.strip().replace("\n", " "), topics=topics, projects=projects,
                             distilled=True)
    text = p.read_text(encoding="utf-8")
    links = " ".join(f"[[{x}]]" for x in projects or [])
    block = f"## Summary\n\n{summary.strip()}\n" + (f"\nProjects: {links}\n" if links else "")
    text = re.sub(r"## Summary\n[\s\S]*?(?=\n<!-- brain:transcript|\n## (?!Summary))", block, text, count=1)
    p.write_text(text, encoding="utf-8")
    _reindex(vault)
    return p.relative_to(vault.root).as_posix()


def distill_queue(vault: Vault, limit: int = 20, platform: str | None = None, min_messages: int = 2) -> list[dict]:
    rows = []
    for p in vault.iter_conversations():
        fm, _ = parse_frontmatter(p.read_text(encoding="utf-8")[:4000] + "\n---")
        if fm.get("distilled") is True or (platform and fm.get("platform") != platform):
            continue
        if int(fm.get("messages") or 0) < min_messages:
            continue
        rows.append({"path": p.relative_to(vault.root).as_posix(), "title": fm.get("title"), "platform": fm.get("platform"),
                     "updated": fm.get("updated"), "messages": fm.get("messages")})
    rows.sort(key=lambda r: str(r["updated"]), reverse=True)
    return rows[:limit]


def recent(vault: Vault, days: int = 7, platform: str | None = None, limit: int = 30) -> list[dict]:
    idx = Index(vault)
    idx.refresh()
    out = idx.recent(days, platform, limit)
    idx.close()
    return out


def search(vault: Vault, query: str, limit: int = 10, platform: str | None = None) -> list[dict]:
    idx = Index(vault)
    idx.refresh()
    out = idx.search(query, limit, platform)
    idx.close()
    return out


def _reindex(vault: Vault):
    idx = Index(vault)
    idx.refresh()
    idx.close()


def fmt_hits(hits: list[dict]) -> str:
    if not hits:
        return "No matches."
    out = []
    for h in hits:
        out.append(f"### {h['title']}\n`{h['path']}` · {h['platform'] or h['kind']} · {str(h['updated'])[:10]}")
        if h.get("summary"):
            out.append(f"Summary: {h['summary']}")
        out += [f"> {s}" for s in h["snippets"]]
        out.append("")
    return "\n".join(out)

