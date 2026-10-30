"""Claude Code: ~/.claude/projects/<project>/<session>.jsonl"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..model import Conversation, Message, parse_ts
from .base import blocks_text, files, iter_jsonl, keep, strip_noise

PLATFORM = "claude-code"
DEFAULT_PATHS = ["~/.claude/projects"]


def sniff(path: Path, head: str) -> bool:
    return path.suffix == ".jsonl" and '"sessionId"' in head and ('"type":"user"' in head.replace(" ", "")
                                                                   or '"parentUuid"' in head)


def parse(path: Path, tools: bool = True) -> Iterator[Conversation]:
    for f in files(path, ["*.jsonl"]):
        if "/subagents/" in str(f):
            continue
        conv = Conversation(platform=PLATFORM, native_id=f.stem, source=str(f))
        for d in iter_jsonl(f):
            kind = d.get("type")
            if kind == "summary" and d.get("summary") and not conv.title:
                conv.title = d["summary"]
            elif kind in ("custom-title", "ai-title") and (d.get("title") or d.get("customTitle")):
                conv.title = d.get("customTitle") or d.get("title")
            att = d.get("attachment") if kind == "attachment" else None
            if isinstance(att, dict) and att.get("type") == "queued_command" and att.get("humanTurn") \
                    and not d.get("isSidechain") and att.get("prompt"):
                # A message the user typed while the agent was mid-turn.
                conv.messages.append(Message("user", strip_noise(str(att["prompt"])), parse_ts(d.get("timestamp"))))
                continue
            if kind not in ("user", "assistant") or d.get("isSidechain") or d.get("isMeta"):
                continue
            conv.native_id = d.get("sessionId") or conv.native_id
            conv.project = conv.project or d.get("cwd")
            msg = d.get("message") or {}
            ts = parse_ts(d.get("timestamp"))
            if kind == "user":
                content = msg.get("content")
                if isinstance(content, list) and all(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    continue  # tool output, not something the human said
                text = strip_noise(blocks_text(content, tools=False))
                if not text or text.startswith(("<local-command-stdout>", "Caveat:", "[Request interrupted")):
                    continue
                conv.messages.append(Message("user", text, ts))
            else:
                text = blocks_text(msg.get("content"), tools=tools)
                if not text:
                    continue
                model = msg.get("model")
                prev = conv.messages[-1] if conv.messages else None
                # Claude Code writes one line per content block; merge them back into one turn.
                if prev and prev.role == "assistant":
                    prev.text += "\n\n" + text
                    prev.model = prev.model or model
                else:
                    conv.messages.append(Message("assistant", text, ts, model))
        if keep(conv):
            yield conv
