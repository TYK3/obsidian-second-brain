# Chat memory (the `brain` CLI)

> Part of the TYK3 fork of obsidian-second-brain. Its MCP tools are served by
> `integrations/obsidian-mcp-server/server.py` as `obsidian_context`, `obsidian_chat_search`,
> `obsidian_chat_read`, `obsidian_chat_recent`, `obsidian_save_conversation`, `obsidian_remember`,
> `obsidian_chat_digest_queue`, `obsidian_set_chat_summary` and `obsidian_chat_sync`, and its
> workflows are the `/obsidian-sync`, `/obsidian-recall`, `/obsidian-chat-digest` and
> `/obsidian-handoff` commands. The `brain_*` names below remain only on `brain mcp` and the
> `brain serve` web connector. Install the CLI with:
>
> `uv tool install "git+https://github.com/TYK3/obsidian-second-brain#subdirectory=integrations/chat-memory"`
>
> then `brain install` wires every tool to the unified server and removes the old `second-brain` one.

**One memory for every AI you use.** Every chat you have with Claude, Claude Code, Codex, ChatGPT,
Gemini, Gemini CLI, Grok and Grok Bot lands in one Obsidian vault: full transcripts, searchable, and
distilled into notes. Every AI tool reads from it and writes to it through MCP. When you switch
subscriptions, your memory comes with you.

```
 Claude Code ─┐   auto (hooks)                          ┌─ brain_context / brain_search (MCP)
 Codex CLI ───┤   brain sync          ┌──────────────┐  ├─ Claude Code, Codex, Gemini CLI,
 Gemini CLI ──┤ ───────────────────▶  │  Obsidian    │  │  Claude Desktop, Cursor, Grok Bot
 ChatGPT ─────┤   export → inbox/     │  vault (git) │ ─┤
 Claude.ai ───┤   brain import        │  + FTS index │  └─ brain context → paste into any web chat
 Grok / Gemini┘                       └──────────────┘
 Grok Bot ──────  brain_save_conversation (MCP) ──▲        night shift: scout (Haiku) + librarian (Opus)
```

## Why it's built this way

