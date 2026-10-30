#!/usr/bin/env bash
# The night shift: organize the brain before anyone asks.
# crontab -e →  7 2 * * *  ~/SecondBrain/scripts/night.sh >> ~/SecondBrain/.brain/night.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
export SECOND_BRAIN_VAULT="$PWD"
BRAIN="${BRAIN:-brain}"
day=$(date +%F)
mkdir -p reports

# 1. Import every chat from every local AI CLI, plus anything dropped in inbox/ (free).
$BRAIN sync --no-commit --quiet
# 2. Mechanical checks (free).
$BRAIN lint --out

if command -v claude >/dev/null; then
  # 3. Scout (Haiku) triages the queue and marks trivial chats.
  claude -p "Use the scout agent: triage the distill queue and finish reports/$day-mechanical.md." \
    --model haiku --permission-mode acceptEdits || true
  # 4. Librarian (Opus) distills the substantive ones. Max 15 page edits.
  claude -p "Use the librarian agent and follow the /obsidian-chat-digest command on up to 10 conversations. Max 15 knowledge-page edits." \
    --model opus --permission-mode acceptEdits || true
  # 5. Morning report.
  claude -p "Write reports/$day.md: what changed in the vault today (see log.md), conflicts found, fixes proposed. Keep it under 40 lines." \
    --model haiku --permission-mode acceptEdits --allowedTools "Read,Grep,Glob,Write" || true
fi

$BRAIN sync --quiet  # reindex + commit (+ push if auto_push is on)
