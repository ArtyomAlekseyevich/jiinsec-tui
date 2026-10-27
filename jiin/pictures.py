# Fetching, caching and drawing pictures in the terminal (kitty graphics, or block characters).
from __future__ import annotations

import asyncio
import io
from collections import OrderedDict
from typing import Callable

from PIL import Image, ImageOps
from rich.text import Text
from .theme import C

BG = tuple(int(C.bg[i:i + 2], 16) for i in (1, 3, 5))   # the app background, behind transparent pixels


def _probe_kitty() -> bool:
    # true if the terminal supports kitty graphics. JIIN_PICTURES=kitty|blocks forces it. Run at import, before the app starts.
    import os
    env = os.environ.get("JIIN_PICTURES", "").lower()
    if env in ("blocks", "text", "off"):
        return False
    if env == "kitty":
        return True
    try:
        from textual_image._terminal import probe_terminal
        if probe_terminal().tgp:
            return True
    except Exception:  # noqa: BLE001
        pass
    # the probe sometimes misses, so also check for known terminals
    return (os.environ.get("TERM") in ("xterm-kitty", "xterm-ghostty") or bool(os.environ.get("KITTY_WINDOW_ID"))
            or os.environ.get("TERM_PROGRAM") in ("WezTerm", "ghostty"))


KITTY = _probe_kitty()
try:
    from textual_image._terminal import get_cell_size as _gcs
    _cs = _gcs() if KITTY else None
    CELL = ((_cs.width or 10), (_cs.height or 20)) if _cs else (10, 20)    # pixels per character cell
except Exception:  # noqa: BLE001
    CELL = (10, 20)

_PLACEHOLDER = chr(0x10EEEE)
# kitty row/column diacritics (first 64 from the spec)
_DIACRITICS = [chr(c) for c in (
    0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F, 0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351,
    0x0352, 0x0357, 0x035B, 0x0363, 0x0364, 0x0365, 0x0366, 0x0367, 0x0368, 0x0369, 0x036A, 0x036B, 0x036C, 0x036D,
    0x036E, 0x036F, 0x0483, 0x0484, 0x0485, 0x0486, 0x0487, 0x0592, 0x0593, 0x0594, 0x0595, 0x0597, 0x0598, 0x0599,
    0x059C, 0x059D, 0x059E, 0x059F, 0x05A0, 0x05A1, 0x05A8, 0x05A9, 0x05AB, 0x05AC, 0x05AF, 0x05C4, 0x0610, 0x0611,
    0x0612, 0x0613, 0x0614, 0x0615, 0x0616, 0x0617, 0x0657, 0x0658)]
_MAX_KITTY_CELLS = len(_DIACRITICS)


def kitty_fit(w: int, h: int, max_cols: int, max_rows: int) -> tuple[int, int]:
    # size in cells for a kitty picture, keeping aspect ratio
    cw, ch = CELL
    w, h = max(1, int(w or 1)), max(1, int(h or 1))
    sc = min(max_cols * cw / w, max_rows * ch / h, 1.0)
    return (max(1, min(max_cols, _MAX_KITTY_CELLS, round(w * sc / cw))),
            max(1, min(max_rows, _MAX_KITTY_CELLS, round(h * sc / ch))))


def kitty_placeholders(image_id: int, cols: int, rows: int) -> Text:
    # placeholder cells kitty swaps for the picture (id encoded in the colour)
    style = f"rgb({(image_id >> 16) & 255},{(image_id >> 8) & 255},{image_id & 255})"
    t = Text(no_wrap=True, overflow="crop")
    for r in range(rows):
        if r:
            t.append("\n")
        t.append("".join(_PLACEHOLDER + _DIACRITICS[r] + _DIACRITICS[c] for c in range(cols)), style=style)
    return t
DIM = f"{C.muted}"


