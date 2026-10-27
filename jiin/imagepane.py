"""Image Data tab: check a photo for hidden data and save a clean copy. All local."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.suggester import Suggester
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static

from . import imagedata
from .markup import DIM, RED
from .theme import C

SEV_STYLE = {"high": f"bold {C.accent}", "med": f"bold {C.warn}", "low": f"{C.muted}"}
SEV_NAME = {"high": "HIGH", "med": "MED", "low": "LOW"}
RISK = {"high": ("HIGH RISK", f"{C.accent}"), "med": ("SOME RISK", f"{C.warn}"), "clean": ("CLEAN", f"{C.ok}")}


class PathSuggester(Suggester):
    """Tab-completes file paths."""

    def __init__(self):
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        p = Path(value).expanduser()
        base, stem = (p, "") if value.endswith("/") else (p.parent, p.name)
        try:
            for c in sorted(base.iterdir()):
                if c.name.startswith(stem) and not c.name.startswith(".") or (stem.startswith(".") and c.name.startswith(stem)):
                    rest = c.name[len(stem):] + ("/" if c.is_dir() else "")
                    return value + rest
        except OSError:
            return None
        return None


class ImagePane(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.rep: imagedata.Report | None = None

    def compose(self) -> ComposeResult:
        yield Label("IMAGE DATA  ·  see what your photo gives away, then save a clean copy (runs locally, nothing is uploaded)",
                    classes="panel-title")
        with Horizontal(id="imgform"):
            yield Input(placeholder="Path to a photo, e.g. ~/Pictures/IMG_1234.jpg   (→ to accept a path suggestion)",
                        id="imgpath", suggester=PathSuggester())
            yield Button("Check", id="imgcheck", classes="-primary")
            yield Button("Save clean copy", id="imgclean", disabled=True)
            yield Button("Map", id="imgmap", disabled=True)
        yield Static("", id="imgsum")
        with Horizontal(id="imgbody"):
            yield Static("", id="imgprev")
            with VerticalScroll(id="imgfind"):
                yield Static(Text("JPEG, PNG, WebP, TIFF and GIF work. JPEG and PNG are cleaned without re-compressing: "
                                  "the pixels stay identical, only the hidden blocks are removed, and the photo keeps its "
                                  "rotation.", style=DIM), id="imgtable")

    @on(Input.Submitted, "#imgpath")
    @on(Button.Pressed, "#imgcheck")
    def _check(self) -> None:
        p = self.query_one("#imgpath", Input).value.strip().strip("'\"")
        if p:
            self.check(p)

    @work(thread=True, exclusive=True)
    def check(self, path: str) -> None:
        try:
            rep = imagedata.analyse(path)
        except FileNotFoundError:
            self.app.call_from_thread(self._fail, f"No file at {path}")
            return
        except IsADirectoryError:
            self.app.call_from_thread(self._fail, f"{path} is a folder - pick a picture inside it")
            return
        except Exception as e:  # noqa: BLE001
            self.app.call_from_thread(self._fail, str(e))
            return
        try:
            prev = imagedata.preview_lines(rep.path, cols=44, rows=20)
        except Exception:  # noqa: BLE001
            prev = []
        self.app.call_from_thread(self._show, rep, prev)

    def _fail(self, msg: str) -> None:
        self.rep = None
        self.query_one("#imgsum", Static).update(Text(msg, style=f"{C.err}"))
        self.query_one("#imgprev", Static).update("")
        self.query_one("#imgtable", Static).update("")
        self.query_one("#imgclean", Button).disabled = True
        self.query_one("#imgmap", Button).disabled = True

    def _show(self, rep: imagedata.Report, prev: list[Text]) -> None:
        self.rep = rep
        label, col = RISK[rep.risk]
        s = Text()
        s.append(f" {label} ", style=f"bold {C.bg} on {col}")
        s.append(f"  {rep.path.name} · {rep.fmt.upper()} · {rep.width}×{rep.height} · {rep.size / 1024:.0f} KB\n", style=DIM)
        s.append(rep.summary(), style="bold")
        self.query_one("#imgsum", Static).update(s)
        pv = Text()
        for k, ln in enumerate(prev):
            if k:
                pv.append("\n")
            pv.append_text(ln)
        self.query_one("#imgprev", Static).update(pv)
        tb = Table(box=None, show_header=True, header_style=f"bold {RED}", expand=True, padding=(0, 1))
        tb.add_column("RISK", width=5, no_wrap=True)
        tb.add_column("WHAT", ratio=2)
        tb.add_column("VALUE", ratio=3)
        for f in rep.findings:
            tb.add_row(Text(SEV_NAME[f.sev], style=SEV_STYLE[f.sev]),
                       Text(f.group.upper() + "  ", style=f"{RED}") + Text(f.label, style="bold") + Text("\n" + f.why, style=DIM),
                       Text(f.value))
        if not rep.findings:
            tb.add_row("", Text("Nothing hidden found.", style=f"{C.ok}"), "")
        self.query_one("#imgtable", Static).update(tb)
        self.query_one("#imgclean", Button).disabled = False
        self.query_one("#imgmap", Button).disabled = rep.gps is None

    @on(Button.Pressed, "#imgclean")
    def _clean(self) -> None:
        if not self.rep:
            return
        try:
            out, lossless = imagedata.clean_copy(self.rep)
        except Exception as e:  # noqa: BLE001
            self.app.notify(f"Couldn't make a clean copy: {e}", severity="error")
            return
        how = "losslessly (pixels untouched)" if lossless else "by re-saving the picture"
        self.app.notify(f"Saved {out} - all hidden data removed {how}.", timeout=8)
        self.query_one("#imgpath", Input).value = str(out)
        self.check(str(out))

    @on(Button.Pressed, "#imgmap")
    def _map(self) -> None:
        if self.rep and self.rep.gps:
            lat, lon = self.rep.gps
            webbrowser.open(f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=17/{lat:.6f}/{lon:.6f}")