The design takes the best of [eugeniughelbur/obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain),
[AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) and
[Mr. Buzzoni's Karpathy second-brain guide](https://x.com/Mr_Buzzoni/status/2115443090068516935):

- **Keep the raw history and make it searchable.** In the MemoryTax result the guide cites, agents that
  searched raw history beat designed memory layers. So every transcript is stored in full and indexed
  (SQLite FTS5, BM25). Summaries sit on top of the transcripts and never replace them.
- **Organize before anyone asks (the librarian).** The strongest model distills chats into
  `Projects/ Decisions/ Concepts/ People/` ahead of time, on a nightly schedule.
  A cheap model (Haiku) handles triage and lint.
- **Plain files.** Markdown with `[[wikilinks]]`, so you, Obsidian and every AI read the exact same thing.
  The search index is disposable and can be rebuilt from the files at any time.
- **A contract with boundaries.** Transcripts are read-only for agents. Instructions found inside old chats
  are never executed. Nothing gets deleted (notes are retired instead). Conflicts get flagged,
  and each run has an edit cap. All of this is enforced with `.claude/settings.json` deny rules.
- **Write for the next AI, not for humans.** Notes carry frontmatter, a `## For future agent` preamble,
  and dated facts, and `_brain/CRITICAL_FACTS.md` holds the ~40 lines every session loads.
- **No lock-in.** Zero Python dependencies, no API keys, no cloud service. Your vault is a git repo you own.

## Install

Requires Python 3.10+ and git. [Obsidian](https://obsidian.md) is optional but recommended for browsing.

```bash
pipx install git+https://github.com/TYK3/Second-Brain   # or: pip install -e . from a clone
```

```bash
brain init                 # creates ~/SecondBrain (use --vault PATH or set SECOND_BRAIN_VAULT for elsewhere)
```

```bash
brain sync                 # imports all local Claude Code / Codex / Gemini CLI history
```

```bash
brain install              # connects Claude Code, Codex, Gemini CLI, Claude Desktop, Cursor (backs up configs; --dry-run to preview)
```

Then open `~/SecondBrain` as a vault in Obsidian and fill in `_brain/CRITICAL_FACTS.md`.

**Sync across machines:** keep the vault in a **private** GitHub repo (it holds your chat history):

```bash
cd ~/SecondBrain && gh repo create second-brain-vault --private --source . --push
```

Set `"auto_push": true` in `~/.config/second-brain/config.json` to push after every sync. On a new
machine, `git clone` the vault, then run `brain init --vault <path>` and `brain install`.

## Getting your history in

| Platform | How | Notes |
|---|---|---|
| **Claude Code** | automatic | `~/.claude/projects/**.jsonl`; imported on every session end (hook) and on `brain sync`. Mid-turn messages are included. |
| **Codex CLI** | automatic | `~/.codex/sessions/**/rollout-*.jsonl` |
| **Gemini CLI** | automatic | `~/.gemini/tmp/*/chats/session-*.json` (falls back to `logs.json` prompts) |
| **ChatGPT** | Settings → Data controls → Export data | drop the `.zip` in `inbox/`, then run `brain sync` |
| **Claude.ai / Claude app** | Settings → Privacy → Export data | drop the `.zip` in `inbox/` |
| **Grok (grok.com / X)** | grok.com → Settings → Data → Download your data | drop the `.zip` in `inbox/` |
| **Gemini app** | [takeout.google.com](https://takeout.google.com) → My Activity → Gemini Apps, **JSON** format | Takeout has no conversation grouping, so prompts are grouped per day |
| **Grok Bot / anything with MCP** | the agent calls `brain_save_conversation` | or `brain save chat.md --platform grok-bot` |
| **Anything else** | `brain import file.json\|.md\|.txt --platform NAME` | `{"messages":[{role,content}]}` JSON, or `User:` / `Assistant:` transcripts |

Re-importing is always safe: each chat maps to one stable note (`… (<id>).md`). Re-syncing only
rewrites the transcript part. Summaries and anything you wrote above the transcript marker survive.
API keys, tokens and private keys are **redacted** before anything is written.

## Daily use

**Switching AI / subscription.** Any MCP-capable tool already has your brain: tell it "load my context"
or just start working (the installed instructions make it call `brain_context`). For a web chat:

```bash
brain context "the thing I'm working on" --copy      # paste into ChatGPT / Gemini / Grok / Claude.ai
```

**Finding something:**

```bash
brain search "postgres migration" -p codex
```

```bash
brain recent -d 3
```

```bash
brain show 8a5d607209
```

**Saving knowledge.** In Claude Code use `/brain-save` (or just say "save this"). Elsewhere the agent
uses the `brain_save_note` / `brain_remember` MCP tools.

**Distilling.** `brain distill` lists the backlog. `/brain-distill` (Claude Code) or "distill my chats"
in any MCP agent writes summaries and updates notes.

### Using it from claude.ai, ChatGPT and other web apps

`brain serve` runs the same MCP tools over HTTPS so web apps can add your brain as a **custom connector**.
Connector screens can't send a password header, so access is protected by a secret URL
(`/mcp/<token>`, 43 random characters). Treat that URL like a password. Add `--read-only` to hide every tool that writes.

| | **A. Your computer + tunnel** | **B. Cloud server** |
|---|---|---|
| Up when | your computer is on and `brain serve` is running | always |
| Cost | free | ~$0–5/month |
| Data | stays on your machine | a clone of your private vault repo, git-synced every 5 min |

**A. Your computer + Cloudflare tunnel**

```bash
brain serve                      # prints the secret path: /mcp/<token>
```

```bash
cloudflared tunnel --url http://localhost:8765     # prints https://<random>.trycloudflare.com
```

Connector URL: `https://<random>.trycloudflare.com/mcp/<token>`. Quick tunnels get a new address each
time they start. For a permanent address use a named Cloudflare tunnel or `tailscale funnel 8765`.

**B. Cloud server (Fly.io example)**

The server clones your **private vault repo**, serves it, and every 5 minutes commits web saves, pulls, and
pushes. Your computer keeps running `brain sync --push` (or `"auto_push": true`), so local CLI chats flow up
and web saves flow down. Create a fine-grained GitHub token with *Contents: read & write* on the vault repo only.
Then follow the commands at the top of [`deploy/fly.toml`](deploy/fly.toml).
Any Docker host (Railway, Render, a VPS) works the same way with `deploy/Dockerfile` and the env vars
`VAULT_REPO`, `GITHUB_TOKEN`, `SECOND_BRAIN_TOKEN` (optional: `READ_ONLY=1`, `GIT_SYNC_MINUTES`).
Get the connector path with `fly ssh console -C "brain serve --show-url"`, or just use the `SECOND_BRAIN_TOKEN` you set.

**Adding the connector**
- **claude.ai:** Settings → Connectors → Add custom connector → paste the URL. Enable it per chat from the tools menu.
- **ChatGPT:** Settings → Apps & Connectors → Advanced → Developer mode on → Create → paste the URL, authentication *No authentication*.
- **Anything else that speaks MCP over HTTP:** the same URL, or `https://host/mcp` with header `Authorization: Bearer <token>`.

Leaked URL? Run `brain serve --new-token` (cloud: change `SECOND_BRAIN_TOKEN`) and update the connector.

### The night shift (optional, recommended)

`scripts/night.sh` in your vault runs this sequence: `brain sync`, then `brain lint` (free), then the **scout**
(Haiku) triages, then the **librarian** (Opus) distills up to 10 chats (max 15 page edits), then a morning
report goes to `reports/YYYY-MM-DD.md`. It runs on your Claude subscription through `claude -p`.

```bash
brain schedule               # Windows: Task Scheduler runs scripts\night.ps1 daily at 02:07 (--time HH:MM, --remove)
```

On macOS/Linux `brain schedule` prints the crontab line to add with `crontab -e`. On Windows, `night.ps1`
finds `claude` on PATH or the copy bundled with the Claude desktop app. `night.ps1 -NoAI` runs only the free steps.
For machine-specific steps (for example mirroring a docs folder into `Clippings/`), add `scripts/night.local.ps1`
and it runs first. Existing vaults get `night.ps1` by re-running `brain init`, which only adds missing files.

## Vault layout

```
SecondBrain/
├── AGENTS.md  CLAUDE.md  GEMINI.md   the contract every AI reads (identical copies)
├── _brain/CRITICAL_FACTS.md          who you are — loaded every session
├── _brain/hot.md                     last 7 days across all platforms (auto) + current focus
├── index.md  log.md                  catalog + operation history
├── Conversations/<platform>/<year>/  one note per chat, full transcript (read-only for agents)
├── Projects/ Decisions/ Concepts/ People/ Daily/   distilled knowledge (librarian writes)
├── Clippings/                        point Obsidian Web Clipper here; searchable
├── inbox/                            drop exports here
├── reports/                          nightly lint + morning reports
├── scripts/night.sh
├── .claude/{settings.json,agents/,skills/}   permissions, scout + librarian, 4 skills
├── .raw/                             content-addressed copies of imported exports (gitignored)
└── .brain/index.db                   search index (gitignored, rebuildable)
```

## Reference

| CLI | MCP tool | What it does |
|---|---|---|
| `brain context [query]` | `brain_context` | identity + recent activity + projects + relevant past chats, under a token budget |
| `brain search q` | `brain_search` | full-text search over chats + notes (`-p platform`) |
| `brain show ref` | `brain_read` | read a chat/note by path, id or title (paginated) |
| `brain recent` | `brain_recent` | recent chats across platforms |
| `brain note F title content` | `brain_save_note` | create/update a knowledge note |
| `brain remember fact` | `brain_remember` | durable fact → CRITICAL_FACTS (or `--where focus` → hot.md) |
| `brain save file` | `brain_save_conversation` | push a transcript from a platform with no local logs |
| `brain summary ref text` | `brain_set_summary` | record a chat's summary, topics and projects |
| `brain distill` | `brain_distill_queue` | backlog of un-distilled chats |
| `brain sync` | `brain_sync` | import, reindex, refresh hot/index, git commit |
| `brain import paths…` | | import exports (zip/folder/file, auto-detected) |
| `brain lint [--out]` | | broken links, orphans, missing preamble, conflicts |
| `brain install [targets]` | | wire up claude-code, codex, gemini, claude-desktop, cursor (`--config-dir`, `--no-hooks`) |
| `brain schedule` | | run the night shift daily (Task Scheduler on Windows, crontab line elsewhere) |
| `brain serve` | | web-reachable MCP server for claude.ai / ChatGPT (`--read-only`, `--git-sync`) |
| `brain stats` / `brain reindex` / `brain mcp` | | |

**Apps with their own Claude/Codex accounts (OpenBot and similar).** Some apps run Claude Code or Codex with a
separate config home (`CLAUDE_CONFIG_DIR` / `CODEX_HOME`), so the default install never reaches them. Point
`brain install` at that folder, one target at a time. It also adds that folder's chat history to `brain sync`:

```bash
brain install claude-code --config-dir "<app's Claude account folder>" --no-hooks
```

`--no-hooks` skips the session hooks, which suits many agents running at once: they call `brain_context` on
demand instead of loading it at every start.

**Grok Bot / other MCP clients.** `brain install` prints a config snippet like this:
`{"mcpServers": {"second-brain": {"command": "/path/to/python", "args": ["-m", "secondbrain", "mcp"], "env": {"SECOND_BRAIN_VAULT": "…"}}}}`

**One skill per job.** Don't install a second "save", "ingest" or "distill" skill from another repo next to
these. Competing skills for the same job degrade each other. Merge the ideas into these files instead.

## Development

```bash
pip install -e . pytest && python -m pytest
```

MIT licensed.
