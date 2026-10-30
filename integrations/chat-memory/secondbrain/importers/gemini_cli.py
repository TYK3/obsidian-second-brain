"""Gemini CLI: ~/.gemini/tmp/<project-hash>/chats/session-*.json

Falls back to logs.json (user prompts only) for sessions that have no saved chat.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterator

from ..model import Conversation, Message, parse_ts
from .base import blocks_text, files, keep, load_json, tool_line

PLATFORM = "gemini-cli"
DEFAULT_PATHS = ["~/.gemini/tmp"]


def sniff(path: Path, head: str) -> bool:
    return path.suffix == ".json" and '"sessionId"' in head and ('"projectHash"' in head or '"messages"' in head)


def _content(c) -> str:
    if isinstance(c, list):
        return "\n".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return blocks_text(c, tools=False)


def parse(path: Path, tools: bool = True) -> Iterator[Conversation]:
    seen: set[str] = set()
    for f in files(path, ["session-*.json"]):
        try:
            data = load_json(f)
        except ValueError:
            continue
        if not isinstance(data, dict) or "messages" not in data:
            continue
        conv = Conversation(platform=PLATFORM, native_id=data.get("sessionId") or f.stem, source=str(f),
                            created=parse_ts(data.get("startTime")), updated=parse_ts(data.get("lastUpdated")),
                            project=data.get("projectHash"))
        for m in data.get("messages", []):
            role = {"user": "user", "gemini": "assistant", "model": "assistant"}.get(m.get("type"))
            if not role:
                continue
            text = _content(m.get("content"))
            if tools and role == "assistant":
                calls = [tool_line(tc.get("name", "tool"), tc.get("args")) for tc in m.get("toolCalls") or []]
                text = "\n\n".join([t for t in [text, *calls] if t])
            conv.messages.append(Message(role, text, parse_ts(m.get("timestamp")), m.get("model")))
        if keep(conv):
            seen.add(conv.native_id)
            yield conv

    # logs.json only has the user's prompts; still worth keeping for sessions without a chat file.
    for f in files(path, ["logs.json"]):
        try:
            rows = load_json(f)
        except ValueError:
            continue
        by_session = defaultdict(list)
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("type") == "user" and r.get("sessionId") not in seen:
                by_session[r["sessionId"]].append(r)
        for sid, items in by_session.items():
            conv = Conversation(platform=PLATFORM, native_id=sid, source=str(f), meta={"partial": "user prompts only"})
            conv.messages = [Message("user", r.get("message", ""), parse_ts(r.get("timestamp"))) for r in items]
            if keep(conv):
                yield conv