def fit(w: int, h: int, max_cols: int, max_rows: int) -> tuple[int, int]:
    # size in cells for a block-drawn picture, keeping aspect ratio
    w, h = max(1, int(w or 1)), max(1, int(h or 1))
    sc = min(max_cols / w, (max_rows * 2) / h, 1.0)      # shrink to fit, never blow up tiny pictures
    cols = max(1, round(w * sc))
    rows = max(1, round(h * sc / 2))
    return min(cols, max_cols), min(rows, max_rows)


def decode(data: bytes, keep: int = 640) -> tuple[Image.Image, bool]:
    # decode to a small RGB image (first frame for gifs). returns (image, animated)
    im = Image.open(io.BytesIO(data))
    anim = bool(getattr(im, "is_animated", False))
    im.seek(0)
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P", "PA"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, BG + (255,))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    im.thumbnail((keep, keep), Image.LANCZOS)
    return im, anim


QUAD = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"          # index = TL 1 | TR 2 | BL 4 | BR 8
MODES = {"sext": (2, 3, "sharpest (2×3 pixels per character)"),
         "quad": (2, 2, "sharp (2×2 pixels per character)"),
         "half": (1, 2, "classic (1×2 pixels per character)")}
MODES["kitty"] = (0, 0, "real pixels (Kitty graphics)")
MODE_ORDER = (["kitty"] if KITTY else []) + ["quad", "sext", "half"]


def _sext_char(mask: int) -> str:
    """mask bits: TL 1, TR 2, ML 4, MR 8, BL 16, BR 32 → a Unicode 'sextant' character."""
    if mask == 0:
        return " "
    if mask == 63:
        return "█"
    if mask == 21:
        return "▌"
    if mask == 42:
        return "▐"
    return chr(0x1FB00 + mask - 1 - (mask > 21) - (mask > 42))


def _two_colours(px: list) -> tuple[int, tuple, tuple]:
    """Split a little block of pixels into a light and a dark group. Returns (mask of light pixels, light, dark)."""
    lum = [p[0] * 299 + p[1] * 587 + p[2] * 114 for p in px]
    mid = sum(lum) / len(lum)
    mask, hi, lo = 0, [0, 0, 0, 0], [0, 0, 0, 0]
    for k, (p, l) in enumerate(zip(px, lum)):
        g = hi if l > mid else lo
        if l > mid:
            mask |= 1 << k
        g[0] += p[0]; g[1] += p[1]; g[2] += p[2]; g[3] += 1          # noqa: E702
    avg = lambda g: (g[0] // g[3], g[1] // g[3], g[2] // g[3]) if g[3] else None   # noqa: E731
    a, b = avg(hi), avg(lo)
    return mask, a or b, b or a


def render(im: Image.Image, cols: int, rows: int, mode: str = "quad", sharpen: bool = False) -> Text:
    """Draw a picture in cols×rows character cells. More pixels per cell = more detail."""
    if mode not in ("quad", "sext", "half"):
        mode = "quad"
    pw, ph, _ = MODES[mode]
    im = im.resize((max(1, cols * pw), max(1, rows * ph)), Image.LANCZOS)
    if sharpen:          # avatars look mushy when shrunk, so sharpen them
        from PIL import ImageFilter
        im = im.filter(ImageFilter.UnsharpMask(radius=0.8, percent=90, threshold=1))
    px = im.load()
    t = Text(no_wrap=True, overflow="crop")
    for cy in range(rows):
        if cy:
            t.append("\n")
        y0 = cy * ph
        for cx in range(cols):
            x0 = cx * pw
            if mode == "half":
                a, b = px[x0, y0], px[x0, y0 + 1]
                t.append("▀", style=f"rgb({a[0]},{a[1]},{a[2]}) on rgb({b[0]},{b[1]},{b[2]})")
                continue
            block = [px[x0 + dx, y0 + dy] for dy in range(ph) for dx in range(pw)]
            mask, fg, bg = _two_colours(block)
            ch = QUAD[mask] if mode == "quad" else _sext_char(mask)
            if ch == " ":
                t.append(" ", style=f"on rgb({bg[0]},{bg[1]},{bg[2]})")
            elif ch == "█":
                t.append(" ", style=f"on rgb({fg[0]},{fg[1]},{fg[2]})")
            else:
                t.append(ch, style=f"rgb({fg[0]},{fg[1]},{fg[2]}) on rgb({bg[0]},{bg[1]},{bg[2]})")
    return t


def halfblock(im: Image.Image, cols: int, rows: int, mode: str = "half") -> Text:
    return render(im, cols, rows, mode)


PICTURE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def dropped_path(text: str):
    # if the text is just a file path (from a drag-and-drop), return it
    import re
    from pathlib import Path
    from urllib.parse import unquote
    s = (text or "").strip()
    if not s or "\n" in s:
        return None
    if s.startswith("file://"):
        s = unquote(s[7:])
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1]
    if not s.startswith(("/", "~", "./")):
        return None
    s = re.sub(r"\\(.)", r"\1", s)          # "My\ Photo.jpg" → "My Photo.jpg"
    p = Path(s).expanduser()
    try:
        return p if p.is_file() else None
    except OSError:
        return None


