"""Platform-neutral conversation model shared by every importer."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

PLATFORMS = {
    "claude-code": "Claude Code",
    "claude": "Claude (web/app)",
    "codex": "Codex CLI",
    "chatgpt": "ChatGPT",
    "gemini-cli": "Gemini CLI",
    "gemini": "Gemini (web/app)",
    "grok": "Grok",
    "grok-bot": "Grok Bot",
    "cursor": "Cursor",
    "other": "Other",
}


@dataclass
class Message:
    role: str  # user | assistant | tool | system
    text: str
    ts: datetime | None = None
    model: str | None = None


@dataclass
class Conversation:
    platform: str
    native_id: str
    title: str = ""
    created: datetime | None = None
    updated: datetime | None = None
    messages: list[Message] = field(default_factory=list)
    project: str | None = None  # working dir / project name when known
    model: str | None = None
    source: str | None = None  # where it was imported from
    meta: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        """Stable short id derived from platform + native id."""
        return hashlib.sha1(f"{self.platform}:{self.native_id}".encode()).hexdigest()[:10]

    def finalize(self) -> "Conversation":
        self.messages = [m for m in self.messages if m.text and m.text.strip()]
        stamps = [m.ts for m in self.messages if m.ts]
        if stamps:
            self.created = self.created or min(stamps)
            self.updated = max([self.updated or min(stamps), *stamps])
        self.created = self.created or self.updated or datetime.now(timezone.utc)
        self.updated = self.updated or self.created
        if not self.title:
            first = next((m.text for m in self.messages if m.role == "user"), "Untitled")
            self.title = skip_preamble(first)
        self.title = clean_title(self.title)
        if not self.model:
            self.model = next((m.model for m in reversed(self.messages) if m.model), None)
        return self


# Boilerplate that agent harnesses put before the real request; titles should start after it.
_PREAMBLES = [
    # OpenBot context-reset resume: header, then "[messageId: ...]" and "[timestamp] <speaker>:" lines.
    re.compile(r"^Continue this OpenBot conversation\.[\s\S]*?--- recent messages ---\s*"),
    re.compile(r"^\s*\[messageId: [^\]]*\][^\n]*\n?", re.M),
    re.compile(r"^\s*\[\d{4}-\d\d-\d\dT[^\]]*\][^\n]*:[ \t]*\n?", re.M),
]


def skip_preamble(text: str) -> str:
    for pat in _PREAMBLES:
        text = pat.sub("", text)
    return text.strip() or "Untitled"


def clean_title(text: str, limit: int = 80) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip().strip("#*>` ")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "..."
    return text or "Untitled"


def parse_ts(value) -> datetime | None:
    """Accept ISO strings, epoch seconds/ms, and Mongo-style {"$date": ...}."""
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        inner = value.get("$date", value.get("$numberLong"))
        return parse_ts(inner)
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d+(\.\d+)?", value)):
        num = float(value)
        if num > 1e12:  # milliseconds
            num /= 1000
        try:
            return datetime.fromtimestamp(num, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        s = re.sub(r"(\.\d{6})\d+", r"\1", s)  # trim nanoseconds
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None
