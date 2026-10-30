"""Scrub credentials out of transcripts before they ever hit the vault.

Chat logs from coding agents routinely contain API keys pasted into prompts or
printed by tools. The vault gets synced to git, so redaction runs on every
message at import time.
"""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),                 # Anthropic
    re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}"),  # OpenAI
    re.compile(r"xai-[A-Za-z0-9]{20,}"),                       # xAI / Grok
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),                     # Google
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),                 # GitHub
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"),                  # GitLab
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),              # Slack
    re.compile(r"AKIA[0-9A-Z]{16}"),                           # AWS access key
    re.compile(r"pplx-[A-Za-z0-9]{20,}"),                      # Perplexity
    re.compile(r"hf_[A-Za-z0-9]{30,}"),                        # Hugging Face
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
# KEY=value / "password": "value" style assignments
_ASSIGN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API_?KEY|SECRET|TOKEN|PASSWORD|PASSWD)[A-Z0-9_]*)(\s*[=:]\s*[\"']?)([^\s\"']{8,})"
)


def redact(text: str) -> str:
    if not text:
        return text
    for pat in _PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
