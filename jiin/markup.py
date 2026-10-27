"""Turn the site's text formats into Rich Text for the terminal."""
from __future__ import annotations

import re
import time
from datetime import datetime

from rich.text import Text
from .theme import C

RED = f"{C.accent}"
DIM = f"{C.muted}"
LINK = f"{C.link}"

# time

def ago(t: float | None) -> str:
    if not t:
        return ""
    s = max(0, time.time() - float(t))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    if s < 2592000:
        return f"{int(s // 86400)}d ago"
    return datetime.fromtimestamp(float(t)).strftime("%d %b %Y")


def hhmm(t: float | None) -> str:
    return datetime.fromtimestamp(float(t or 0)).strftime("%H:%M")


def full(t: float | None) -> str:
    return datetime.fromtimestamp(float(t or 0)).strftime("%d %b %Y %H:%M") if t else ""



_INL = re.compile(
    r"(?P<esc>\\[\\`*_~\[\]#>.\-)•])"
    r"|`(?P<code>[^`\n]+)`"
    r"|\*\*(?P<b>.+?)\*\*"
    r"|__(?P<u>.+?)__"
    r"|~~(?P<s>.+?)~~"
    r"|\*(?P<i>[^*\n]+?)\*"
    r"|\[\[(?P<w>[A-Za-z][A-Za-z '\-]{0,39})\]\]"
    r"|\[(?P<lt>[^\]\n]+)\]\((?P<lu>https?://[^\s)]+)\)"
    r"|(?P<url>https?://[^\s<>()\"']+[^\s<>()\"'.,!?;:])"
)


def inline(s: str, base: str = "") -> Text:
    out = Text(style=base)
    pos = 0
    for m in _INL.finditer(s):
        if m.start() > pos:
            out.append(s[pos:m.start()])
        g = next(n for n in ("esc", "code", "b", "u", "s", "i", "w", "lt", "url") if m.group(n) is not None)
        if g == "esc":
            out.append(m.group("esc")[1])
        elif g == "code":
            out.append(m.group("code"), style=f"{C.code_fg} on {C.sel}")
        elif g == "b":
            out.append_text(inline(m.group("b"), "bold"))
        elif g == "u":
            out.append_text(inline(m.group("u"), "underline"))
        elif g == "s":
            out.append_text(inline(m.group("s"), "strike"))
        elif g == "i":
            out.append_text(inline(m.group("i"), "italic"))
        elif g == "w":
            out.append(m.group("w"), style=f"underline {LINK}")
        elif g == "lt":
            url = m.group("lu")
            out.append(m.group("lt"), style=f"underline {LINK} link {url}")
        elif g == "url":
            url = m.group("url")
            out.append(url, style=f"underline {LINK} link {url}")
        pos = m.end()
    if pos < len(s):
        out.append(s[pos:])
    return out


_LIST = re.compile(r"^\s*(?:[-*•]|(\d{1,3})[.)])\s+(.*)$")
_HEAD = re.compile(r"^(#{1,3})\s+(.*)$")


def forum_body(body: str, width_hint: int = 0) -> Text:
    out = Text()
    lines = (body or "").replace("\r\n", "\n").split("\n")
    i = 0
    first = True

    def nl():
        nonlocal first
        if not first:
            out.append("\n")
        first = False

    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        if st.startswith("```"):
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            for c in code or [""]:
                nl()
                out.append("  " + c, style=f"{C.code_fg} on {C.code_bg}")
            continue
        if st in ("[center]", "[/center]", "[right]", "[/right]"):
            i += 1
            continue
        m = _HEAD.match(ln)
        if m:
            nl()
            out.append_text(inline(m.group(2), f"bold {RED}" + (" underline" if len(m.group(1)) == 1 else "")))
            i += 1
            continue
        if ln.startswith(">"):
            nl()
            out.append("▍ ", style=DIM)
            out.append_text(inline(ln[1:].lstrip(), f"italic {DIM}"))
            i += 1
            continue
        m = _LIST.match(ln)
        if m:
            nl()
            out.append(f"  {m.group(1)}. " if m.group(1) else "  • ", style=RED)
            out.append_text(inline(m.group(2)))
            i += 1
            continue
        nl()
        if st:
            out.append_text(inline(ln))
        i += 1
    return out


def snip(s: str) -> Text:
    """Search snippets mark hits with \\x02 ... \\x03."""
    t = Text()
    for k, part in enumerate(re.split(r"[\x02\x03]", s or "")):
        t.append(part, style=f"bold {RED}" if k % 2 else "")
    return t
