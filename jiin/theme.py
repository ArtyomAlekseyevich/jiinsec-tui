# Palette. Tries Saber's colours first, then hyprctl, then falls back to the red default.
# JIIN_THEME=jiinsec forces the default.
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

SABER_PALETTE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "saber" / "palette.json"

JIINSEC = {"accent": "#ff2b3d", "accent2": "#e10a1f", "background": "#050204", "surface": "#12030a", "raised": "#2a0308",
           "border": "#5c0a12", "inactive": "#3a0a10", "foreground": "#dccbcd", "muted": "#826c70", "text_dim": "#a89497",
           "link": "#ff7a85", "name": "JIINSEC"}


def _hex(c: str) -> str | None:
    c = (c or "").strip().lstrip("#")
    m = re.fullmatch(r"(?:[0-9a-fA-F]{2})?([0-9a-fA-F]{6})", c) if len(c) == 8 else re.fullmatch(r"([0-9a-fA-F]{6})", c)
    return "#" + m.group(1).lower() if m else None


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    """Blend colour a toward b by t (0 = a, 1 = b)."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def lum(h: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _from_saber() -> dict | None:
    try:
        p = json.loads(SABER_PALETTE.read_text())
    except (OSError, ValueError):
        return None
    out = {k: _hex(p.get(k, "")) for k in ("accent", "accent2", "background", "surface", "raised", "border", "inactive",
                                           "foreground", "muted", "text_dim")}
    if not out["accent"] or not out["background"]:
        return None
    out["name"] = p.get("theme") or "Hyprland"
    return {k: v for k, v in out.items() if v}


def _from_hyprctl() -> dict | None:
    def opt(name):
        try:
            return subprocess.run(["hyprctl", "getoption", name], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    active = re.findall(r"\b([0-9a-fA-F]{8})\b", opt("general:col.active_border"))
    inactive = re.findall(r"\b([0-9a-fA-F]{8})\b", opt("general:col.inactive_border"))
    m = re.search(r"int:\s*(-?\d+)", opt("misc:background_color"))
    if not active:
        return None
    out = {"accent": _hex(active[0]), "name": "Hyprland"}
    if len(active) > 1:
        out["accent2"] = _hex(active[1])
    if inactive:
        out["inactive"] = _hex(inactive[0])
    if m:
        out["background"] = "#%06x" % (int(m.group(1)) & 0xFFFFFF)
    return out


def _build() -> SimpleNamespace:
    force = os.environ.get("JIIN_THEME", "").lower()
    src = dict(JIINSEC)
    if force not in ("jiinsec", "jiin", "red"):
        got = _from_saber() or _from_hyprctl()
        if got:
            # keep only what the theme defines; the rest is derived below
            src = {"foreground": "#e8e8ec", "background": JIINSEC["background"], **got}
    bg, acc = src["background"], src["accent"]
    acc2 = src.get("accent2") or acc
    fg = src["foreground"] if contrast(src["foreground"], bg) > 4 else ("#e8e8ec" if lum(bg) < 0.4 else "#141414")
    # make sure the accent is readable on the background
    if contrast(acc, bg) < 3:
        acc = mix(acc, fg, 0.5)
    if contrast(acc2, bg) < 2.2:
        acc2 = mix(acc2, fg, 0.5)
    muted = src.get("muted") or mix(fg, bg, 0.45)
    if contrast(muted, bg) < 3:
        muted = mix(fg, bg, 0.4)
    surface = src.get("surface") or mix(bg, acc, 0.06)
    raised = src.get("raised") or mix(bg, acc, 0.14)
    border = src.get("border") or mix(bg, acc, 0.35)
    link = src.get("link") or (acc2 if contrast(acc2, fg) > 1.3 else acc)
    C = SimpleNamespace(
        name=src.get("name", "Hyprland"),
        accent=acc, accent2=acc2,
        on_accent="#000000" if lum(acc) > 0.35 else "#ffffff",       # text on an accent block
        bg=bg, bg_alt=mix(bg, surface, 0.5), surface=surface, raised=raised,
        input=mix(bg, raised, 0.45),
        border=border, inactive=src.get("inactive") or mix(bg, border, 0.5),
        fg=fg, fg_bright=mix(fg, "#ffffff", 0.35), muted=muted, faint=mix(muted, bg, 0.45),
        text_dim=src.get("text_dim") or mix(fg, bg, 0.3),
        link=link,
        sel=mix(bg, acc, 0.14), sel_strong=mix(bg, acc, 0.24),       # selected row, own reaction
        code_bg=mix(bg, acc, 0.10), code_fg=mix(fg, acc, 0.25),
        btn=mix(bg, acc, 0.16), btn_hover=mix(bg, acc, 0.26),
        # fixed status colours
        ok="#39ff88", warn="#ffb020", err="#ff5b6b", music="#b07cff", ping_bg=mix(bg, "#ffb020", 0.10),
        del_bg=mix(bg, "#ff5b6b", 0.13),
    )
    return C


C = _build()


def textual_variables() -> dict[str, str]:
    # palette as Textual CSS vars ($jx-accent, $jx-bg, ...)
    return {"jx-" + k.replace("_", "-"): v for k, v in vars(C).items() if isinstance(v, str) and v.startswith("#")}


def palette_mtime() -> float:
    try:
        return SABER_PALETTE.stat().st_mtime
    except OSError:
        return 0.0
