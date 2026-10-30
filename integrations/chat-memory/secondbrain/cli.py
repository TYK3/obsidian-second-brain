"""`brain` command line."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__, config, ops
from .context import build_context
from .importers import BY_NAME, LOCAL
from .install import TARGETS, Installer, generic_snippet
from .lint import lint
from .search import Index
from .vault import Vault


def _vault(args, must_exist: bool = True) -> Vault:
    v = Vault(config.vault_path(getattr(args, "vault", None)))
    if must_exist and not v.exists():
        sys.exit(f"No vault at {v.root}. Run `brain init` first (or pass --vault / set SECOND_BRAIN_VAULT).")
    return v


def cmd_init(a):
    v = _vault(a, must_exist=False)
    created = v.init(git=not a.no_git)
    cfg = config.load()
    cfg["vault"] = str(v.root)
    config.save(cfg)
    print(f"Vault ready at {v.root}")
    for c in created:
        print(f"  + {c}")
    print(f"Config saved to {config.CONFIG_FILE}\n\nNext:\n  brain sync          # import local Claude Code / Codex / Gemini CLI history"
          "\n  brain install       # connect Claude Code, Codex, Gemini CLI, Claude Desktop, Cursor"
          "\n  brain import <export.zip|folder|file>   # ChatGPT / Claude.ai / Grok / Gemini exports")


def cmd_sync(a):
    v = _vault(a)
    r = ops.sync(v, only=a.only, commit=not a.no_commit, push=a.push or None)
    if a.quiet:
        return
    print(f"Scanned: {', '.join(r['scanned']) or '(no local sources found)'}")
    print(f"New: {r['new']}  Updated: {r['updated']}  Unchanged: {r['unchanged']}")
    for k, n in sorted(r["by_platform"].items()):
        print(f"  {k}: {n}")
    print(f"Index: {r['index']}   Git: {r['git']}")


def cmd_import(a):
    v = _vault(a)
    total = {}
    for p in a.paths:
        c = ops.import_source(v, Path(p), a.format, a.platform, tools=not a.no_tools)
        for k, n in c.items():
            total[k] = total.get(k, 0) + n
    idx = Index(v)
    idx.refresh()
    idx.close()
    v.refresh_hot()
    v.refresh_index()
    changed = {k: n for k, n in total.items() if ":" in k}
    if changed:
        v.log("import", "\n".join(f"- {k.replace(':', ' ')}: {n}" for k, n in sorted(changed.items()))
              + "\n- from: " + ", ".join(a.paths))
    if not a.no_commit:
        v.commit("brain import: " + ", ".join(Path(p).name for p in a.paths))
    print(f"New: {total.get('new', 0)}  Updated: {total.get('updated', 0)}  Unchanged: {total.get('unchanged', 0)}")
    for k, n in sorted(changed.items()):
        print(f"  {k}: {n}")
    if not total:
        print("Nothing recognised. Try --format (one of: " + ", ".join(BY_NAME) + ")")


def cmd_search(a):
    hits = ops.search(_vault(a), " ".join(a.query), a.limit, a.platform)
    if a.json:
        print(json.dumps(hits, indent=1))
    else:
        print(ops.fmt_hits(hits))


def cmd_show(a):
    print(ops.read(_vault(a), a.ref, a.max_chars, a.offset))


def cmd_recent(a):
    for r in ops.recent(_vault(a), a.days, a.platform, a.limit):
        print(f"{r['updated'][:10]}  {r['platform']:<12} {r['title']}\n            {r['path']}")


def cmd_context(a):
    v = _vault(a)
    text = build_context(v, " ".join(a.query) if a.query else None, a.budget)
    if a.out:
        out = v.safe_path(a.out) if not Path(a.out).is_absolute() else Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)
    if a.copy:
        for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["clip"]):
            try:
                subprocess.run(cmd, input=text, text=True, check=True)
                print("Copied to clipboard.", file=sys.stderr)
                break
            except (OSError, subprocess.CalledProcessError):
                continue
    if not a.out or a.print:
        print(text)


def cmd_distill(a):
    rows = ops.distill_queue(_vault(a), a.limit, a.platform)
    if not rows:
        print("Everything is distilled.")
        return
    print(f"{len(rows)} conversation(s) waiting. Run /obsidian-chat-digest in your agent, or:\n"
          '  claude -p "Follow /obsidian-chat-digest for 10 conversations" --model opus\n')
    for r in rows:
        print(f"  {str(r['updated'])[:10]}  {r['platform']:<12} {r['messages']:>4} msgs  {r['path']}")


def cmd_summary(a):
    print(ops.set_summary(_vault(a), a.ref, a.summary, a.topics, a.projects))


def cmd_note(a):
    content = sys.stdin.read() if a.content == "-" else a.content
    print(ops.save_note(_vault(a), a.folder, a.title, content, a.tags, mode=a.mode))


def cmd_remember(a):
    print(ops.remember(_vault(a), " ".join(a.fact), a.where))


def cmd_save(a):
    """Save a chat from a JSON/markdown file or stdin (for platforms without local logs)."""
    v = _vault(a)
    if a.file == "-":
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
            msgs = data["messages"] if isinstance(data, dict) else data
        except (ValueError, KeyError, TypeError):
            msgs = [{"role": "user", "content": raw}]
        print(ops.save_conversation(v, a.platform, a.title or "Saved chat", msgs, a.session_id))
    else:
        c = ops.import_source(v, Path(a.file), None, a.platform)
        print(dict(c))


def cmd_lint(a):
    v = _vault(a)
    report = lint(v)
    if a.out:
        path = v.root / "reports" / f"{report['date']}-mechanical.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(report["markdown"], encoding="utf-8")
        print(f"Wrote {path.relative_to(v.root)}")
    else:
        print(report["markdown"])


def cmd_stats(a):
    v = _vault(a)
    idx = Index(v)
    idx.refresh()
    s = idx.stats()
    idx.close()
    print(f"Vault: {v.root}")
    for k, n in sorted(s.items()):
        print(f"  {k:<28} {n}")
    print(f"  {'undistilled':<28} {len(ops.distill_queue(v, 10**6))}")


def cmd_reindex(a):
    idx = Index(_vault(a))
    print(idx.refresh(full=True))
    idx.close()


def cmd_mcp(a):
    from .mcp_server import serve
    serve(_vault(a))


def cmd_serve(a):
    from .http_server import get_token, serve_http
    v = _vault(a)
    token = os.environ.get("SECOND_BRAIN_TOKEN") or get_token(rotate=a.new_token)
    if len(token) < 24:
        sys.exit("SECOND_BRAIN_TOKEN must be at least 24 characters.")
    if a.show_url:
        print(f"/mcp/{token}")
        return
    serve_http(v, a.host, a.port, token, read_only=a.read_only, git_sync_minutes=a.git_sync,
               announce_token="SECOND_BRAIN_TOKEN" not in os.environ)


def cmd_install(a):
    v = _vault(a)
    targets = a.targets or TARGETS
    try:
        report = Installer(v.root, dry_run=a.dry_run, config_dir=a.config_dir, hooks=not a.no_hooks).run(targets)
    except ValueError as e:
        sys.exit(str(e))
    for line in report:
        print(line)
    print("\nGrok Bot / any other MCP client - add this server config:\n" + generic_snippet(v.root))
    print("\nRestart each tool to pick up the change. Backups were saved as *.bak-second-brain.")


TASK_NAME = "SecondBrain Night Shift"


def cmd_schedule(a):
    """Run scripts/night.(ps1|sh) every night: Task Scheduler on Windows, a crontab line elsewhere."""
    v = _vault(a)
    if os.name == "nt":
        if a.remove:
            cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
        else:
            script = v.root / "scripts" / "night.ps1"
            if not script.exists():
                sys.exit(f"{script} is missing. Run `brain init` to add it.")
            run = f'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{script}"'
            cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "DAILY", "/ST", a.time, "/TR", run, "/F"]
        if a.dry_run:
            print(subprocess.list2cmdline(cmd))
            return
        sys.exit(subprocess.run(cmd).returncode)
    hh, mm = a.time.split(":")
    line = f"{int(mm)} {int(hh)} * * *  {v.root}/scripts/night.sh >> {v.root}/.brain/night.log 2>&1"
    print(f"Add this line with `crontab -e`{' (and remove it to unschedule)' if a.remove else ''}:\n  {line}")


def cmd_hook(a):
    """Called by Claude Code hooks. Must be fast and never fail loudly."""
    try:
        v = _vault(a)
    except SystemExit:
        return
    if a.event == "session-start":
        parts = []
        for rel, cap in (("_brain/CRITICAL_FACTS.md", 3000), ("_brain/hot.md", 3000)):
            p = v.root / rel
            if p.exists():
                parts.append(p.read_text(encoding="utf-8")[:cap])
        if parts:
            print("# Second brain (auto-loaded; use the obsidian_chat_search MCP tool for more)\n\n" + "\n\n".join(parts))
    elif a.event == "session-end":
        # Detach so the session closes instantly; the sync imports the session that just ended.
        subprocess.Popen([sys.executable, "-m", "secondbrain", "--vault", str(v.root), "sync", "--quiet",
                          "--only", "claude-code"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)


def main(argv=None):
    p = argparse.ArgumentParser(prog="brain", description="Second brain for all your AI chats.")
    p.add_argument("--vault", help="vault path (default: config / $SECOND_BRAIN_VAULT / ~/SecondBrain)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create the vault")
    s.add_argument("--no-git", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("sync", help="import local CLI history + inbox, reindex, commit")
    s.add_argument("--only", nargs="+", choices=[i.name for i in LOCAL])
    s.add_argument("--no-commit", action="store_true")
    s.add_argument("--push", action="store_true", help="git push after committing")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("import", help="import export files/folders/zips (auto-detected)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--format", choices=list(BY_NAME))
    s.add_argument("--platform", help="override platform label (e.g. grok-bot)")
    s.add_argument("--no-tools", action="store_true", help="drop tool-call lines from agent transcripts")
    s.add_argument("--no-commit", action="store_true")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("search", help="full-text search")
    s.add_argument("query", nargs="+")
    s.add_argument("-n", "--limit", type=int, default=10)
    s.add_argument("-p", "--platform")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("show", help="print a conversation/note (path, id, or title)")
    s.add_argument("ref")
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--max-chars", type=int, default=10**9)
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("recent", help="recent conversations")
    s.add_argument("-d", "--days", type=int, default=7)
    s.add_argument("-p", "--platform")
    s.add_argument("-n", "--limit", type=int, default=30)
    s.set_defaults(fn=cmd_recent)

    s = sub.add_parser("context", help="build a context pack to paste into any AI")
    s.add_argument("query", nargs="*")
    s.add_argument("-b", "--budget", type=int, default=4000, help="token budget")
    s.add_argument("-o", "--out", help="write to file (relative paths are inside the vault)")
    s.add_argument("--print", action="store_true", help="also print when --out is given")
    s.add_argument("-c", "--copy", action="store_true", help="copy to clipboard")
    s.set_defaults(fn=cmd_context)

    s = sub.add_parser("distill", help="list conversations waiting to be distilled")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.add_argument("-p", "--platform")
    s.set_defaults(fn=cmd_distill)

    s = sub.add_parser("summary", help="record a conversation summary (marks it distilled)")
    s.add_argument("ref")
    s.add_argument("summary")
    s.add_argument("--topics", nargs="*")
    s.add_argument("--projects", nargs="*")
    s.set_defaults(fn=cmd_summary)

    s = sub.add_parser("note", help="create/update a knowledge note")
    s.add_argument("folder", choices=["Projects", "Decisions", "Concepts", "People", "Daily"])
    s.add_argument("title")
    s.add_argument("content", help="markdown, or - for stdin")
    s.add_argument("--tags", nargs="*")
    s.add_argument("--mode", choices=["overwrite", "append"], default="append")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("remember", help="add a durable fact to CRITICAL_FACTS (or --focus to hot.md)")
    s.add_argument("fact", nargs="+")
    s.add_argument("--where", choices=["facts", "focus"], default="facts")
    s.set_defaults(fn=cmd_remember)

    s = sub.add_parser("save", help="save a chat from a file or stdin")
    s.add_argument("file", help="file path, or - for stdin (JSON messages or plain text)")
    s.add_argument("--platform", default="other")
    s.add_argument("--title")
    s.add_argument("--session-id")
    s.set_defaults(fn=cmd_save)

    s = sub.add_parser("lint", help="mechanical health check: broken links, orphans, stale/undistilled")
    s.add_argument("--out", action="store_true", help="write reports/YYYY-MM-DD-mechanical.md")
    s.set_defaults(fn=cmd_lint)

    sub.add_parser("stats", help="counts").set_defaults(fn=cmd_stats)
    sub.add_parser("reindex", help="rebuild the search index from scratch").set_defaults(fn=cmd_reindex)
    sub.add_parser("mcp", help="run the MCP server on stdio").set_defaults(fn=cmd_mcp)

    s = sub.add_parser("serve", help="web-reachable MCP server for claude.ai / ChatGPT connectors")
    s.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 on a cloud server")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--read-only", action="store_true", help="hide every tool that writes")
    s.add_argument("--git-sync", type=float, default=0, metavar="MIN",
                   help="every MIN minutes: commit web saves, git pull --rebase, push (cloud mode)")
    s.add_argument("--new-token", action="store_true", help="rotate the secret (old connector URLs stop working)")
    s.add_argument("--show-url", action="store_true", help="print the secret connector path and exit")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("install", help="connect AI tools (MCP + instructions + hooks)")
    s.add_argument("targets", nargs="*", choices=TARGETS + [[]], default=None)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--config-dir", metavar="PATH",
                   help="install into this config home instead of the default (an app's own CLAUDE_CONFIG_DIR / "
                        "CODEX_HOME / Gemini folder); needs exactly one target; also adds its history to `brain sync`")
    s.add_argument("--no-hooks", action="store_true",
                   help="skip the Claude Code session hooks (agents look things up on demand instead)")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("schedule", help="run the night shift every night (Task Scheduler / cron)")
    s.add_argument("--time", default="02:07", help="HH:MM, local time (default 02:07)")
    s.add_argument("--remove", action="store_true", help="unschedule")
    s.add_argument("--dry-run", action="store_true", help="print the command instead of running it")
    s.set_defaults(fn=cmd_schedule)

    s = sub.add_parser("hook", help=argparse.SUPPRESS)
    s.add_argument("event", choices=["session-start", "session-end"])
    s.set_defaults(fn=cmd_hook)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
