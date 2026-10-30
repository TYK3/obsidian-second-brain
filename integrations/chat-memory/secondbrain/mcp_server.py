"""Minimal MCP server (JSON-RPC 2.0 over stdio, no dependencies).

Every MCP-capable agent - Claude Code, Claude Desktop, Codex CLI, Gemini CLI, Cursor,
Grok Bot - can connect to this and share one memory.
"""
from __future__ import annotations

import json
import sys
import traceback

from . import __version__, ops
from .context import build_context
from .vault import Vault

SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

_S = {"type": "string"}
_I = {"type": "integer"}
_L = {"type": "array", "items": {"type": "string"}}

TOOLS = [
    {"name": "brain_context",
     "description": "Load the user's second brain: who they are, what they've worked on recently across ALL AI "
                    "platforms, active projects, and (optionally) the most relevant past conversations for a topic. "
                    "Call this at the start of any substantial task.",
     "inputSchema": {"type": "object", "properties": {"query": _S, "budget_tokens": _I}}},
    {"name": "brain_search",
     "description": "Full-text search over every past conversation (Claude, Claude Code, Codex, ChatGPT, Gemini, Grok) "
                    "and every knowledge note. Use before asking the user to repeat something.",
     "inputSchema": {"type": "object", "properties": {"query": _S, "limit": _I,
                                                      "platform": {**_S, "description": "e.g. claude-code, codex, chatgpt, gemini-cli, grok"}},
                     "required": ["query"]}},
    {"name": "brain_read",
     "description": "Read a conversation or note by vault path, 10-char conversation id, or note title. Paginate with offset.",
     "inputSchema": {"type": "object", "properties": {"ref": _S, "offset": _I, "max_chars": _I}, "required": ["ref"]}},
    {"name": "brain_recent",
     "description": "List recent conversations across platforms.",
     "inputSchema": {"type": "object", "properties": {"days": _I, "platform": _S, "limit": _I}}},
    {"name": "brain_save_note",
     "description": "Create or update a knowledge note. folder: Projects | Decisions | Concepts | People | Daily. "
                    "Follow the AI-first rules: frontmatter is added for you; start content with '## For future agent'. "
                    "mode=overwrite rewrites the note (preferred when facts changed), mode=append adds a dated update.",
     "inputSchema": {"type": "object", "properties": {"folder": _S, "title": _S, "content": _S, "tags": _L,
                                                      "sources": {**_L, "description": "[[conversation]] links this came from"},
                                                      "mode": {"type": "string", "enum": ["overwrite", "append"]}},
                     "required": ["folder", "title", "content"]}},
    {"name": "brain_save_conversation",
     "description": "Save the current chat into the second brain. Use on platforms that don't keep local logs "
                    "(Grok Bot, web apps) when the user says 'save this' or at the end of a meaningful session. "
                    "Re-saving with the same session_id updates the same note.",
     "inputSchema": {"type": "object", "properties": {
         "platform": {**_S, "description": "grok-bot, grok, claude, chatgpt, gemini, cursor, ..."},
         "title": _S, "session_id": _S, "model": _S, "project": _S,
         "messages": {"type": "array", "items": {"type": "object", "properties": {
             "role": {"type": "string", "enum": ["user", "assistant"]}, "content": _S, "timestamp": _S},
             "required": ["role", "content"]}}},
         "required": ["platform", "title", "messages"]}},
    {"name": "brain_remember",
     "description": "Store one durable fact about the user (where=facts → CRITICAL_FACTS) or a current focus item (where=focus → hot.md).",
     "inputSchema": {"type": "object", "properties": {"fact": _S, "where": {"type": "string", "enum": ["facts", "focus"]}},
                     "required": ["fact"]}},
    {"name": "brain_set_summary",
     "description": "After reading a conversation, record its 2-5 sentence summary, topics and linked projects. Marks it distilled.",
     "inputSchema": {"type": "object", "properties": {"ref": _S, "summary": _S, "topics": _L, "projects": _L},
                     "required": ["ref", "summary"]}},
    {"name": "brain_distill_queue",
     "description": "List conversations not yet distilled into knowledge, newest first.",
     "inputSchema": {"type": "object", "properties": {"limit": _I, "platform": _S}}},
    {"name": "brain_sync",
     "description": "Import new local chat logs (Claude Code, Codex, Gemini CLI) and inbox exports, then reindex.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def call_tool(vault: Vault, name: str, a: dict) -> str:
    if name == "brain_context":
        return build_context(vault, a.get("query"), int(a.get("budget_tokens") or 4000))
    if name == "brain_search":
        return ops.fmt_hits(ops.search(vault, a["query"], int(a.get("limit") or 10), a.get("platform")))
    if name == "brain_read":
        return ops.read(vault, a["ref"], int(a.get("max_chars") or 30000), int(a.get("offset") or 0))
    if name == "brain_recent":
        rows = ops.recent(vault, int(a.get("days") or 7), a.get("platform"), int(a.get("limit") or 30))
        return "\n".join(f"- {r['updated'][:10]} [{r['platform']}] {r['title']} - `{r['path']}`"
                         + (f"\n  {r['summary']}" if r.get("summary") else "") for r in rows) or "Nothing recent."
    if name == "brain_save_note":
        return "Saved " + ops.save_note(vault, a["folder"], a["title"], a["content"], a.get("tags"),
                                        a.get("sources"), a.get("mode") or "overwrite")
    if name == "brain_save_conversation":
        return "Saved " + ops.save_conversation(vault, a["platform"], a["title"], a["messages"], a.get("session_id"),
                                                a.get("model"), a.get("project"))
    if name == "brain_remember":
        return "Remembered in " + ops.remember(vault, a["fact"], a.get("where") or "facts")
    if name == "brain_set_summary":
        return "Updated " + ops.set_summary(vault, a["ref"], a["summary"], a.get("topics"), a.get("projects"))
    if name == "brain_distill_queue":
        rows = ops.distill_queue(vault, int(a.get("limit") or 20), a.get("platform"))
        return "\n".join(f"- `{r['path']}` ({r['platform']}, {r['messages']} msgs)" for r in rows) or "Queue empty."
    if name == "brain_sync":
        return json.dumps(ops.sync(vault, commit=True), indent=1)
    raise KeyError(f"unknown tool {name}")


def handle(vault: Vault, req: dict) -> dict | None:
    method, rid = req.get("method"), req.get("id")
    if rid is None:  # notification
        return None
    try:
        if method == "initialize":
            asked = (req.get("params") or {}).get("protocolVersion")
            result = {"protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "second-brain", "version": __version__},
                      "instructions": "The user's cross-platform second brain. Call brain_context at the start of "
                                      "substantial work; brain_search before asking the user to repeat context."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = req.get("params") or {}
            try:
                text = call_tool(vault, p.get("name"), p.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}]}
            except Exception as e:  # tool errors are results, not protocol errors
                result = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        elif method in ("resources/list", "prompts/list"):
            result = {method.split("/")[0]: []}
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}}


def serve(vault: Vault) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            resp = handle(vault, req) if isinstance(req, dict) else None
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
