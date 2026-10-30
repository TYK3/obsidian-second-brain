"""Web-reachable MCP server (Streamable HTTP transport) so claude.ai, ChatGPT and other
web apps can use the brain as a custom connector.

Auth: web connector UIs can't send custom headers, so the endpoint lives at a secret URL
(/mcp/<token>). CLI clients may instead send `Authorization: Bearer <token>` to /mcp.
"""
from __future__ import annotations

import hmac
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .mcp_server import TOOLS, handle
from .vault import Vault

WRITE_TOOLS = {"brain_save_note", "brain_save_conversation", "brain_remember", "brain_set_summary", "brain_sync"}
MAX_BODY = 8 * 1024 * 1024


def get_token(rotate: bool = False) -> str:
    cfg = config.load()
    if rotate or not cfg.get("http_token"):
        cfg["http_token"] = secrets.token_urlsafe(32)
        config.save(cfg)
    return cfg["http_token"]


class BrainHTTP:
    def __init__(self, vault: Vault, token: str, read_only: bool = False):
        self.vault, self.token, self.read_only = vault, token, read_only
        self.lock = threading.Lock()  # vault writes and git are not concurrency-safe

    def authorized(self, path: str, auth_header: str | None) -> bool:
        path = path.split("?", 1)[0].rstrip("/")
        if path.startswith("/mcp/"):
            return hmac.compare_digest(path[len("/mcp/"):], self.token)
        if path == "/mcp" and auth_header and auth_header.startswith("Bearer "):
            return hmac.compare_digest(auth_header[7:].strip(), self.token)
        return False

    def dispatch(self, req: dict) -> dict | None:
        method = req.get("method")
        if self.read_only:
            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": req.get("id"),
                        "result": {"tools": [t for t in TOOLS if t["name"] not in WRITE_TOOLS]}}
            if method == "tools/call" and (req.get("params") or {}).get("name") in WRITE_TOOLS:
                return {"jsonrpc": "2.0", "id": req.get("id"),
                        "result": {"content": [{"type": "text", "text": "Error: this brain is served read-only."}],
                                   "isError": True}}
        with self.lock:
            return handle(self.vault, req)

    def git_loop(self, minutes: float):
        """Cloud mode: keep the server's vault in step with the private vault repo."""
        from .search import Index
        while True:
            time.sleep(minutes * 60)
            with self.lock:
                try:
                    v = self.vault
                    if not (v.root / ".git").exists():
                        continue
                    v.commit("brain: web saves")
                    v.git("pull", "--rebase", "--autostash", "-q")
                    if v.git("remote").stdout.strip():
                        v.git("push", "-q")
                    idx = Index(v)
                    idx.refresh()
                    idx.close()
                    v.refresh_hot()
                except Exception as e:  # never let the sync loop kill the server
                    print(f"git sync failed: {e}", file=sys.stderr)


def make_handler(app: BrainHTTP):
    class Handler(BaseHTTPRequestHandler):
        server_version = "second-brain"

        def log_message(self, fmt, *args):  # never log the secret path
            sys.stderr.write(f"{self.address_string()} {self.command} {self.path.split('/mcp')[0] or '/'}... "
                             f"{args[1] if len(args) > 1 else ''}\n")

        def _send(self, code: int, body: dict | str | None = None, ctype: str = "application/json"):
            data = b"" if body is None else (json.dumps(body) if isinstance(body, dict) else body).encode()
            self.send_response(code)
            if data:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if self.authorized():
                # No server-initiated stream; clients fall back to plain POST request/response.
                return self._send(405, {"error": "use POST"})
            return self._send(404, {"error": "not found"})

        def do_DELETE(self):
            return self._send(204 if self.authorized() else 404)

        def authorized(self) -> bool:
            return app.authorized(self.path, self.headers.get("Authorization"))

        def do_POST(self):
            if not self.authorized():
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"error": "too large"})
            try:
                payload = json.loads(self.rfile.read(length) or b"null")
            except ValueError:
                return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            if isinstance(payload, list):
                out = [r for r in (app.dispatch(x) for x in payload if isinstance(x, dict)) if r]
                return self._send(200, json.dumps(out)) if out else self._send(202)
            if not isinstance(payload, dict):
                return self._send(400, {"error": "expected JSON-RPC object"})
            resp = app.dispatch(payload)
            return self._send(200, resp) if resp else self._send(202)

    return Handler


def serve_http(vault: Vault, host: str, port: int, token: str, read_only: bool = False,
               git_sync_minutes: float = 0, announce_token: bool = True) -> None:
    app = BrainHTTP(vault, token, read_only)
    if git_sync_minutes > 0:
        threading.Thread(target=app.git_loop, args=(git_sync_minutes,), daemon=True).start()
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"Second brain MCP server on http://{host}:{port}  ({'read-only' if read_only else 'read/write'})",
          file=sys.stderr)
    if announce_token:  # skipped in cloud mode, where stderr ends up in hosted logs
        print(f"Connector path: /mcp/{token}", file=sys.stderr)
        print("Put your public URL in front of that path, e.g. https://<your-tunnel>/mcp/<token>", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
