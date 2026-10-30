import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from secondbrain import ops
from secondbrain.importers import import_path
from secondbrain.mcp_server import handle
from secondbrain.redact import redact
from secondbrain.vault import Vault


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data)
    elif path.suffix == ".jsonl":
        path.write_text("\n".join(json.dumps(x) for x in data))
    else:
        path.write_text(json.dumps(data))
    return path


@pytest.fixture
def vault(tmp_path, monkeypatch):
    from secondbrain import config
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    # CONFIG_FILE is resolved at import, so the env var alone never reaches it.
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "cfg" / "second-brain" / "config.json")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # keep sync away from the real ~/.claude etc.
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Windows reads ~ from here, not HOME
    monkeypatch.setenv("OSB_SKILL_DIR", str(Path(__file__).resolve().parents[3]))  # this checkout's server.py
    v = Vault(tmp_path / "brain")
    v.init(git=False)
    return v


# ------------------------------------------------------------------ fixtures per platform
def claude_code_file(d: Path) -> Path:
    sid = "11111111-aaaa"
    return write(d / "proj" / f"{sid}.jsonl", [
        {"type": "user", "sessionId": sid, "cwd": "/w/app", "timestamp": "2026-10-01T10:00:00Z", "parentUuid": None,
         "message": {"role": "user", "content": "<system-reminder>noise</system-reminder>Set up Postgres for the app"}},
        {"type": "assistant", "sessionId": sid, "timestamp": "2026-10-01T10:00:05Z",
         "message": {"model": "claude-opus-5-5", "content": [{"type": "thinking", "thinking": "secret thoughts"},
                                                            {"type": "text", "text": "I'll use Postgres 17."}]}},
        {"type": "assistant", "sessionId": sid, "timestamp": "2026-10-01T10:00:06Z",
         "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "docker run postgres"}}]}},
        {"type": "user", "sessionId": sid, "timestamp": "2026-10-01T10:00:07Z",
         "message": {"content": [{"type": "tool_result", "content": "big output"}]}},
        {"type": "attachment", "sessionId": sid, "timestamp": "2026-10-01T10:00:08Z",
         "attachment": {"type": "queued_command", "prompt": "use port 5433", "humanTurn": True}},
        {"type": "assistant", "sessionId": sid, "timestamp": "2026-10-01T10:00:09Z",
         "message": {"content": [{"type": "text", "text": "Done, port 5433."}]}},
    ])


def codex_file(d: Path) -> Path:
    return write(d / "2026" / "10" / "02" / "rollout-2026-10-02T09-00-00-abc.jsonl", [
        {"timestamp": "2026-10-02T09:00:00Z", "type": "session_meta", "payload": {"id": "codex-1", "cwd": "/w/api"}},
        {"timestamp": "2026-10-02T09:00:00Z", "type": "turn_context", "payload": {"model": "gpt-5-codex"}},
        {"timestamp": "2026-10-02T09:00:01Z", "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
        {"timestamp": "2026-10-02T09:00:02Z", "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "Add rate limiting to the API"}]}},
        {"timestamp": "2026-10-02T09:00:03Z", "type": "response_item", "payload": {
            "type": "function_call", "name": "shell", "arguments": json.dumps({"command": ["rg", "limiter"]})}},
        {"timestamp": "2026-10-02T09:00:04Z", "type": "response_item", "payload": {
            "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Added a token bucket limiter."}]}},
    ])


def gemini_cli_file(d: Path) -> Path:
    return write(d / "hash123" / "chats" / "session-2026-10-03T08-00-g1.json", {
        "sessionId": "g1", "projectHash": "hash123", "startTime": "2026-10-03T08:00:00Z",
        "lastUpdated": "2026-10-03T08:05:00Z",
        "messages": [
            {"id": "1", "timestamp": "2026-10-03T08:00:00Z", "type": "user", "content": "Explain vector clocks"},
            {"id": "2", "timestamp": "2026-10-03T08:00:10Z", "type": "gemini", "content": "Vector clocks track causality.",
             "model": "gemini-3-pro", "toolCalls": [{"name": "google_web_search", "args": {"query": "vector clocks"}}]},
        ]})


def chatgpt_file(d: Path) -> Path:
    return write(d / "conversations.json", [{
        "title": "Trip to Japan", "conversation_id": "cg1", "create_time": 1759300000.0, "update_time": 1759300100.0,
        "current_node": "c", "default_model_slug": "gpt-5",
        "mapping": {
            "root": {"message": None, "parent": None},
            "s": {"message": {"author": {"role": "system"}, "content": {"content_type": "text", "parts": [""]}}, "parent": "root"},
            "a": {"message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["Plan 5 days in Kyoto"]},
                              "create_time": 1759300000.0}, "parent": "s"},
            "b_old": {"message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["old branch"]}}, "parent": "a"},
            "c": {"message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["Day 1: Fushimi Inari"]},
                              "create_time": 1759300050.0, "metadata": {"model_slug": "gpt-5"}}, "parent": "a"},
        }}])


