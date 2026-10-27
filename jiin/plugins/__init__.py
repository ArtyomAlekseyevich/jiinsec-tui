# Small plugin system. Drop a module in this package that defines a Plugin subclass.
# The app calls named hooks; a plugin handles the ones it cares about.
from __future__ import annotations

import importlib
import pkgutil


class Plugin:
    name = ""
    description = ""
    default_enabled = False

    def setup(self, app) -> None:
        """Called once, the first time the plugin becomes active."""

    # Optional hooks a plugin may define:
    #   chat_received(pane, messages)          new chat messages arrived
    #   chat_keep_deleted(keep, pane, ids)     return the set of deleted ids to keep visible


class PluginManager:
    def __init__(self, app):
        self.app = app
        self.all: list[Plugin] = []
        self.enabled: set[str] = set()
        self._ready: set[str] = set()

    def discover(self) -> None:
        for info in pkgutil.iter_modules(__path__):
            if info.name.startswith("_"):
                continue
            mod = importlib.import_module(f"{__name__}.{info.name}")
            for v in vars(mod).values():
                if isinstance(v, type) and issubclass(v, Plugin) and v is not Plugin:
                    self.all.append(v())
        self.all.sort(key=lambda p: p.name)

    def load(self, enabled: list[str] | None) -> None:
        if enabled is None:        # first run: turn on the defaults
            self.enabled = {p.name for p in self.all if p.default_enabled}
        else:
            self.enabled = set(enabled)
        for p in self.active():
            self._ensure_setup(p)

    def get(self, name: str) -> Plugin | None:
        return next((p for p in self.all if p.name == name), None)

    def active(self) -> list[Plugin]:
        return [p for p in self.all if p.name in self.enabled]

    def set_enabled(self, name: str, on: bool) -> None:
        if on:
            self.enabled.add(name)
            p = self.get(name)
            if p:
                self._ensure_setup(p)
        else:
            self.enabled.discard(name)

    def _ensure_setup(self, p: Plugin) -> None:
        if p.name in self._ready:
            return
        self._ready.add(p.name)
        try:
            p.setup(self.app)
        except Exception:  # noqa: BLE001
            pass

    def call(self, hook: str, *a, **k) -> None:
        for p in self.active():
            fn = getattr(p, hook, None)
            if fn:
                try:
                    fn(*a, **k)
                except Exception:  # noqa: BLE001
                    pass

    def reduce(self, hook: str, acc, *a, **k):
        for p in self.active():
            fn = getattr(p, hook, None)
            if fn:
                try:
                    acc = fn(acc, *a, **k)
                except Exception:  # noqa: BLE001
                    pass
        return acc
