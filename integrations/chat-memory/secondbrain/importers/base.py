"""Helpers shared by importers."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Iterator

from ..model import Conversation

TOOL_PREVIEW = 160

# Wrapper tags that harnesses inject into "user" turns but the human never typed.
_NOISE_TAGS = re.compile(
    r"<(system-reminder|environment_context|user_instructions|local-command-caveat|"
    r"command-message|ide_opened_file|ide_selection|openbot_\w+)>[\s\S]*?</\1>",
)


def strip_noise(text: str) -> str:
    text = _NOISE_TAGS.sub("", text)
    # Slash commands: keep them readable as "/name args".
    m = re.search(r"<command-name>(.*?)</command-name>", text)
    if m:
        args = re.search(r"<command-args>([\s\S]*?)</command-args>", text)
        text = f"{m.group(1).strip()} {args.group(1).strip() if args else ''}".strip()
    return text.strip()


def tool_line(name: str, args) -> str:
    """One-line summary of a tool call so transcripts stay readable."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            pass
    if isinstance(args, dict):
        key = next((k for k in ("command", "cmd", "file_path", "path", "query", "pattern", "url",
                                "description", "prompt") if k in args), None)
        preview = args[key] if key else json.dumps(args, ensure_ascii=False)
    else:
        preview = str(args or "")
    if isinstance(preview, list):
        preview = " ".join(map(str, preview))
    preview = re.sub(r"\s+", " ", str(preview)).strip()
    if len(preview) > TOOL_PREVIEW:
        preview = preview[:TOOL_PREVIEW] + "..."
    return f"`🔧 {name}` {preview}".rstrip()


def blocks_text(content, tools: bool = True) -> str:
    """Flatten Anthropic/OpenAI/Gemini style content blocks into text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    out = []
    for b in content:
        if isinstance(b, str):
            out.append(b)
            continue
        if not isinstance(b, dict):
            continue
        kind = b.get("type")
        if kind in ("text", "input_text", "output_text") or (kind is None and "text" in b):
            out.append(b.get("text") or "")
        elif kind == "tool_use" and tools:
            out.append(tool_line(b.get("name", "tool"), b.get("input")))
        elif kind == "functionCall" or "functionCall" in b:
            fc = b.get("functionCall", b)
            if tools:
                out.append(tool_line(fc.get("name", "tool"), fc.get("args")))
        # thinking, tool_result, images, etc. are intentionally dropped
    return "\n\n".join(x for x in out if x and x.strip())


def load_json(path: Path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def iter_jsonl(path: Path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


def files(root: Path, patterns: Iterable[str]) -> list[Path]:
    if root.is_file():
        return [root]
    found: set[Path] = set()
    for pat in patterns:
        found.update(p for p in root.rglob(pat) if p.is_file())
    return sorted(found)


def keep(conv: Conversation) -> bool:
    conv.finalize()
    return any(m.role == "user" for m in conv.messages) and len(conv.messages) >= 1