def claude_web_file(d: Path) -> Path:
    return write(d / "claude-export" / "conversations.json", [{
        "uuid": "cw1", "name": "Pricing strategy", "created_at": "2026-09-01T12:00:00Z", "updated_at": "2026-09-01T12:10:00Z",
        "chat_messages": [
            {"sender": "human", "text": "How should I price my SaaS?", "created_at": "2026-09-01T12:00:00Z", "content": []},
            {"sender": "assistant", "text": "", "created_at": "2026-09-01T12:00:30Z",
             "content": [{"type": "text", "text": "Start with value-based tiers."}]},
        ]}])


def grok_file(d: Path) -> Path:
    return write(d / "grok" / "prod-grok-backend.json", {"conversations": [{
        "conversation": {"id": "gk1", "title": "X growth ideas", "create_time": "2026-08-01T10:00:00Z"},
        "responses": [
            {"response": {"_id": "2", "message": "Post daily threads.", "sender": "ASSISTANT",
                          "create_time": {"$date": {"$numberLong": "1754042460000"}}, "model": "grok-4"}},
            {"response": {"_id": "1", "message": "How do I grow on X?", "sender": "human",
                          "create_time": {"$date": {"$numberLong": "1754042400000"}}}},
        ]}]})


def gemini_takeout_file(d: Path) -> Path:
    return write(d / "Takeout" / "My Activity" / "Gemini Apps" / "MyActivity.json", [
        {"header": "Gemini Apps", "title": "Prompted What is RLHF?", "time": "2026-07-01T09:00:00.123Z",
         "safeHtmlItem": [{"html": "<p>RLHF is <b>reinforcement learning</b> from human feedback.</p>"}]},
        {"header": "Gemini Apps", "title": "Used Gemini Apps", "time": "2026-07-01T09:01:00Z"},
    ])


@pytest.mark.parametrize("maker,platform,expect", [
    (claude_code_file, "claude-code", ["Set up Postgres", "Postgres 17", "docker run postgres", "use port 5433"]),
    (codex_file, "codex", ["rate limiting", "token bucket", "rg limiter"]),
    (gemini_cli_file, "gemini-cli", ["vector clocks", "causality", "google_web_search"]),
    (chatgpt_file, "chatgpt", ["Kyoto", "Fushimi"]),
    (claude_web_file, "claude", ["price my SaaS", "value-based"]),
    (grok_file, "grok", ["grow on X", "daily threads"]),
    (gemini_takeout_file, "gemini", ["RLHF", "reinforcement learning"]),
])
def test_importers(tmp_path, maker, platform, expect):
    f = maker(tmp_path / "src")
    convs = list(import_path(f))
    assert len(convs) == 1, f"{platform}: {convs}"
    c = convs[0]
    assert c.platform == platform
    text = "\n".join(m.text for m in c.messages)
    for e in expect:
        assert e in text
    assert c.messages[0].role == "user"
    assert "noise" not in text and "secret thoughts" not in text and "big output" not in text
    assert "environment_context" not in text and "old branch" not in text


def test_claude_code_turns(tmp_path):
    c = next(import_path(claude_code_file(tmp_path)))
    assert [m.role for m in c.messages] == ["user", "assistant", "user", "assistant"]
    assert c.project == "/w/app" and c.model == "claude-opus-5-5"


def test_zip_and_folder_detection(tmp_path):
    chatgpt_file(tmp_path / "x")
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(tmp_path / "x" / "conversations.json", "conversations.json")
    assert [c.platform for c in import_path(z)] == ["chatgpt"]
    grok_file(tmp_path / "mixed")
    claude_web_file(tmp_path / "mixed")
    assert sorted(c.platform for c in import_path(tmp_path / "mixed")) == ["claude", "grok"]


