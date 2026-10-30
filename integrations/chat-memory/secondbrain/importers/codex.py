"""OpenAI Codex CLI: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl

Handles both the current envelope format ({"type": "response_item", "payload": {...}})
and the older flat format (first line = session header, then bare items).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..model import Conversation, Message, parse_ts
from .base import blocks_text, files, iter_jsonl, keep, strip_noise, tool_line

PLATFORM = "codex"
DEFAULT_PATHS = ["~/.codex/sessions", "~/.codex/archived_sessions"]

_SKIP_PREFIXES = ("<environment_context>", "<user_instructions>", "# AGENTS.md instructions",
                  "<permissions instructions>", "<turn_aborted>")


def sniff(path: Path, head: str) -> bool:
    return path.suffix == ".jsonl" and ("session_meta" in head or "rollout" in path.name
                                        or ('"instructions"' in head and '"id"' in head))


def parse(path: Path, tools: bool = True) -> Iterator[Conversation]:
    for f in files(path, ["rollout-*.jsonl", "*.jsonl"]):
        conv = Conversation(platform=PLATFORM, native_id=f.stem, source=str(f))
        last_ts = None
        for d in iter_jsonl(f):
            last_ts = parse_ts(d.get("timestamp")) or last_ts
            kind = d.get("type")
            payload = d.get("payload") if isinstance(d.get("payload"), dict) else None
            if kind == "session_meta" and payload:
                conv.native_id = payload.get("id") or conv.native_id
                conv.project = payload.get("cwd")
                conv.created = parse_ts(payload.get("timestamp")) or last_ts
                continue
            if kind == "turn_context" and payload:
                conv.model = payload.get("model") or conv.model
                continue
            if "instructions" in d and "id" in d and kind is None:  # legacy header
                conv.native_id = d["id"]
                conv.created = parse_ts(d.get("timestamp"))
                continue
            item = payload if kind == "response_item" else (d if kind in ("message", "function_call") else None)
            if not item:
                continue
            itype = item.get("type")
            if itype == "message" and item.get("role") in ("user", "assistant"):
                text = blocks_text(item.get("content"), tools=False)
                if item["role"] == "user":
                    if text.lstrip().startswith(_SKIP_PREFIXES):
                        continue
                    text = strip_noise(text)
                conv.messages.append(Message(item["role"], text, last_ts, conv.model if item["role"] == "assistant" else None))
            elif itype in ("function_call", "custom_tool_call", "local_shell_call") and tools:
                line = tool_line(item.get("name") or "shell", item.get("arguments") or item.get("input") or item.get("action"))
                prev = conv.messages[-1] if conv.messages else None
                if prev and prev.role == "assistant":
                    prev.text += "\n\n" + line
                else:
                    conv.messages.append(Message("assistant", line, last_ts, conv.model))
        if keep(conv):
            yield conv
