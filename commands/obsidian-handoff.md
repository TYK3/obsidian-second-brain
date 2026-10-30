---
description: Build a context pack to continue in another AI - identity, current task, recent work and relevant past chats, ready to paste into ChatGPT, Gemini, Grok or Claude
category: vault
triggers_en: ["handoff", "i'm switching to", "export my context", "give me something to paste into another ai", "context pack"]
---

Use the obsidian-second-brain skill. Execute `/obsidian-handoff $ARGUMENTS`:

The argument is the task being handed off (optional).

1. Save first: run the `/obsidian-save` workflow for this session so nothing is lost.
2. Call `obsidian_context` with `query` set to the current task and `budget_tokens` between 3000 and 6000.
3. Add a `## Where we are right now` section: the current task, the last step done, the next 3 steps, and the files or links involved.
4. Save it to `_brain/handoff.md` (overwrite) and show it to the user in a single code block they can paste.

CLI equivalent: `brain context "<task>" --out _brain/handoff.md --copy` (copies it to the clipboard).

---

**AI-first rule:** Every note created or updated by this command MUST follow `references/ai-first-rules.md` - `## For future agent` preamble, rich frontmatter (`type`, `date`, `tags`, `ai-first: true`, plus type-specific fields), recency markers per external claim, mandatory `[[wikilinks]]` for every person/project/concept referenced, sources preserved verbatim with URLs inline, and confidence levels where applicable. If that path does not resolve from your working directory, search upward for it; if you still cannot read it, say so before writing rather than producing a note that silently skips the rule. The vault is for future agent retrieval - not human reading.

**Anti-fabrication:** Search exhaustively before claiming any note, person, or file is absent - false absence is the most common failure mode - and never invent facts, entities, or dates (mark unknowns as `TBD`). See the anti-fabrication and search-completeness hard rules in `references/ai-first-rules.md`.