def test_generic_transcript(tmp_path):
    f = write(tmp_path / "grokbot-chat.md", "User: what's my deploy target?\nGrok: Fly.io, per last week.\nUser: thanks")
    c = next(import_path(f, platform="grok-bot"))
    assert c.platform == "grok-bot" and [m.role for m in c.messages] == ["user", "assistant", "user"]


def test_redaction():
    s = redact("key sk-ant-api03-abcdefghijklmnopqrstuvwxyz and OPENAI_API_KEY=abc123456789 ghp_" + "a" * 36)
    assert "abcdefghijklmnop" not in s and "abc123456789" not in s and "ghp_aaaa" not in s
    assert s.count("[REDACTED]") == 3


# ------------------------------------------------------------------ vault behaviour
def test_write_resync_preserves_summary(vault, tmp_path):
    src = claude_code_file(tmp_path / "src")
    assert ops.import_source(vault, src)["new"] == 1
    assert ops.import_source(vault, src)["unchanged"] == 1
    path = next(vault.iter_conversations())
    ops.set_summary(vault, str(path.relative_to(vault.root)), "Set up Postgres 17 on port 5433.", ["postgres"], ["App"])
    # conversation grows → transcript regenerated, summary kept
    lines = src.read_text().splitlines()
    lines.append(json.dumps({"type": "user", "sessionId": "11111111-aaaa", "timestamp": "2026-10-02T10:00:00Z",
                             "message": {"content": "now add backups"}}))
    src.write_text("\n".join(lines))
    assert ops.import_source(vault, src)["updated"] == 1
    fm, msgs = vault.read_conversation(path)
    assert fm["distilled"] is True and fm["summary"].startswith("Set up Postgres")
    assert fm["topics"] == ["postgres"] and msgs[-1].text == "now add backups"
    assert "Set up Postgres 17 on port 5433." in path.read_text().split("brain:transcript")[0]


def test_search_context_and_notes(vault, tmp_path):
    for mk in (codex_file, chatgpt_file, grok_file):
        ops.import_source(vault, mk(tmp_path / mk.__name__))
    hits = ops.search(vault, "rate limiting")
    assert hits and hits[0]["platform"] == "codex"
    assert ops.search(vault, "Kyoto", platform="grok") == []
    ops.save_note(vault, "Projects", "API", "## For future agent\nThe API project.\n\nUses a token bucket limiter.")
    ops.remember(vault, "Prefers Postgres over MySQL")
    from secondbrain.context import build_context
    ctx = build_context(vault, "limiter")
    assert "Prefers Postgres" in ctx and "API" in ctx and "rate limiting" in ctx.lower()
    assert ops.search(vault, "token bucket")[0]["path"] in ("Projects/API.md",) or any(
        h["path"] == "Projects/API.md" for h in ops.search(vault, "token bucket"))


def test_save_conversation_and_safety(vault):
    rel = ops.save_conversation(vault, "grok-bot", "Launch plan",
                                [{"role": "user", "content": "plan the launch"}, {"role": "assistant", "content": "Step 1"}],
                                session_id="s1")
    assert rel.startswith("Conversations/grok-bot/")
    rel2 = ops.save_conversation(vault, "grok-bot", "Launch plan",
                                 [{"role": "user", "content": "plan the launch"}, {"role": "assistant", "content": "Step 1"},
                                  {"role": "user", "content": "and step 2?"}], session_id="s1")
    assert rel == rel2
    with pytest.raises(ValueError):
        ops.save_note(vault, "../../etc", "x", "y")
    with pytest.raises((ValueError, FileNotFoundError)):
        ops.read(vault, "../../../etc/passwd")


def test_sync_inbox_dedup(vault, tmp_path):
    chatgpt_file(vault.root / "inbox")
    r1 = ops.sync(vault, only=None, commit=False)
    assert r1["new"] == 1
    r2 = ops.sync(vault, only=None, commit=False)
    assert r2["new"] == 0 and r2["updated"] == 0


def test_lint(vault):
    ops.save_note(vault, "Concepts", "Orphan idea", "no preamble, links to [[Nowhere]]")
    from secondbrain.lint import lint
    r = lint(vault)
    assert ("Concepts/Orphan idea.md", "Nowhere") in r["broken"]
    assert "Concepts/Orphan idea.md" in r["orphans"] and "Concepts/Orphan idea.md" in r["no_preamble"]