def _hue(s: str) -> int:
    h = 0
    for c in s:
        h = (h * 31 + ord(c)) % 360
    return h


def initial_block(name: str, cols: int, rows: int) -> Text:
    # fallback avatar: initial on a colour derived from the name
    import colorsys
    r, g, b = (round(v * 255) for v in colorsys.hls_to_rgb(_hue(name or "?") / 360, 0.32, 0.55))
    bg = f"on rgb({r},{g},{b})"
    letter = (name or "?")[:1].upper()
    t = Text(no_wrap=True, overflow="crop")
    for y in range(rows):
        if y:
            t.append("\n")
        if y == (rows - 1) // 2:
            left = (cols - 1) // 2
            t.append(" " * left, style=bg)
            t.append(letter, style=f"bold #ffffff {bg}")
            t.append(" " * (cols - left - 1), style=bg)
        else:
            t.append(" " * cols, style=bg)
    return t


def indent(pic: Text, prefix: str = " ", prefix_style: str = "") -> Text:
    # prefix every line of a block
    out = Text(no_wrap=True, overflow="crop")
    for k, line in enumerate(pic.split("\n")):
        if k:
            out.append("\n")
        out.append(prefix, style=prefix_style)
        out.append_text(line)
    return out


class Pictures:
    # loads and caches pictures, calls back when one is ready

    def __init__(self, fetch: Callable[[str], "asyncio.Future[bytes]"], keep: int = 300):
        self._fetch = fetch
        self._img: OrderedDict[str, tuple[Image.Image, bool] | None] = OrderedDict()   # None = failed
        self._txt: OrderedDict[tuple, Text] = OrderedDict()
        self._waiting: dict[str, list[Callable[[], None]]] = {}
        self._sem = asyncio.Semaphore(4)
        self._keep = keep
        self.enabled = True
        self.mode = "kitty" if KITTY else "quad"
        self.write: Callable[[str], None] | None = None     # set by the app; writes raw bytes to the terminal
        self._ids = iter(range(1 + (id(self) % 5000) * 1000, 2 ** 24))  # 24-bit so the id fits in an rgb colour
        self._sent: dict[tuple, int] = {}

    def picture(self, url: str) -> tuple[Image.Image, bool] | None:
        return self._img.get(url)

    def preview(self, url: str, w: int | None, h: int | None, max_cols: int, max_rows: int,
                on_ready: Callable[[], None] | None = None, label: str = "picture") -> Text:
        # preview for a message. loads in the background; on_ready fires when done
        if url in self._img:
            got = self._img[url]
            self._img.move_to_end(url)
            if got is None:
                return Text(f"🖼  {label} (couldn't load it)", style=DIM)
            im, anim = got
            if self.mode == "kitty" and self.write:
                return self._kitty(url, im, *kitty_fit(im.width, im.height, max_cols, max_rows))
            cols, rows = fit(im.width, im.height, max_cols, max_rows)
            key = (url, cols, rows, self.mode)
            t = self._txt.get(key)
            if t is None:
                t = render(im, cols, rows, self.mode)
                self._txt[key] = t
                while len(self._txt) > self._keep:
                    self._txt.popitem(last=False)
            return t
        first = url not in self._waiting
        waiting = self._waiting.setdefault(url, [])
        if on_ready:
            waiting.append(on_ready)
        if first:
            asyncio.get_running_loop().create_task(self._load(url))
        return Text(f"🖼  loading {label}…", style=DIM)

    def avatar(self, uid, av, name: str, cols: int, rows: int, on_ready: Callable[[], None] | None = None,
               mode: str | None = None) -> Text:
        # avatar as a cols x rows block. shows the initial until it loads, or if there is none.
        # small avatars force the 1x2 style; the denser modes turn tiny faces into stripes.
        stand_in = initial_block(name, cols, rows)
        if not self.enabled or not uid or not av or (isinstance(av, (int, float)) and av <= 0):
            return stand_in
        url = f"/api/avatar/{uid}?v={av}"
        if url not in self._img:
            first = url not in self._waiting
            waiting = self._waiting.setdefault(url, [])
            if on_ready:
                waiting.append(on_ready)
            if first:
                asyncio.get_running_loop().create_task(self._load(url))
            return stand_in
        got = self._img[url]
        if got is None:
            return stand_in
        if self.mode == "kitty" and self.write:
            im = got[0]
            side = min(im.width, im.height)
            left, top = (im.width - side) // 2, (im.height - side) // 2
            # keep it square given the cell shape
            r = max(1, round(cols * CELL[0] / CELL[1]))
            return self._kitty(url + "#sq", im.crop((left, top, left + side, top + side)), cols, min(rows, r))
        mode = mode or "half"
        key = (url, "sq", cols, rows, mode)
        t = self._txt.get(key)
        if t is None:
            im = got[0]
            side = min(im.width, im.height)          # centre-crop to a square
            left, top = (im.width - side) // 2, (im.height - side) // 2
            t = render(im.crop((left, top, left + side, top + side)), cols, rows, mode, sharpen=True)
            self._txt[key] = t
        return t

    def _kitty(self, key: str, im: Image.Image, cols: int, rows: int) -> Text:
        # upload the picture to kitty once, then return placeholder cells
        import base64
        k = (key, cols, rows)
        image_id = self._sent.get(k)
        if image_id is None:
            image_id = next(self._ids)
            px = im.resize((max(1, cols * CELL[0]), max(1, rows * CELL[1])), Image.LANCZOS)
            buf = io.BytesIO()
            px.save(buf, "PNG")
            data = base64.standard_b64encode(buf.getvalue()).decode()
            out = []
            while data:                      # 1) send the pixels in 4 KB chunks
                chunk, data = data[:4096], data[4096:]
                head = f"i={image_id},f=100,q=2,m={1 if data else 0}" if not out else f"m={1 if data else 0},q=2"
                out.append(f"\x1b_G{head};{chunk}\x1b\\")
            # 2) a virtual placement: Kitty draws it wherever placeholder characters with this id appear
            out.append(f"\x1b_Ga=p,U=1,i={image_id},c={cols},r={rows},q=2\x1b\\")
            self.write("".join(out))
            self._sent[k] = image_id
        return kitty_placeholders(image_id, cols, rows)

    async def _load(self, url: str) -> None:
        try:
            async with self._sem:
                data = await self._fetch(url)
            self._img[url] = await asyncio.to_thread(decode, data)
        except Exception:  # noqa: BLE001
            self._img[url] = None
        while len(self._img) > self._keep:
            self._img.popitem(last=False)
        for cb in self._waiting.pop(url, []):
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass


def with_avatar(avatar, content, cols: int, row_style: str | None = None):
    # [avatar | text] layout; text wraps, avatar column is fixed width
    from rich.table import Table
    g = Table.grid(padding=(0, 1), expand=True)
    g.add_column(width=cols, no_wrap=True)
    g.add_column(ratio=1)
    g.add_row(avatar, content, style=row_style)
    return g
