"""Official data exports from the web/app products.

- Claude.ai:  Settings → Privacy → Export data          → conversations.json
- ChatGPT:    Settings → Data controls → Export data     → conversations.json
- Grok:       grok.com Settings → Data → Download data   → prod-grok-backend.json
- Gemini:     takeout.google.com → "My Activity" → Gemini Apps (JSON format) → MyActivity.json
"""
from __future__ import annotations

import html as htmllib
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator

from ..model import Conversation, Message, parse_ts
from .base import blocks_text, keep, load_json


# ---------------------------------------------------------------- Claude.ai
def sniff_claude(path: Path, head: str) -> bool:
    return path.suffix == ".json" and '"chat_messages"' in head


def parse_claude(path: Path, tools: bool = True) -> Iterator[Conversation]:
    data = load_json(path)
    for c in data if isinstance(data, list) else []:
        conv = Conversation(platform="claude", native_id=c.get("uuid", ""), title=c.get("name") or "",
                            created=parse_ts(c.get("created_at")), updated=parse_ts(c.get("updated_at")),
                            source=str(path))
        for m in c.get("chat_messages", []):
            role = "user" if m.get("sender") == "human" else "assistant"
            text = blocks_text(m.get("content"), tools=tools) or m.get("text", "")
            for a in m.get("attachments") or []:
                if a.get("extracted_content"):
                    text += f"\n\n📎 **{a.get('file_name', 'attachment')}**\n\n{a['extracted_content'][:4000]}"
            conv.messages.append(Message(role, text, parse_ts(m.get("created_at"))))
        if keep(conv):
            yield conv


# ---------------------------------------------------------------- ChatGPT
def sniff_chatgpt(path: Path, head: str) -> bool:
    return path.suffix == ".json" and '"mapping"' in head and '"current_node"' in head


def _chatgpt_text(content: dict) -> str:
    ctype = content.get("content_type")
    if ctype in ("text", "multimodal_text"):
        return "\n".join(p for p in content.get("parts", []) if isinstance(p, str))
    if ctype == "code":
        return f"```\n{content.get('text', '')}\n```"
    return ""  # thoughts, browsing displays, tool output, etc.


def parse_chatgpt(path: Path, tools: bool = True) -> Iterator[Conversation]:
    data = load_json(path)
    for c in data if isinstance(data, list) else []:
        mapping = c.get("mapping") or {}
        chain, node = [], c.get("current_node")
        while node and node in mapping:  # walk the active branch back to the root
            chain.append(mapping[node])
            node = mapping[node].get("parent")
        conv = Conversation(platform="chatgpt", native_id=c.get("conversation_id") or c.get("id", ""),
                            title=c.get("title") or "", created=parse_ts(c.get("create_time")),
                            updated=parse_ts(c.get("update_time")), model=c.get("default_model_slug"),
                            source=str(path))
        for n in reversed(chain):
            m = n.get("message") or {}
            role = (m.get("author") or {}).get("role")
            meta = m.get("metadata") or {}
            if role not in ("user", "assistant") or meta.get("is_visually_hidden_from_conversation"):
                continue
            text = _chatgpt_text(m.get("content") or {})
            conv.messages.append(Message(role, text, parse_ts(m.get("create_time")), meta.get("model_slug")))
        if keep(conv):
            yield conv


# ---------------------------------------------------------------- Grok
def sniff_grok(path: Path, head: str) -> bool:
    return path.suffix == ".json" and '"conversations"' in head and ('"responses"' in head or "grok" in path.name)


def parse_grok(path: Path, tools: bool = True) -> Iterator[Conversation]:
    data = load_json(path)
    convs = data.get("conversations", []) if isinstance(data, dict) else data
    for item in convs or []:
        meta = item.get("conversation", item)
        conv = Conversation(platform="grok", native_id=str(meta.get("id") or meta.get("_id") or ""),
                            title=meta.get("title") or "", created=parse_ts(meta.get("create_time")),
                            updated=parse_ts(meta.get("modify_time")), source=str(path))
        responses = [r.get("response", r) for r in item.get("responses", [])]
        responses.sort(key=lambda r: (parse_ts(r.get("create_time")) or conv.created or parse_ts(0)))
        for r in responses:
            sender = str(r.get("sender", "")).lower()
            role = "user" if sender in ("human", "user") else "assistant"
            conv.messages.append(Message(role, r.get("message") or "", parse_ts(r.get("create_time")), r.get("model")))
        if keep(conv):
            yield conv