# ------------------------------------------------------------------ MCP
def test_mcp_protocol(vault, tmp_path):
    ops.import_source(vault, codex_file(tmp_path / "c"))
    init = handle(vault, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert handle(vault, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = handle(vault, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {"brain_context", "brain_search", "brain_save_conversation"} <= {t["name"] for t in tools}
    r = handle(vault, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "brain_search", "arguments": {"query": "rate limiting"}}})
    assert "rate limiting" in r["result"]["content"][0]["text"].lower()
    bad = handle(vault, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "brain_read", "arguments": {"ref": "nope"}}})
    assert bad["result"]["isError"] is True


def test_mcp_stdio_end_to_end(vault):
    reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "brain_context", "arguments": {}}}]
    out = subprocess.run([sys.executable, "-m", "secondbrain", "--vault", str(vault.root), "mcp"],
                         input="\n".join(json.dumps(r) for r in reqs) + "\n", capture_output=True, text=True, timeout=30)
    lines = [json.loads(l) for l in out.stdout.splitlines()]
    assert [l["id"] for l in lines] == [1, 2]
    assert "Context from my second brain" in lines[1]["result"]["content"][0]["text"]


def test_installer_dry_and_real(vault, tmp_path, monkeypatch):
    from secondbrain import install
    monkeypatch.setattr(install, "HOME", tmp_path / "home")
    (tmp_path / "home" / ".codex").mkdir(parents=True)
    (tmp_path / "home" / ".codex" / "config.toml").write_text('model = "gpt-5"\n')
    rep = install.Installer(vault.root, dry_run=True).run(["claude-code", "codex", "gemini"])
    assert all(r.startswith("[dry-run]") for r in rep)
    assert not (tmp_path / "home" / ".claude.json").exists()
    home = tmp_path / "home"
    # A pre-merge install: old server, old skill, old session-start hook, plus an unrelated hook.
    (home / ".claude" / "skills" / "brain-recall").mkdir(parents=True)
    (home / ".claude" / "skills" / "brain-recall" / "SKILL.md").write_text("old")
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"second-brain": {}, "other": {}}}))
    old_hook = {"hooks": [{"type": "command", "command": "python -m secondbrain hook session-start"}]}
    mine = {"hooks": [{"type": "command", "command": "echo mine"}]}
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [old_hook, mine]}}))
    (home / ".codex" / "config.toml").write_text('model = "gpt-5"\n\n[mcp_servers.second-brain]\ncommand = "x"\n')
    install.Installer(vault.root).run(["claude-code", "codex", "gemini"])
    install.Installer(vault.root).run(["claude-code", "codex", "gemini"])  # idempotent
    servers = json.loads((home / ".claude.json").read_text())["mcpServers"]
    assert "second-brain" not in servers and "other" in servers
    assert servers["obsidian-second-brain"]["args"][-1].endswith("server.py")
    assert servers["obsidian-second-brain"]["env"] == {"OBSIDIAN_VAULT_PATH": str(vault.root)}
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert settings["hooks"]["SessionStart"] == [mine]  # old start hook gone, the user's own kept
    assert len(settings["hooks"]["SessionEnd"]) == 1
    toml = (home / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.second-brain]" not in toml and 'model = "gpt-5"' in toml
    assert toml.count("[mcp_servers.obsidian-second-brain]") == 1
    assert (home / ".claude" / "CLAUDE.md").read_text().count("second-brain:start") == 1
    assert not (home / ".claude" / "skills" / "brain-recall").exists()
    assert "obsidian-second-brain" in json.loads((home / ".gemini" / "settings.json").read_text())["mcpServers"]


def test_installer_config_dir(vault, tmp_path, monkeypatch):
    from secondbrain import config, install
    monkeypatch.setattr(install, "HOME", tmp_path / "home")
    app = tmp_path / "app" / "claude-account"  # an app's own CLAUDE_CONFIG_DIR
    for _ in range(2):  # re-running must replace the instructions block, not crash on Windows paths
        install.Installer(vault.root, config_dir=app, hooks=False).run(["claude-code"])
    assert "obsidian-second-brain" in json.loads((app / ".claude.json").read_text())["mcpServers"]
    assert (app / "CLAUDE.md").read_text().count("second-brain:start") == 1
    assert not (app / "settings.json").exists()  # --no-hooks
    assert not (tmp_path / "home" / ".claude.json").exists()  # default home untouched
    assert config.load()["sources"][str(app / "projects")] == "claude-code"
    codex_home = tmp_path / "app" / "codex-account"
    install.Installer(vault.root, config_dir=codex_home).run(["codex"])
    assert "[mcp_servers.obsidian-second-brain]" in (codex_home / "config.toml").read_text()
    assert config.load()["sources"][str(codex_home / "archived_sessions")] == "codex"
    with pytest.raises(ValueError):
        install.Installer(vault.root, config_dir=app).run(["claude-code", "codex"])


