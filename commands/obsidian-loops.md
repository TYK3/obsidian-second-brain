---
description: Review open loops - what you owe people and what they owe you - plus the preferences your agents have learned; close, chase or retire items
category: vault
triggers_en: ["open loops", "what do i owe", "who owes me", "what am i waiting on", "what preferences have you learned"]
---

Use the obsidian-second-brain skill. Execute `/obsidian-loops $ARGUMENTS`:

`$ARGUMENTS` may be a person or project to filter by, `prefs` to review learned preferences instead, or empty for everything. Open-loop tracking is adapted from gbrain; learning preferences from open-second-brain.

## Open loops

1. Read `_CLAUDE.md`, then `_brain/open-loops.md`. If it does not exist, create it with sections `## I owe`, `## Owed to me` and `## Closed`, then suggest `/obsidian-chat-digest`, which fills it from imported chats.
2. For each open item, check for newer evidence with `obsidian_chat_search` and `obsidian_search` (the person, the deliverable). If a newer chat or note shows it was done, move it to `## Closed` with the date and the source link.
3. Present what is left, oldest first, grouped by person: what, since when, due date, age in days, source. Flag anything past due or older than 14 days.
4. For each overdue item, offer one next action: chase (draft a short message for the owner to send; never send it), reschedule (ask for the new date), or drop (move to `## Closed` marked `dropped`, with the date). Change nothing without the owner's answer.

## Learned preferences (`prefs`)

1. Read `_brain/preferences.md`. List `## Active` preferences with their confidence, count and last-seen date.
2. Flag any not seen for 90 days and offer to retire them (move to `## Retired` with the date). Flag pairs that contradict each other and ask which one holds.
3. A preference the owner confirms here becomes `stated`; one with `high` confidence that the owner wants applied everywhere can be promoted into `_brain/CRITICAL_FACTS.md` under `## How I like to work`.

Both files are loaded by `obsidian_context` into every context pack, so keeping them current changes how every agent behaves.

---

**AI-first rule:** Every note created or updated by this command MUST follow `references/ai-first-rules.md` - `## For future agent` preamble, rich frontmatter (`type`, `date`, `tags`, `ai-first: true`, plus type-specific fields), recency markers per external claim, mandatory `[[wikilinks]]` for every person/project/concept referenced, sources preserved verbatim with URLs inline, and confidence levels where applicable. If that path does not resolve from your working directory, search upward for it; if you still cannot read it, say so before writing rather than producing a note that silently skips the rule. The vault is for future agent retrieval - not human reading.

**Anti-fabrication:** Search exhaustively before claiming any note, person, or file is absent - false absence is the most common failure mode - and never invent facts, entities, or dates (mark unknowns as `TBD`). See the anti-fabrication and search-completeness hard rules in `references/ai-first-rules.md`.
