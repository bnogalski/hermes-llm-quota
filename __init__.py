"""LLM Quota Monitor — Hermes plugin entry.

Copies the desktop pane into $HERMES_HOME/desktop-plugins/llm-quota/
so `hermes plugins install` also lights up the Electron UI.
"""

from __future__ import annotations

import os
from pathlib import Path


def _ensure_desktop_plugin() -> None:
    src = Path(__file__).resolve().parent / "desktop" / "plugin.js"
    if not src.is_file():
        return
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    dest = home / "desktop-plugins" / "llm-quota" / "plugin.js"
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = src.read_bytes()
    if dest.is_file() and dest.read_bytes() == payload:
        return
    dest.write_bytes(payload)


def register(ctx) -> None:
    del ctx
    _ensure_desktop_plugin()
