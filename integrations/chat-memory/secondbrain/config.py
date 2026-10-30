"""Where the vault lives. Resolution order: --vault flag, $SECOND_BRAIN_VAULT, config file, ~/SecondBrain."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_FILE = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "second-brain" / "config.json"
DEFAULTS = {"vault": "~/SecondBrain", "auto_push": False, "include_tools": True,
            "sources": {}}  # extra folders to scan on sync: {"/path": "importer-name or auto"}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except ValueError:
            pass
    return cfg


def save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def vault_path(override: str | None = None) -> Path:
    return Path(override or os.environ.get("SECOND_BRAIN_VAULT") or load()["vault"]).expanduser()
