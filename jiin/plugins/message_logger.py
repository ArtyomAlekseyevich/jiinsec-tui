# Keeps deleted global-chat messages visible instead of removing them, and appends them to a log file.
from __future__ import annotations

import json
import time
from pathlib import Path

from . import Plugin
from ..http import CONF_DIR


class MessageLogger(Plugin):
    name = "message-logger"
    description = "Keep deleted messages visible (dimmed red) and save them to a log file."
    default_enabled = False

    def setup(self, app) -> None:
        self.app = app
        self.logfile = CONF_DIR / "deleted-messages.jsonl"

    def chat_keep_deleted(self, keep: set, pane, ids: set) -> set:
        by_id = {m["id"]: m for m in pane.msgs}
        for mid in ids:
            m = by_id.get(mid)
            if m is not None and not m.get("_deleted"):
                self._log(m)
        return keep | set(ids)

    def _log(self, m: dict) -> None:
        row = {"logged_at": round(time.time()), "id": m.get("id"), "uid": m.get("uid"),
               "username": m.get("username"), "ts": m.get("ts"), "text": m.get("text") or "",
               "media": bool(m.get("media"))}
        try:
            CONF_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.logfile, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass
