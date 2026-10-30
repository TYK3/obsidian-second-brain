"""The vault: an Obsidian folder (and git repo) that is the single source of truth.

Layout
    AGENTS.md / CLAUDE.md / GEMINI.md   operating manual any AI reads on entry
    _brain/CRITICAL_FACTS.md            who you are, ~150 tokens, always loaded
    _brain/hot.md                       recent context (auto section + manual section)
    _brain/handoff.md                   last generated context pack for web chats
    index.md, log.md                    catalog + operation history
    Conversations/<platform>/<YYYY>/    one note per chat, full transcript
    Projects/ Decisions/ Concepts/ People/ Daily/   distilled knowledge (AI-maintained)
    inbox/                              drop export zips/files here; `brain sync` imports them
    .raw/                               content-addressed copies of imported exports (gitignored)
    .brain/                             search index + state (gitignored, rebuildable)
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

from .model import PLATFORMS, Conversation, Message, parse_ts
from .redact import redact

KNOWLEDGE_DIRS = ["Projects", "Decisions", "Concepts", "People", "Daily"]
TRANSCRIPT_MARK = "<!-- brain:transcript - regenerated on sync; write notes above this line -->"
MSG_RE = re.compile(r"^<!-- msg role=(\w+)(?: ts=(\S+))?(?: model=(\S+))? -->$", re.M)
PRESERVED_KEYS = ("summary", "topics", "projects", "distilled", "tags", "starred")
ROLE_LABEL = {"user": "🧑 You", "assistant": "🤖 Assistant"}


# ---------------------------------------------------------------- frontmatter
def dump_frontmatter(d: dict) -> str:
    lines = ["---"]
    for k, v in d.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines += [f"  - {json.dumps(str(x), ensure_ascii=False)}" for x in v]
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {json.dumps(str(v), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Small YAML subset: scalars, quoted strings, and '- item' lists."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    data, key = {}, None
    for line in text[4:end].splitlines():
        if re.match(r"^\s+-\s", line) and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(_scalar(line.split("-", 1)[1].strip()))
        elif ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if val.startswith("[") and val.endswith("]"):
                data[key] = [_scalar(x.strip()) for x in val[1:-1].split(",") if x.strip()]
            else:
                data[key] = _scalar(val) if val else []
    body = text[end + 4:].lstrip("\n")
    return data, body


def _scalar(v: str):
    if v.startswith('"') and v.endswith('"'):
        try:
            return json.loads(v)
        except ValueError:
            return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


# ---------------------------------------------------------------- helpers
def slugify(text: str, limit: int = 60) -> str:
    text = re.sub(r'[\\/:*?"<>|#^\[\]`\n\r\t]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:limit].rstrip(" .") or "Untitled"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


class Vault:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    # ------------------------------------------------------------ paths
    @property
    def convs(self) -> Path:
        return self.root / "Conversations"

    @property
    def state(self) -> Path:
        return self.root / ".brain"

    def exists(self) -> bool:
        return (self.root / "_brain").is_dir()

    def safe_path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"path escapes the vault: {rel}")
        return p

    # ------------------------------------------------------------ init
    def init(self, git: bool = True) -> list[str]:
        created = []
        for d in ["_brain", "Conversations", "inbox", "Clippings", "reports", ".raw", ".brain", *KNOWLEDGE_DIRS]:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        pkg = resources.files("secondbrain")
        tpl = pkg / "templates"
        files = {
            "AGENTS.md": "AGENTS.md", "index.md": "index.md", "log.md": "log.md",
            "gitignore": ".gitignore",
            "obsidian-app.json": ".obsidian/app.json",
            "CRITICAL_FACTS.md": "_brain/CRITICAL_FACTS.md",
            "hot.md": "_brain/hot.md",
            "claude-settings.json": ".claude/settings.json",
            "claude-agents/scout.md": ".claude/agents/scout.md",
            "claude-agents/librarian.md": ".claude/agents/librarian.md",
            "scripts/night.sh": "scripts/night.sh",
            "scripts/night.ps1": "scripts/night.ps1",
        }
        for src, target in files.items():
            dest = self.root / target
            if dest.exists():
                continue
            item = tpl.joinpath(*src.split("/")) if not src.startswith("../") else pkg.joinpath(*src[3:].split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(item.read_text(encoding="utf-8").replace("{{date}}", now().date().isoformat()),
                            encoding="utf-8")
            if dest.suffix == ".sh":
                dest.chmod(0o755)
            created.append(target)
        # Every agent reads a different filename; keep them identical.
        manual = self.root / "AGENTS.md"
        for alias in ("CLAUDE.md", "GEMINI.md"):
            dest = self.root / alias
            if not dest.exists():
                shutil.copyfile(manual, dest)
                created.append(alias)
        for d in ["inbox", "Clippings", "reports", *KNOWLEDGE_DIRS]:
            keep = self.root / d / ".gitkeep"
            if not any((self.root / d).iterdir()):
                keep.touch()
        if git and not (self.root / ".git").exists() and shutil.which("git"):
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=False)
            created.append(".git")
        return created

    # ------------------------------------------------------------ conversations
    def find_conversation(self, uid: str) -> Path | None:
        hits = list(self.convs.rglob(f"*({uid}).md")) if self.convs.exists() else []
        return hits[0] if hits else None

    def conversation_path(self, conv: Conversation) -> Path:
        existing = self.find_conversation(conv.uid)
        if existing:
            return existing
        day = conv.created.astimezone(timezone.utc)
        name = f"{day:%Y-%m-%d} {slugify(conv.title)} ({conv.uid}).md"
        return self.convs / conv.platform / f"{day:%Y}" / name

    def write_conversation(self, conv: Conversation) -> str:
        """Create or update a conversation note. Returns 'new', 'updated' or 'unchanged'."""
        path = self.conversation_path(conv)
        old_fm, notes = {}, ""
        if path.exists():
            old_fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            if old_fm.get("messages") == len(conv.messages) and old_fm.get("updated") == iso(conv.updated):
                return "unchanged"
            notes = body.split(TRANSCRIPT_MARK)[0].rstrip() if TRANSCRIPT_MARK in body else ""
        fm = {
            "type": "conversation",
            "id": conv.uid,
            "platform": conv.platform,
            "title": conv.title,
            "native_id": conv.native_id,
            "created": iso(conv.created),
            "updated": iso(conv.updated),
            "messages": len(conv.messages),
            "model": conv.model,
            "project": conv.project,
            "distilled": False,
            "tags": ["conversation", f"platform/{conv.platform}"],
        }
        if conv.meta.get("partial"):
            fm["partial"] = conv.meta["partial"]
        for k in PRESERVED_KEYS:  # never clobber what an agent or the user wrote
            if k in old_fm:
                fm[k] = old_fm[k]
        if not notes:
            notes = (f"# {conv.title}\n\n"
                     f"> [!info] {PLATFORMS.get(conv.platform, conv.platform)} · "
                     f"{conv.created:%Y-%m-%d} · {len(conv.messages)} messages\n\n"
                     "## Summary\n\n_Not distilled yet. Run `/obsidian-chat-digest`._")
        parts = [dump_frontmatter(fm), notes, "", TRANSCRIPT_MARK, "", "## Transcript", ""]
        for m in conv.messages:
            attrs = f"role={m.role}"
            if m.ts:
                attrs += f" ts={iso(m.ts)}"
            if m.model:
                model = re.sub(r"\s", "", m.model)  # no backslash inside the f-string: py3.10
                attrs += f" model={model}"
            stamp = f" · {m.ts.astimezone(timezone.utc):%Y-%m-%d %H:%M}" if m.ts else ""
            parts += [f"<!-- msg {attrs} -->", f"#### {ROLE_LABEL.get(m.role, m.role)}{stamp}", "",
                      redact(m.text).strip(), ""]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(parts), encoding="utf-8")
        return "updated" if old_fm else "new"

    def read_conversation(self, path: Path) -> tuple[dict, list[Message]]:
        fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        transcript = body.split(TRANSCRIPT_MARK, 1)[-1]
        msgs, matches = [], list(MSG_RE.finditer(transcript))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(transcript)
            chunk = transcript[m.end():end].strip()
            chunk = re.sub(r"^#### .*\n?", "", chunk, count=1).strip()
            msgs.append(Message(m.group(1), chunk, parse_ts(m.group(2)), m.group(3)))
        return fm, msgs

    def iter_conversations(self):
        if self.convs.exists():
            yield from sorted(self.convs.rglob("*.md"))

    def iter_notes(self):
        """Every markdown note that is not a conversation transcript."""
        for p in sorted(self.root.rglob("*.md")):
            rel = p.relative_to(self.root)
            if rel.parts[0] in ("Conversations", "inbox") or rel.parts[0].startswith(".") \
                    or str(rel) in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "log.md"):
                continue
            yield p

    def update_frontmatter(self, path: Path, **changes) -> None:
        fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        fm.update({k: v for k, v in changes.items() if v is not None})
        path.write_text(dump_frontmatter(fm) + "\n" + body, encoding="utf-8")

    # ------------------------------------------------------------ raw exports
    def stash_raw(self, src: Path) -> tuple[str, bool]:
        """Keep an immutable, content-addressed copy of an export. Returns (sha, already_seen)."""
        h = hashlib.sha256()
        with Path(src).open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        sha = h.hexdigest()
        manifest_path = self.root / ".raw" / ".manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if sha in manifest:
            return sha, True
        dest = self.root / ".raw" / f"{sha[:16]}{src.suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copyfile(src, dest)
        manifest[sha] = {"name": src.name, "stored": dest.name, "imported": iso(now())}
        manifest_path.write_text(json.dumps(manifest, indent=1))
        return sha, False

    # ------------------------------------------------------------ log / hot / index
    def log(self, op: str, detail: str) -> None:
        path = self.root / "log.md"
        text = path.read_text(encoding="utf-8") if path.exists() else "# Log\n\nNewest first.\n"
        head, _, rest = text.partition("\n## ")
        entry = f"## {now():%Y-%m-%d %H:%M} UTC · {op}\n\n{detail.strip()}\n"
        path.write_text(f"{head.rstrip()}\n\n{entry}\n" + (f"## {rest}" if rest else ""), encoding="utf-8")

    def refresh_hot(self, days: int = 7, limit: int = 25) -> None:
        """Rewrite the auto section of _brain/hot.md with recent conversations."""
        path = self.root / "_brain" / "hot.md"
        start, end = "<!-- brain:auto:start -->", "<!-- brain:auto:end -->"
        text = path.read_text(encoding="utf-8") if path.exists() else f"# Hot context\n\n{start}\n{end}\n"
        if start not in text:
            text += f"\n{start}\n{end}\n"
        cutoff = now() - timedelta(days=days)
        rows = []
        for p in self.iter_conversations():
            fm, _ = parse_frontmatter(p.read_text(encoding="utf-8")[:4000] + "\n---")
            ts = parse_ts(fm.get("updated"))
            if ts and ts >= cutoff:
                rows.append((ts, fm, p))
        rows.sort(key=lambda r: r[0], reverse=True)
        lines = [f"_Auto-generated {now():%Y-%m-%d %H:%M} UTC - last {days} days, newest first._", ""]
        for ts, fm, p in rows[:limit]:
            summary = fm.get("summary") or ""
            summary = f" - {summary[:140]}" if summary else ""
            lines.append(f"- {ts:%m-%d} **{fm.get('platform')}** [[{p.stem}|{fm.get('title')}]]{summary}")
        if not rows:
            lines.append("- (no conversations in this window)")
        auto = "\n".join(lines)
        text = re.sub(re.escape(start) + r"[\s\S]*?" + re.escape(end), f"{start}\n{auto}\n{end}", text)
        path.write_text(text, encoding="utf-8")

    def refresh_index(self) -> None:
        """Rewrite the auto catalog in index.md: counts per platform + knowledge notes."""
        path = self.root / "index.md"
        start, end = "<!-- brain:auto:start -->", "<!-- brain:auto:end -->"
        text = path.read_text(encoding="utf-8") if path.exists() else f"# Index\n\n{start}\n{end}\n"
        if start not in text:
            text += f"\n{start}\n{end}\n"
        counts: dict[str, int] = {}
        distilled = 0
        for p in self.iter_conversations():
            plat = p.relative_to(self.convs).parts[0]
            counts[plat] = counts.get(plat, 0) + 1
            if "distilled: true" in p.read_text(encoding="utf-8")[:3000]:
                distilled += 1
        lines = ["## Conversations", ""]
        lines += [f"- **{PLATFORMS.get(k, k)}** - {v} chats (`Conversations/{k}/`)" for k, v in sorted(counts.items())]
        lines += ["", f"Distilled: {distilled}/{sum(counts.values())}", ""]
        for d in KNOWLEDGE_DIRS[:-1]:
            notes = sorted((self.root / d).glob("*.md"))
            lines += [f"## {d}", ""]
            lines += [f"- [[{n.stem}]]" for n in notes] or ["- _(none yet)_"]
            lines.append("")
        text = re.sub(re.escape(start) + r"[\s\S]*?" + re.escape(end), f"{start}\n" + "\n".join(lines) + f"\n{end}", text)
        path.write_text(text, encoding="utf-8")

    # ------------------------------------------------------------ git
    def git(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=check)

    def commit(self, message: str, push: bool = False) -> str:
        if not (self.root / ".git").exists():
            return "not a git repo"
        self.git("add", "-A")
        if not self.git("status", "--porcelain").stdout.strip():
            return "nothing to commit"
        r = self.git("commit", "-q", "-m", message)
        if r.returncode:
            return f"commit failed: {r.stderr.strip()}"
        if push and self.git("remote").stdout.strip():
            r = self.git("push", "-q")
            return "committed and pushed" if r.returncode == 0 else f"committed; push failed: {r.stderr.strip()}"
        return "committed"
