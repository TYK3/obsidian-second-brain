# The night shift (Windows): organize the brain before anyone asks.
# Scheduled by:  brain schedule   (or run it by hand:  powershell -File scripts\night.ps1)
# -NoAI skips the Claude steps (sync + lint only, free).
param([switch]$NoAI)
$ErrorActionPreference = 'Continue'
$vault = Split-Path $PSScriptRoot -Parent
Set-Location $vault
$env:SECOND_BRAIN_VAULT = $vault
$env:PYTHONIOENCODING = 'utf-8'
$day = Get-Date -Format 'yyyy-MM-dd'
New-Item -ItemType Directory -Force reports, .brain | Out-Null
$log = Join-Path $vault ".brain\night.log"
function Say($m) { "$(Get-Date -Format s)  $m" | Tee-Object -FilePath $log -Append }

$brain = if ($env:BRAIN) { $env:BRAIN } else { (Get-Command brain -ErrorAction SilentlyContinue).Source }
if (-not $brain) { Say "brain not found on PATH"; exit 1 }

# Claude CLI: PATH first, then the copy bundled with the Claude desktop app (newest version).
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) {
    $claude = Get-ChildItem "$env:APPDATA\Claude\claude-code\*\*\claude.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}

Say "night shift start"
# Optional machine-specific steps (e.g. mirroring docs into Clippings/). Not part of the template.
$local = Join-Path $PSScriptRoot 'night.local.ps1'
if (Test-Path $local) { & $local *>> $log }

# 1. Import every chat from every local AI CLI, plus anything dropped in inbox/ (free).
& $brain sync --no-commit --quiet *>> $log
# 2. Mechanical checks (free).
& $brain lint --out *>> $log

if ($claude -and -not $NoAI) {
    # 3. Scout (Haiku) triages the queue and marks trivial chats.
    & $claude -p "Use the scout agent: triage the distill queue and finish reports/$day-mechanical.md." `
        --model haiku --permission-mode acceptEdits *>> $log
    # 4. Librarian (Opus) distills the substantive ones. Max 15 page edits.
    & $claude -p "Use the librarian agent and follow the /obsidian-chat-digest command on up to 10 conversations. Max 15 knowledge-page edits." `
        --model opus --permission-mode acceptEdits *>> $log
    # 5. Morning report.
    & $claude -p "Write reports/$day.md: what changed in the vault today (see log.md), conflicts found, fixes proposed. Keep it under 40 lines." `
        --model haiku --permission-mode acceptEdits --allowedTools "Read,Grep,Glob,Write" *>> $log
} elseif (-not $claude) {
    Say "claude CLI not found; skipped distilling"
}

& $brain sync --quiet *>> $log  # reindex + commit (+ push if auto_push is on)
Say "night shift done"