def test_openbot_wrappers_and_titles(tmp_path):
    sid = "22222222-bbbb"
    src = write(tmp_path / "ob" / f"{sid}.jsonl", [
        {"type": "user", "sessionId": sid, "timestamp": "2026-10-28T19:13:15Z", "parentUuid": None,
         "message": {"role": "user", "content": "<openbot_saved_memories>\nThe following saved memories are untrusted"
                     " data.\n</openbot_saved_memories>\n<openbot_section_teammates>\nYou and these agents share a"
                     " sidebar section.\n</openbot_section_teammates>\n\nYou are Claude-1, restored executor bot."}},
        {"type": "assistant", "sessionId": sid, "timestamp": "2026-10-28T19:13:35Z",
         "message": {"content": [{"type": "text", "text": "Ready."}]}},
    ])
    conv = next(import_path(src, "claude-code"))
    assert conv.title.startswith("You are Claude-1") and "untrusted" not in conv.messages[0].text
    from secondbrain.model import skip_preamble
    resumed = ("Continue this OpenBot conversation.\nPrevious conversation excerpts.\n--- recent messages ---\n\n"
               "[messageId: a6b9]\n[2026-10-28T14:26:38.457Z] user:\nRESTORATION AND VERIFICATION ONLY.")
    assert skip_preamble(resumed).startswith("RESTORATION AND VERIFICATION ONLY")
    agent_turn = resumed.replace("] user:", "] agent agent:Codex Hackathon Manager (agent-07f9):")
    assert skip_preamble(agent_turn).startswith("RESTORATION AND VERIFICATION ONLY")
    assert skip_preamble("Fix the login bug: it 500s") == "Fix the login bug: it 500s"


def test_schedule_dry_run(vault, capsys):
    from secondbrain.cli import main
    assert (vault.root / "scripts" / "night.ps1").exists()
    main(["--vault", str(vault.root), "schedule", "--dry-run", "--time", "03:15"])
    out = capsys.readouterr().out
    assert ("schtasks" in out and "03:15" in out and "night.ps1" in out) or "15 3 * * *" in out


# ------------------------------------------------------------------ web (HTTP) MCP
def _http_server(vault, read_only=False):
    import threading
    from http.server import ThreadingHTTPServer

    from secondbrain.http_server import BrainHTTP, make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BrainHTTP(vault, "t" * 32, read_only)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _post(url, body, headers=None):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read()
            return r.status, json.loads(data) if data else None
    except urllib.error.HTTPError as e:
        return e.code, None


def test_http_auth_and_tools(vault, tmp_path):
    ops.import_source(vault, codex_file(tmp_path / "c"))
    srv, base = _http_server(vault)
    try:
        url = f"{base}/mcp/{'t' * 32}"
        code, r = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert code == 200 and r["result"]["serverInfo"]["name"] == "second-brain"
        assert _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202
        code, r = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "brain_search", "arguments": {"query": "rate limiting"}}})
        assert "rate limiting" in r["result"]["content"][0]["text"].lower()
        assert _post(f"{base}/mcp/{'x' * 32}", {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 404
        assert _post(f"{base}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 404
        assert _post(f"{base}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                     {"Authorization": "Bearer " + "t" * 32})[0] == 200
        code, r = _post(url, [{"jsonrpc": "2.0", "id": 5, "method": "ping"}, {"jsonrpc": "2.0", "id": 6, "method": "ping"}])
        assert [x["id"] for x in r] == [5, 6]
    finally:
        srv.shutdown()


def test_http_read_only(vault):
    srv, base = _http_server(vault, read_only=True)
    try:
        url = f"{base}/mcp/{'t' * 32}"
        _, r = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in r["result"]["tools"]}
        assert "brain_search" in names and "brain_save_note" not in names
        _, r = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "brain_save_note", "arguments": {"folder": "Concepts", "title": "x", "content": "y"}}})
        assert r["result"]["isError"] and not (vault.root / "Concepts" / "x.md").exists()
    finally:
        srv.shutdown()
