"""Importer registry and format auto-detection."""
from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from ..model import Conversation
from . import claude_code, codex, gemini_cli
from . import web_exports as web


@dataclass
class Importer:
    name: str
    platform: str
    sniff: Callable[[Path, str], bool]
    parse: Callable[..., Iterator[Conversation]]
    local_paths: tuple[str, ...] = ()


# Order matters: specific formats before the generic fallback.
IMPORTERS = [
    Importer("claude-code", "claude-code", claude_code.sniff, claude_code.parse, tuple(claude_code.DEFAULT_PATHS)),
    Importer("codex", "codex", codex.sniff, codex.parse, tuple(codex.DEFAULT_PATHS)),
    Importer("gemini-cli", "gemini-cli", gemini_cli.sniff, gemini_cli.parse, tuple(gemini_cli.DEFAULT_PATHS)),
    Importer("claude", "claude", web.sniff_claude, web.parse_claude),
    Importer("chatgpt", "chatgpt", web.sniff_chatgpt, web.parse_chatgpt),
    Importer("grok", "grok", web.sniff_grok, web.parse_grok),
    Importer("gemini", "gemini", web.sniff_gemini_takeout, web.parse_gemini_takeout),
    Importer("generic", "other", web.sniff_generic, web.parse_generic),
]
BY_NAME = {i.name: i for i in IMPORTERS}
LOCAL = [i for i in IMPORTERS if i.local_paths]
SKIP_NAMES = {"projects.json", "users.json", "memories.json", "user.json", "message_feedback.json",
              "shared_conversations.json", "model_comparisons.json", "chat.html"}


def _head(p: Path, n: int = 4096) -> str:
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            return f.read(n)
    except OSError:
        return ""


def detect(path: Path) -> Importer | None:
    head = _head(path)
    for imp in IMPORTERS:
        if imp.sniff(path, head):
            return imp
    return None


def import_path(path: Path, importer: str | None = None, platform: str | None = None,
                tools: bool = True) -> Iterator[Conversation]:
    """Import a file, folder, or .zip export. Auto-detects the format per file."""
    path = Path(path).expanduser()
    if path.suffix == ".zip":
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(path) as z:
                for member in z.namelist():  # guard against path traversal
                    target = (Path(tmp) / member).resolve()
                    if Path(tmp).resolve() in target.parents:
                        z.extract(member, tmp)
            yield from import_path(Path(tmp), importer, platform, tools)
        return
    if importer:
        imp = BY_NAME[importer]
        yield from _run(imp, path, tools, platform)
        return
    if path.is_file():
        imp = detect(path)
        if imp:
            yield from _run(imp, path, tools, platform)
        return
    # Folder: whole-folder importers for known local layouts, else detect per file.
    for imp in LOCAL:
        if any(path.resolve() == Path(p).expanduser().resolve() for p in imp.local_paths):
            yield from _run(imp, path, tools, platform)
            return
    for f in sorted(path.rglob("*")):
        if f.is_file() and f.suffix in (".json", ".jsonl", ".md", ".txt", ".zip") and f.name not in SKIP_NAMES \
                and not any(part.startswith(".") for part in f.relative_to(path).parts):
            yield from import_path(f, None, platform, tools)


def _run(imp: Importer, path: Path, tools: bool, platform: str | None):
    if imp.name == "generic":
        yield from imp.parse(path, tools, platform=platform or "other")
        return
    for conv in imp.parse(path, tools):
        if platform:
            conv.platform = platform
        yield conv