# ---------------------------------------------------------------- Gemini (Google Takeout)
class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "li", "div", "h1", "h2", "h3", "tr", "pre"):
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_data(self, data):
        self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    return re.sub(r"\n{3,}", "\n\n", htmllib.unescape("".join(p.out))).strip()


def sniff_gemini_takeout(path: Path, head: str) -> bool:
    return path.suffix == ".json" and ('"Gemini Apps"' in head or '"Bard"' in head) and '"title"' in head


def parse_gemini_takeout(path: Path, tools: bool = True) -> Iterator[Conversation]:
    """Takeout has no conversation grouping, so prompts are grouped by day."""
    data = load_json(path)
    days = defaultdict(list)
    for a in data if isinstance(data, list) else []:
        title = a.get("title", "")
        if not title.startswith("Prompted"):
            continue
        ts = parse_ts(a.get("time"))
        if ts:
            days[ts.date().isoformat()].append((ts, a))
    for day, items in days.items():
        conv = Conversation(platform="gemini", native_id=f"takeout-{day}", title=f"Gemini web chats {day}",
                            source=str(path))
        for ts, a in sorted(items, key=lambda x: x[0]):
            conv.messages.append(Message("user", a["title"].removeprefix("Prompted").strip(), ts))
            reply = "\n\n".join(html_to_text(h.get("html", "")) for h in a.get("safeHtmlItem", []))
            conv.messages.append(Message("assistant", reply, ts))
        if keep(conv):
            yield conv


# ---------------------------------------------------------------- Generic
def sniff_generic(path: Path, head: str) -> bool:
    return path.suffix in (".json", ".md", ".txt")


_ROLE_LINE = re.compile(r"^\s*(?:\*\*|#+\s*)?(user|you|human|me|assistant|ai|claude|chatgpt|gpt|grok|gemini|codex|model)"
                        r"(?:\*\*)?\s*:?\s*(?:\*\*)?\s*$|^\s*(user|you|human|assistant|ai|claude|chatgpt|grok|gemini)\s*:\s*(.*)$",
                        re.I)


def parse_generic(path: Path, tools: bool = True, platform: str = "other") -> Iterator[Conversation]:
    """{"messages": [{"role", "content"}]} JSON, or a pasted transcript with 'User:'/'Assistant:' lines."""
    conv = Conversation(platform=platform, native_id=path.stem, title=path.stem.replace("-", " "), source=str(path))
    if path.suffix == ".json":
        data = load_json(path)
        if isinstance(data, dict):
            conv.title = data.get("title") or conv.title
            conv.native_id = str(data.get("id") or data.get("session_id") or conv.native_id)
            data = data.get("messages", [])
        for m in data if isinstance(data, list) else []:
            if isinstance(m, dict):
                role = "user" if m.get("role") in ("user", "human") else "assistant"
                conv.messages.append(Message(role, blocks_text(m.get("content", m.get("text")), tools),
                                             parse_ts(m.get("timestamp") or m.get("created_at"))))
    else:
        role, buf = None, []

        def flush():
            if role and buf:
                conv.messages.append(Message(role, "\n".join(buf).strip()))

        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _ROLE_LINE.match(line)
            if m:
                flush()
                who = (m.group(1) or m.group(2)).lower()
                role = "user" if who in ("user", "you", "human", "me") else "assistant"
                buf = [m.group(3)] if m.group(3) else []
            else:
                buf.append(line)
        flush()
        if not conv.messages:  # no speaker markers: keep the whole file as a note
            conv.messages.append(Message("user", path.read_text(encoding="utf-8", errors="replace")))
    if keep(conv):
        yield conv
