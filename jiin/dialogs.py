"""Small reusable modal dialogs."""
from __future__ import annotations

import io
import webbrowser

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea
from .theme import C

# import early so it can probe the terminal before the app starts
try:
    import textual_image.widget as _tiw
    _GFX = _tiw.Image if _tiw.Image in (_tiw.TGPImage, _tiw.SixelImage) else None
except Exception:  # noqa: BLE001
    _tiw, _GFX = None, None


def _open_full(data: bytes):
    # decode to RGB (max 2000px). returns (image, animated, original size)
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    anim = bool(getattr(im, "is_animated", False))
    im.seek(0)
    im = ImageOps.exif_transpose(im)
    size = im.size
    if im.mode in ("RGBA", "LA", "P", "PA"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (5, 2, 4, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    im.thumbnail((2000, 2000))
    return im, anim, size


class Confirm(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "dismiss(False)", "Cancel"), Binding("y", "dismiss(True)", "Yes", show=False)]

    def __init__(self, title: str, text: str, ok: str = "OK", danger: bool = False):
        super().__init__()
        self._t, self._x, self._ok, self._danger = title, text, ok, danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._t, classes="title")
            yield Static(self._x)
            with Horizontal(classes="row"):
                yield Button(self._ok, id="ok", classes="-primary" if not self._danger else "")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#cancel" if self._danger else "#ok", Button).focus()

    def on_button_pressed(self, e: Button.Pressed) -> None:
        self.dismiss(e.button.id == "ok")


class Prompt(ModalScreen[str | None]):
    # text prompt (multiline=True for several lines, Ctrl+S to submit)
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel"), Binding("ctrl+s", "submit", "Submit")]

    def __init__(self, title: str, placeholder: str = "", value: str = "", multiline: bool = False,
                 ok: str = "OK", help: str = "", max_length: int = 0, password: bool = False):
        super().__init__()
        self._t, self._ph, self._v, self._ml, self._ok, self._help = title, placeholder, value, multiline, ok, help
        self._max, self._pw = max_length, password

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._t, classes="title")
            if self._help:
                yield Static(self._help, classes="meta")
            if self._ml:
                ta = TextArea(self._v, id="val", soft_wrap=True, show_line_numbers=False)
                ta.styles.height = 12
                yield ta
            else:
                yield Input(self._v, placeholder=self._ph, id="val", max_length=self._max, password=self._pw)
            with Horizontal(classes="row"):
                yield Button(self._ok + (" (Ctrl+S)" if self._ml else ""), id="ok", classes="-primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        w = self.query_one("#val")
        w.focus()
        if isinstance(w, TextArea):
            w.move_cursor(w.document.end)

    def _value(self) -> str:
        w = self.query_one("#val")
        return w.text if isinstance(w, TextArea) else w.value

    def action_submit(self) -> None:
        self.dismiss(self._value())

    def on_input_submitted(self, e: Input.Submitted) -> None:
        self.dismiss(e.value)

    def on_button_pressed(self, e: Button.Pressed) -> None:
        self.dismiss(self._value() if e.button.id == "ok" else None)


class Choose(ModalScreen[str | None]):
    """Pick one of several labelled options."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title: str, options: list[tuple[str, str]], value: str | None = None):
        super().__init__()
        self._t, self._opts, self._val = title, options, value

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._t, classes="title")
            yield Select([(l, v) for v, l in self._opts], value=self._val if self._val is not None else Select.NULL, id="sel", allow_blank=self._val is None)
            with Horizontal(classes="row"):
                yield Button("OK", id="ok", classes="-primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, e: Button.Pressed) -> None:
        v = self.query_one("#sel", Select).value
        self.dismiss(None if e.button.id != "ok" or v is Select.NULL else str(v))


class TextView(ModalScreen[None]):
    BINDINGS = [Binding("escape,q", "dismiss(None)", "Close")]

    def __init__(self, title: str, body: Text | str):
        super().__init__()
        self._t, self._b = title, body

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._t, classes="title")
            with VerticalScroll():
                yield Static(self._b)
            with Horizontal(classes="row"):
                yield Button("Close", id="close")

    def on_button_pressed(self, e: Button.Pressed) -> None:
        self.dismiss(None)


class ImageView(ModalScreen[None]):
    # full-size picture. real pixels on kitty/sixel, block characters otherwise.
    BINDINGS = [Binding("escape,q", "dismiss(None)", "Close"), Binding("o", "browser", "Open in browser")]

    def __init__(self, title: str, url: str):
        super().__init__()
        self._t, self._url = title, url

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._t, classes="title")
            yield Static("Loading…", id="pic")
            yield Static("", id="picinfo", classes="meta")
            with Horizontal(classes="row"):
                yield Button("Open in browser (o)", id="open")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self.run_worker(self._load(), exclusive=True)

    async def _load(self) -> None:
        import asyncio
        pic = self.query_one("#pic", Static)
        try:
            data = await self.app.api.http.raw(self._url)
            im, anim, (w, h) = await asyncio.to_thread(_open_full, data)
        except Exception as e:  # noqa: BLE001
            pic.update(Text(f"Couldn't load the picture: {e}", style=f"{C.err}"))
            return
        max_cols = max(20, self.app.size.width - 12)
        max_rows = max(6, self.app.size.height - 13)
        info = f"{w}×{h}" + (" · GIF (first frame)" if anim else "") + f" · {len(data) / 1024:.0f} KB"
        if _GFX is not None:
            try:
                cell = _tiw.get_cell_size()
                cw, ch = (cell.width or 10), (cell.height or 20)
                sc = min(max_cols * cw / w, max_rows * ch / h, 2.0)
                big = _GFX(im, id="picbig")
                big.styles.width = max(1, round(w * sc / cw))
                big.styles.height = max(1, round(h * sc / ch))
                await pic.remove()
                await self.query_one(".dialog").mount(big, after=self.query_one(".title"))
                self.query_one("#picinfo", Static).update(info)
                return
            except Exception:  # noqa: BLE001
                pass              # fall back to half-blocks below
        from .pictures import render
        sc = min(max_cols / w, max_rows * 2 / h, 4.0)
        cols, rows = max(1, round(w * sc)), max(1, round(h * sc / 2))
        pic.update(await asyncio.to_thread(render, im, cols, rows, self.app.pics.mode))
        self.query_one("#picinfo", Static).update(info + " · press o to see it sharp in your browser")

    def action_browser(self) -> None:
        url = self._url if self._url.startswith("http") else self.app.api.http.base + self._url
        webbrowser.open(url)

    def on_button_pressed(self, e: Button.Pressed) -> None:
        if e.button.id == "open":
            self.action_browser()
        else:
            self.dismiss(None)
