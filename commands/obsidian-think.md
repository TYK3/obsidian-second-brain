---
description: Think a consequential or ambiguous decision through a 10-stage loop - observe, listen, think, connect, feel, accept, create, grow - grounded in vault evidence
category: thinking
triggers_en: ["deep think", "think it through properly", "tradeoff analysis", "postmortem this", "challenge my reasoning"]
---

Use the obsidian-second-brain skill. Execute `/obsidian-think $ARGUMENTS`:

The argument is the decision, problem or plan to reason about. Adapted from the `think` skill in claude-obsidian (MIT, see `THIRD_PARTY_NOTICES.md`).

Use the ten stages as a loop of attention, not a ceremony. Scale depth to novelty, stakes, uncertainty and irreversibility; for a trivial, reversible question, skip the loop. This command is read-only: it inspects evidence but does not edit notes. If the result should be kept, finish by offering `/obsidian-decide` (decision record) or `/obsidian-save`.

## Establish an evidence frame

Before the loop, pull what the vault already knows: `obsidian_context` with the topic, then `obsidian_search` and `obsidian_chat_search` for past notes and conversations. Separate:

- **Observed:** directly supported by a note, chat, source, test or measurement (link it).
- **Inferred:** a conclusion drawn from observations; state the bridge.
- **Unknown:** missing evidence that could change the decision.
- **Preference:** the owner's choice, not a factual claim.

Never fabricate a quotation, locator, test result, consensus or confidence level.

## The ten stages

1. **Observe, external:** the actual inputs, current state, constraints, failures and prior work. Say what was read in full versus sampled.
2. **Observe, internal:** the biases most likely to distort this call (anchoring, sunk cost, novelty, urgency, confirmation, a wanted verdict). Recalibrate confidence.
3. **Listen:** the owner's intent, success condition, constraints and unstated stakes, including past statements in the vault. Ask only questions whose answers would change the outcome.
4. **Think:** reduce to invariants, alternatives, tradeoffs and failure modes. Prefer the smallest reversible test that could disprove the leading option.
5. **Connect, lateral:** the same structure in another project or domain from the vault. Use an analogy only with its limits stated.
6. **Connect, system:** upstream inputs, downstream consumers, owners, interfaces and recovery paths. Check whether a locally sound choice breaks something elsewhere.
7. **Feel:** cognitive load, trust and error-recovery experience for the people affected. Intuition is a signal to investigate, not evidence.
8. **Accept:** state constraints, uncertainty and unfavorable findings plainly, plus the strongest counterargument to the preferred conclusion.
9. **Create:** the smallest useful artifact: a recommendation, experiment, draft or handoff, with assumptions and open risks marked.
10. **Grow:** what feedback should update the decision, when to revisit it, and the reusable lesson.

## Output

```markdown
## Decision
## Evidence
## Counterargument and risks
## Verification
## Growth loop
```

Give confidence as a reasoned qualitative judgment (`stated | high | medium | speculation`), not a decorative percentage.

---

**AI-first rule:** Every note created or updated by this command MUST follow `references/ai-first-rules.md` - `## For future agent` preamble, rich frontmatter (`type`, `date`, `tags`, `ai-first: true`, plus type-specific fields), recency markers per external claim, mandatory `[[wikilinks]]` for every person/project/concept referenced, sources preserved verbatim with URLs inline, and confidence levels where applicable. If that path does not resolve from your working directory, search upward for it; if you still cannot read it, say so before writing rather than producing a note that silently skips the rule. The vault is for future agent retrieval - not human reading.

**Anti-fabrication:** Search exhaustively before claiming any note, person, or file is absent - false absence is the most common failure mode - and never invent facts, entities, or dates (mark unknowns as `TBD`). See the anti-fabrication and search-completeness hard rules in `references/ai-first-rules.md`.
