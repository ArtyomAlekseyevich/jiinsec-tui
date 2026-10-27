# jiinsec in the terminal.
from __future__ import annotations

import asyncio
import io
import json
import re
import time
import webbrowser
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.suggester import Suggester
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import (Button, Checkbox, ContentSwitcher, Footer, Input, Label, OptionList, Static,
                             TabbedContent, TabPane)
from textual.widgets.option_list import Option

from .dialogs import Choose, Confirm, ImageView, Prompt, TextView
from .forums import ForumsPane
from .http import BASE, CONF_DIR, Http, SignedOut
from .imagepane import ImagePane
from .markup import DIM, LINK, RED, ago, full, hhmm
from .pictures import PICTURE_EXT, Pictures, dropped_path, indent, with_avatar
from .social import QUICK_REACTS, SocialPane
from .theme import C, lum, palette_mtime, textual_variables

LOGO = """\
     ██╗██╗██╗███╗   ██╗███████╗███████╗ ██████╗
     ██║██║██║████╗  ██║██╔════╝██╔════╝██╔════╝
     ██║██║██║██╔██╗ ██║███████╗█████╗  ██║
██   ██║██║██║██║╚██╗██║╚════██║██╔══╝  ██║
╚█████╔╝██║██║██║ ╚████║███████║███████╗╚██████╗
 ╚════╝ ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝ ╚═════╝"""

# used until /api/roles loads
FALLBACK_ROLES = [
    {"id": "owner", "label": "Owner", "color": "#ffffff"}, {"id": "admin", "label": "Admin", "color": "#ff8a5c"},
    {"id": "manager", "label": "Manager", "color": f"{C.accent}"}, {"id": "developer", "label": "Developer", "color": "#4f7cff"},
    {"id": "mod", "label": "Mod", "color": "#394fb1"}, {"id": "contributor", "label": "Contributor", "color": "#d6ecff"},
    {"id": "vip", "label": "VIP", "color": "#ffd700"}, {"id": "notable", "label": "Notable", "color": "#ff4fa3"},
    {"id": "artist", "label": "Artist", "color": f"{C.music}"}, {"id": "tester", "label": "Tester", "color": f"{C.ok}"},
    {"id": "early_supporter", "label": "Early Supporter", "color": "#5b3fd1"},
]

HELP = f"""\
[b {C.accent}]Moving around[/]
  F2 Chat   F3 Messages   F4 Forums   F5 News   F6 Image Data      (or click the tabs)
  Tab / Shift+Tab      move between the message list and the text box
  Ctrl+B               show / hide the members list (pick someone to see their profile)
  F7                   show / hide pictures inside messages (i on a message opens it full size)
  F8                   picture quality: real pixels (Kitty) / 2×2 / 2×3 / 1×2 pixels per character
  F9                   see-through background (shows your terminal's transparency, e.g. Kitty's)
  F10                  log out          Ctrl+Q   quit

[b {C.accent}]Global chat[/]
  Type and press Enter to send.  @name and :emoji: complete with → (right arrow).
  Drag a picture into the text box and press Enter to send it, or: /img ~/path/pic.jpg \\[caption]
  (the site unlocks sending pictures at a certain level)
  In the message list (Tab to it, ↑/↓ to pick a message):
    r reply   e react   d delete   m mention   p profile   i view picture   Enter = all actions

[b {C.accent}]Messages[/]
  Ctrl+N message someone   Ctrl+F friends & requests   Ctrl+G new group chat
  Drag any file into the text box and press Enter to send it, or: /file ~/path/to/file \\[message]
  In a conversation: r reply  e react  d delete  i view picture  o open file

[b {C.accent}]Forums[/]
  Pick a forum on the left, a thread on the right.  n new thread · s sort · / search · \\[ ] pages · i notifications
  In a thread: r reply  q quote  +/- vote  e edit  d delete  i images  f follow  \\[ ] pages  Esc back

[b {C.accent}]Image Data[/]
  Give it a photo's path. It lists what hidden data the file carries (GPS, device serials, names, times...)
  and can save a clean copy. It all happens on your computer; nothing is uploaded.

Voice calls, the World Explorer globe and the music player need a browser - use https://jiin.party for those."""


class Api:
    # wraps every request so a 401 signs the app out

    def __init__(self, app: "JiinApp"):
        self.app = app
        self.http = Http()

    async def j(self, url: str, body=None, **kw) -> dict:
        try:
            r = await self.http.j(url, body, **kw)
        except SignedOut:
            self.app.call_later(self.app.signed_out)
            return {"error": "You're signed out", "_signed_out": True}
        return r if isinstance(r, dict) else {"data": r}

    async def upload(self, url: str, data: bytes, ctype: str) -> dict:
        try:
            r = await self.http.upload(url, data, ctype)
        except SignedOut:
            self.app.call_later(self.app.signed_out)
            return {"error": "You're signed out"}
        return r if isinstance(r, dict) else {"error": "Unexpected answer"}


# ====================================================================== login

class LoginScreen(Screen):
    BINDINGS = [Binding("ctrl+q", "app.quit", "Quit")]

    def __init__(self, mode: str = "login"):
        super().__init__()
        self.mode = mode
        self.pid = None

    def compose(self) -> ComposeResult:
        with Vertical(id="loginbox"):
            yield Static(Text(LOGO, style=f"bold {RED}"), id="logo")
            yield Static(Text.assemble(("JIINSEC", f"bold {RED}"), "  Stay safe online"), id="logosmall")
            yield Static("Stay safe online", id="tag")
            with ContentSwitcher(initial="lf", id="lsw"):
                with Vertical(id="lf"):
                    yield Input(placeholder="USERNAME", id="lu", max_length=20)
                    yield Input(placeholder="PASSWORD", password=True, id="lp", max_length=200)
                    yield Button("Log in", id="lgo", classes="-primary")
                    yield Static(Text.assemble(("No account yet, or forgot your password? Do that at ", DIM),
                                               (BASE.replace("https://", ""), f"underline {LINK} link {BASE}"),
                                               (" - then log in here. Your session is remembered.", DIM)))
                with Vertical(id="vf"):
                    yield Static("", id="vto")
                    yield Input(placeholder="6-DIGIT CODE", id="vc", max_length=6, restrict=r"[0-9]*")
                    yield Button("Verify email", id="vgo", classes="-primary")
                    with Horizontal(classes="row"):
                        yield Button("Resend code", id="vre")
                        yield Button("Back", id="vback")
                    yield Static("Can't find it? Check spam. The code works for 10 minutes.", classes="meta")
                with Vertical(id="tf"):
                    yield Static("", id="tgintro")
                    yield Static(Text("  • You must be 18 or older to use JIINSEC\n"
                                      "  • Be respectful; no harassment, threats or illegal content\n"
                                      "  • Private messages stay private unless they're reported", style=DIM))
                    yield Button("Read the Terms & Privacy Policy (opens the site)", id="tread")
                    yield Checkbox("I have read and agree to the Terms of Service and Privacy Policy, and I confirm I am 18 or older.", id="tck")
                    yield Button("Agree & continue", id="tok", classes="-primary")
                    yield Button("Log out", id="tout")
            yield Static("", id="loginmsg")

    def on_mount(self) -> None:
        self.query_one("#loginmsg").display = False
        if self.mode == "tos":
            self.show_tos()
        else:
            self.query_one("#lu", Input).focus()

    def on_resize(self) -> None:
        # big logo needs a tall terminal; short ones get a one-liner
        self.set_class(self.size.height < 40, "short")

    def msg(self, t: str, err: bool = True) -> None:
        m = self.query_one("#loginmsg", Static)
        m.update(Text(t, style=f"{C.err}" if err else f"{C.ok}"))
        m.display = bool(t)

    # ---- step 1: username + password
    @on(Input.Submitted, "#lu")
    def _u(self) -> None:
        self.query_one("#lp", Input).focus()

    @on(Input.Submitted, "#lp")
    @on(Button.Pressed, "#lgo")
    def _go(self) -> None:
        u, p = self.query_one("#lu", Input).value.strip(), self.query_one("#lp", Input).value
        if not u or not p:
            self.msg("Enter your username and password")
            return
        self.login(u, p)

    @work(exclusive=True)
    async def login(self, u: str, p: str) -> None:
        btn = self.query_one("#lgo", Button)
        btn.disabled = True
        self.msg("Logging in…", err=False)
        r = await self.app.api.j("/api/login", {"username": u, "password": p})
        btn.disabled = False
        if r.get("verify"):
            self.query_one("#lp", Input).value = ""
            self.show_verify(r["verify"], "Your account isn't finished yet - enter the code we emailed you.")
            return
        if r.get("error"):
            self.msg(r["error"] + (" (agree to the Terms on the website first)" if r.get("tos") else ""))
            return
        self.query_one("#lp", Input).value = ""
        await self.app.after_login()

    # ---- step 2 (only for unfinished accounts): emailed code
    def show_verify(self, v: dict, note: str = "") -> None:
        self.pid = v.get("pid")
        t = Text()
        if note:
            t.append(note + "\n", style=f"{C.warn}")
        t.append("We sent a 6-digit code to ")
        t.append(str(v.get("email", "your email")), style="bold")
        self.query_one("#vto", Static).update(t)
        self.query_one("#lsw", ContentSwitcher).current = "vf"
        self.query_one("#vc", Input).focus()
        self.msg("", False)

    @on(Input.Submitted, "#vc")
    @on(Button.Pressed, "#vgo")
    def _vgo(self) -> None:
        c = self.query_one("#vc", Input).value.strip()
        if len(c) != 6:
            self.msg("The code has 6 digits")
            return
        self.verify(c)

    @work(exclusive=True)
    async def verify(self, code: str) -> None:
        r = await self.app.api.j("/api/register/verify", {"pid": self.pid, "code": code})
        if r.get("gone"):
            self.query_one("#lsw", ContentSwitcher).current = "lf"
            self.msg(r.get("error") or "That signup expired - start again on the website")
            return
        if r.get("error"):
            self.msg(r["error"])
            return
        await self.app.after_login()

    @on(Button.Pressed, "#vre")
    @work(exclusive=True)
    async def _vre(self) -> None:
        r = await self.app.api.j("/api/register/resend", {"pid": self.pid})
        if r.get("verify"):
            v = r["verify"]
            self.show_verify(v)
            self.msg(f"New code sent. {v.get('sends_left', '')} resends left.".replace(" .", "."), err=False)
        else:
            self.msg(r.get("error") or "Couldn't resend")

    @on(Button.Pressed, "#vback")
    def _vback(self) -> None:
        self.query_one("#lsw", ContentSwitcher).current = "lf"
        self.msg("", False)

    # ---- terms gate
    def show_tos(self) -> None:
        self.query_one("#tgintro", Static).update(Text.assemble(
            "Welcome back, ", (self.app.me.get("username", ""), "bold"),
            ". JIINSEC asks every member to agree to its terms directly. You only need to do this once.\n"))
        self.query_one("#lsw", ContentSwitcher).current = "tf"
        self.query_one("#tck", Checkbox).focus()

    @on(Button.Pressed, "#tread")
    def _tread(self) -> None:
        webbrowser.open(BASE)
        self.msg("Opened the site - the TOS button is at the bottom of the page.", err=False)

    @on(Button.Pressed, "#tok")
    @work(exclusive=True)
    async def _tok(self) -> None:
        if not self.query_one("#tck", Checkbox).value:
            self.msg("Tick the box to agree first")
            return
        r = await self.app.api.j("/api/tos/agree", {"agree": True, "ver": self.app.me.get("tos_ver")})
        if r.get("error"):
            self.msg(r["error"])
            return
        await self.app.after_login()

    @on(Button.Pressed, "#tout")
    def _tout(self) -> None:
        self.app.logout()


# ====================================================================== chat

class ChatSuggester(Suggester):
    # completes @names and :emoji: at the end of the input

    def __init__(self, app: "JiinApp"):
        super().__init__(use_cache=False, case_sensitive=True)
        self._app = app

    async def get_suggestion(self, value: str) -> str | None:
        m = re.search(r"(?:^|[^A-Za-z0-9_.@-])@([A-Za-z0-9_.-]{1,20})$", value)
        if m:
            q = m.group(1).lower()
            users = sorted(self._app.members.values(), key=lambda u: (not self._app.online(u), u.get("username", "").lower()))
            for u in users:
                n = u.get("username", "")
                if n.lower().startswith(q) and n.lower() != q and u.get("id") != self._app.me.get("id"):
                    return value + n[len(q):] + " "
        m = re.search(r"(?:^|\s):([a-z0-9_]{2,32})$", value)
        if m:
            q = m.group(1)
            for e in self._app.emojis:
                if e.get("name", "").startswith(q):
                    return value + e["name"][len(q):] + ": "
        return None


class ChatPane(Widget):
    BINDINGS = [Binding("escape", "cancel_reply", "Cancel reply", show=False),
                Binding("tab", "swap_focus", "Messages ⇄ text box", show=False, priority=True)]

    def action_swap_focus(self) -> None:
        log, inp = self.query_one("#chatlog", OptionList), self.query_one("#cin", Input)
        if inp.has_focus:
            log.focus()
            if log.highlighted is None and log.option_count:
                log.highlighted = log.option_count - 1
        else:
            inp.focus()

    def __init__(self, **kw):
        super().__init__(**kw)
        self.last = 0
        self.dseq = None
        self.rseq = None
        self.loaded = False
        self.msgs: list[dict] = []
        self.reply: dict | None = None
        self.mute = None
        self.slow = 0
        self.slow_until = 0.0
        self.ty_on = False
        self.ty_sent = 0.0
        self.ty_timer = None
        self.fail = 0

    def compose(self) -> ComposeResult:
        yield Static(Text.assemble(("GLOBAL CHAT", f"bold {RED}"), ("  ● LIVE", f"{C.ok}")), classes="panel-title", id="chathead")
        yield OptionList(id="chatlog")
        yield Static("", id="typing")
        yield Static("", id="replybar")
        yield Static("", id="chatnote")
        with Horizontal(classes="composer"):
            yield Input(placeholder="Message everyone…   (F1 help · Tab to pick a message · → completes @names)",
                        id="cin", max_length=300, suggester=ChatSuggester(self.app))
            yield Button("Send", id="csend")

    def on_mount(self) -> None:
        self.query_one("#replybar").display = False
        self.query_one("#chatnote").display = False
        self.poll_loop()
        self.typing_loop()

    # ---------- polling ----------
    @work(group="chatpoll", exclusive=True)
    async def poll_loop(self) -> None:
        while True:
            await self.poll()
            await asyncio.sleep(3 * (1 + self.fail))

    async def poll(self) -> None:
        q = f"/api/chat?since={self.last}"
        if self.dseq is not None:
            q += f"&dseq={self.dseq}"
        if self.rseq is not None:
            q += f"&rseq={self.rseq}"
        r = await self.app.api.j(q, retries=0)
        if r.get("_signed_out"):
            return
        if r.get("error"):
            self.fail = min(self.fail + 1, 5)
            self.query_one("#chathead", Static).update(Text.assemble(("GLOBAL CHAT", f"bold {RED}"), (f"  ○ {r['error']}", f"{C.warn}")))
            return
        if self.fail:
            self.query_one("#chathead", Static).update(Text.assemble(("GLOBAL CHAT", f"bold {RED}"), ("  ● LIVE", f"{C.ok}")))
        self.fail = 0
        initial = not self.loaded
        self.loaded = True
        new = [m for m in r.get("messages") or [] if m.get("id", 0) > self.last]
        log = self.query_one("#chatlog", OptionList)
        at_end = log.highlighted is None or log.highlighted >= log.option_count - 1 or not log.has_focus
        me_id = self.app.me.get("id")
        for m in new:
            prev = self.msgs[-1] if self.msgs else None
            self.msgs.append(m)
            self.last = max(self.last, m["id"])
            log.add_option(Option(self.render_msg(m, prev), id=f"c{m['id']}"))
            if not initial and m.get("ping") and m.get("uid") != me_id:
                self.app.bell()
                self.app.notify(f"{m.get('username')}: {self.app.plain(m.get('text') or '')[:120]}", title="You were mentioned")
        trimmed = False
        while len(self.msgs) > 300:
            self.msgs.pop(0)
            trimmed = True
        if trimmed:
            self.redraw()
        if new and at_end:
            log.scroll_end(animate=False)
            if log.has_focus:
                log.highlighted = log.option_count - 1
        if r.get("deleted"):
            gone = set(r["deleted"])
            if any(m["id"] in gone for m in self.msgs):
                self.msgs = [m for m in self.msgs if m["id"] not in gone]
                for m in self.msgs:
                    if (m.get("reply") or {}).get("id") in gone:
                        m["reply"]["gone"] = True
                if self.reply and self.reply["id"] in gone:
                    self.set_reply(None)
                    self.note("The message you were replying to was deleted")
                self.redraw()
        if isinstance(r.get("dseq"), int):
            self.dseq = r["dseq"]
        if isinstance(r.get("rseq"), int):
            self.rseq = r["rseq"]
        if r.get("ev") is not None and r.get("ev") != self.app.emoji_ev:
            self.app.load_emojis()
        for sid, rx in (r.get("rx") or {}).items():
            self.set_rx(int(sid), rx)
        self.mute = r.get("mute")
        if isinstance(r.get("slow"), int):
            self.slow = r["slow"]
            if r.get("slow_wait"):
                self.slow_until = time.time() + r["slow_wait"]
        self.show_state()

    def set_rx(self, mid: int, rx: list) -> None:
        for m in self.msgs:
            if m["id"] == mid:
                m["rx"] = rx
                self.refresh_msg(mid)
                return

    def refresh_msg(self, mid: int) -> None:
        # redraw one message (reaction change, or picture loaded)
        for k, m in enumerate(self.msgs):
            if m["id"] == mid:
                try:
                    log = self.query_one("#chatlog", OptionList)
                    at_end = log.scroll_y >= log.max_scroll_y - 1
                    log.replace_option_prompt(f"c{mid}", self.render_msg(m, self.msgs[k - 1] if k else None))
                    if at_end:
                        self.call_after_refresh(log.scroll_end, animate=False)
                except Exception:  # noqa: BLE001
                    pass
                return

    def redraw(self) -> None:
        log = self.query_one("#chatlog", OptionList)
        hi = log.highlighted_option.id if log.highlighted_option else None
        log.clear_options()
        prev = None
        for m in self.msgs:
            log.add_option(Option(self.render_msg(m, prev), id=f"c{m['id']}"))
            prev = m
        if hi:
            try:
                log.highlighted = log.get_option_index(hi)
            except Exception:  # noqa: BLE001
                pass
        else:
            log.scroll_end(animate=False)

    def render_msg(self, m: dict, prev: dict | None):
        grp = prev is not None and not m.get("reply") and prev.get("uid") == m.get("uid") and m.get("ts", 0) - prev.get("ts", 0) < 300
        pics = self.app.pics
        redraw = lambda mid=m["id"]: self.refresh_msg(mid)   # noqa: E731
        t = Text()
        if not grp:
            t.append_text(self.app.name_text(m))
            t.append(f"  {hhmm(m.get('ts'))}", style=DIM)
            if m.get("ping"):
                t.append("  @you", style=f"bold {C.warn}")
        rp = m.get("reply")
        if rp:
            t.append("\n↩ ", style=DIM)
            if rp.get("gone"):
                t.append("original message unavailable", style=f"italic {DIM}")
            else:
                t.append(f"{rp.get('username', '')}" + (" (you)" if m.get("rp") else "") + ": ", style=f"bold {DIM}")
                t.append(self.app.plain(rp.get("text") or "")[:90].replace("\n", " ") or "🖼 picture", style=f"italic {DIM}")
        body = m.get("text") or ""
        if body:
            if t:
                t.append("\n")
            t.append_text(self.app.chat_text(body, m.get("men")))
        md = m.get("media")
        if md:
            if t:
                t.append("\n")
            label = "GIF" if md.get("anim") else "picture"
            if pics.enabled and md.get("url"):
                t.append_text(pics.preview(md["url"], md.get("w"), md.get("h"), 64, 16, label=label, on_ready=redraw))
                t.append(f"\n{label} · i for full size", style=DIM)
            else:
                t.append(f"🖼  {label} {md.get('w', '?')}×{md.get('h', '?')}  (i to view)", style=f"{C.warn}")
        rx = m.get("rx") or []
        if rx:
            t.append("\n")
            for x in rx:
                t.append(f" {self.app.emoji_label(x.get('e'))} {x.get('n', 0)} ", style=f"on {C.sel_strong}" if x.get("me") else f"on {C.code_bg}")
                t.append(" ")
        if pics.enabled:
            av = "" if grp else pics.avatar(m.get("uid"), m.get("av"), m.get("username", ""), 10, 5, on_ready=redraw)
            return with_avatar(av, t, 10, f"on {C.ping_bg}" if m.get("ping") else None)
        return indent(t, "▌ " if m.get("ping") else "  ", f"{C.warn}")

    # ---------- composer state ----------
    def show_state(self) -> None:
        inp = self.query_one("#cin", Input)
        if self.mute:
            mu = self.mute
            until = "permanently" if mu.get("perm") or not mu.get("until") else f"until {full(mu.get('until'))}"
            self.note(f"You're muted {until}" + (f": {mu['reason']}" if mu.get("reason") else ""))
            inp.disabled = True
            return
        inp.disabled = False
        if self.slow and not self.app.me.get("staff"):
            left = int(self.slow_until - time.time())
            self.query_one("#chathead", Static).update(Text.assemble(("GLOBAL CHAT", f"bold {RED}"), ("  ● LIVE", f"{C.ok}"),
                                                                     (f"  ⏱ slowmode {self.slow}s" + (f" · wait {left}s" if left > 0 else ""), f"{C.warn}")))

    def note(self, t: str) -> None:
        n = self.query_one("#chatnote", Static)
        n.update(t)
        n.display = bool(t)
        if t:
            self.set_timer(6, lambda: n.update("") or setattr(n, "display", False))

    def set_reply(self, m: dict | None) -> None:
        self.reply = m
        bar = self.query_one("#replybar", Static)
        if m:
            bar.update(Text(f"↩ replying to {m.get('username')}: {self.app.plain(m.get('text') or '')[:70]}   (Esc to cancel)"))
        bar.display = bool(m)

    def action_cancel_reply(self) -> None:
        self.set_reply(None)

    # ---------- typing ----------
    @work(group="typing", exclusive=True)
    async def typing_loop(self) -> None:
        while True:
            r = await self.app.api.j("/api/chat/typing", retries=0)
            if r.get("_signed_out"):
                return
            ty = [x for x in (r.get("typing") or []) if x.get("id") != self.app.me.get("id")]
            w = self.query_one("#typing", Static)
            if ty:
                names = ", ".join(x.get("username", "?") for x in ty[:3]) + (f" +{len(ty) - 3}" if len(ty) > 3 else "")
                w.update(Text(f"{names} {'is' if len(ty) == 1 else 'are'} typing…", style=DIM))
            else:
                w.update("")
            await asyncio.sleep(2)

    def _ty_post(self, on_: bool) -> None:
        self.run_worker(self.app.api.j("/api/chat/typing", {"channel": "global", "typing": on_}, retries=0), group="typost")

    def _ty_stop(self) -> None:
        if self.ty_timer:
            self.ty_timer.stop()
            self.ty_timer = None
        if self.ty_on:
            self.ty_on = False
            self._ty_post(False)

    @on(Input.Changed, "#cin")
    def _typing(self, e: Input.Changed) -> None:
        if not e.value.strip() or e.value.startswith("/"):
            self._ty_stop()
            return
        now = time.time()
        if not self.ty_on or now - self.ty_sent > 2:
            self.ty_on, self.ty_sent = True, now
            self._ty_post(True)
        if self.ty_timer:
            self.ty_timer.stop()
        self.ty_timer = self.set_timer(2.5, self._ty_stop)

    # ---------- sending ----------
    @on(Input.Submitted, "#cin")
    @on(Button.Pressed, "#csend")
    def _send(self) -> None:
        inp = self.query_one("#cin", Input)
        t = inp.value.strip()
        if not t:
            return
        if self.mute:
            return
        if self.slow_until > time.time() and not self.app.me.get("staff"):
            self.note(f"Slowmode: wait {int(self.slow_until - time.time()) + 1}s")
            return
        dropped = dropped_path(t)
        if dropped:
            inp.value = ""
            if dropped.suffix.lower() in PICTURE_EXT:
                self.send_image(str(dropped), "")
            else:
                self.note("Only pictures can be sent in global chat (PNG, JPG, WebP, GIF). Files go in Messages.")
            return
        if t.startswith("/img ") or t == "/img":
            m = re.match(r"/img\s+(\"[^\"]+\"|'[^']+'|\S+)\s*(.*)$", t)
            if not m:
                self.note("Usage: /img ~/path/to/picture.jpg [caption]")
                return
            inp.value = ""
            self.send_image(m.group(1).strip("'\""), m.group(2))
            return
        if t in ("/help", "/?"):
            inp.value = ""
            self.app.action_help()
            return
        inp.value = ""
        self._ty_stop()
        body = {"text": t}
        if self.reply:
            body["reply_to"] = self.reply["id"]
        self.send(body, t)

    @work(group="chatsend")
    async def send(self, body: dict, text: str) -> None:
        r = await self.app.api.j("/api/chat", body)
        if r.get("error") and r["error"] != "empty":
            inp = self.query_one("#cin", Input)
            if text and not inp.value:
                inp.value = text
            self.note(r["error"])
            if r.get("muted"):
                self.mute = r["muted"]
                self.show_state()
            if isinstance(r.get("slow"), int):
                self.slow = r["slow"]
                self.slow_until = time.time() + (r.get("wait") or 0)
            if self.reply and "no longer exists" in r["error"]:
                self.set_reply(None)
            return
        self.set_reply(None)
        if self.slow and not self.app.me.get("staff"):
            self.slow_until = time.time() + self.slow
        await self.poll()
        log = self.query_one("#chatlog", OptionList)
        log.scroll_end(animate=False)

    @work(group="chatimg")
    async def send_image(self, path: str, caption: str) -> None:
        p = Path(path).expanduser()
        lv, req = self.app.me.get("level") or 0, (self.app.me.get("lvl_req") or {})
        is_gif = p.suffix.lower() == ".gif"
        need = req.get("chat_gif" if is_gif else "chat_img")
        if need and lv < need and "owner" not in (self.app.me.get("roles") or []):
            self.note(f"{'GIFs' if is_gif else 'Pictures'} unlock at level {need} - you're level {lv}.")
            return
        try:
            data, ctype = await asyncio.to_thread(prepare_image, p)
        except Exception as e:  # noqa: BLE001
            self.note(str(e))
            return
        self.note(f"Uploading {p.name}…")
        r = await self.app.api.upload("/api/chat/media", data, ctype)
        md = (r.get("media") or {}).get("id")
        if r.get("error") or not md:
            self.note(r.get("error") or "The upload failed")
            return
        body = {"text": caption.strip(), "media": md}
        if self.reply:
            body["reply_to"] = self.reply["id"]
        self.note("")
        self.send(body, "")

    # ---------- message actions ----------
    def cur(self) -> dict | None:
        o = self.query_one("#chatlog", OptionList).highlighted_option
        if not o:
            return None
        mid = int(o.id[1:])
        return next((m for m in self.msgs if m["id"] == mid), None)

    def on_key(self, event) -> None:
        log = self.query_one("#chatlog", OptionList)
        if not log.has_focus:
            return
        fn = {"r": self.act_reply, "e": self.act_react, "d": self.act_delete, "m": self.act_mention,
              "p": self.act_profile, "i": self.act_view}.get(event.key)
        if fn:
            event.stop()
            fn()

    @on(OptionList.OptionSelected, "#chatlog")
    def _menu(self) -> None:
        m = self.cur()
        if not m:
            return
        me = self.app.me
        opts = [("reply", "Reply (r)"), ("react", "React (e)"), ("mention", "Mention (m)"), ("profile", "Profile (p)")]
        if m.get("media"):
            opts.append(("view", "View picture (i)"))
        if m.get("uid") == me.get("id") or me.get("staff"):
            opts.append(("delete", "Delete (d)"))
        if me.get("staff") and m.get("uid") != me.get("id"):
            opts.append(("mute", "Mute this person"))
        self.app.push_screen(Choose("Message", opts, "reply"), lambda v: {
            "reply": self.act_reply, "react": self.act_react, "mention": self.act_mention, "profile": self.act_profile,
            "view": self.act_view, "delete": self.act_delete, "mute": self.act_mute}.get(v, lambda: None)())

    def act_reply(self) -> None:
        m = self.cur()
        if m:
            self.set_reply(m)
            self.query_one("#cin", Input).focus()

    def act_mention(self) -> None:
        m = self.cur()
        if m:
            inp = self.query_one("#cin", Input)
            inp.value = (inp.value + " " if inp.value and not inp.value.endswith(" ") else inp.value) + f"@{m.get('username')} "
            inp.focus()
            inp.cursor_position = len(inp.value)

    def act_profile(self) -> None:
        m = self.cur()
        if m:
            self.app.open_profile(m["uid"])

    def act_view(self) -> None:
        m = self.cur()
        if m and m.get("media"):
            self.app.push_screen(ImageView(f"Picture from {m.get('username')}", m["media"]["url"]))

    def act_react(self) -> None:
        m = self.cur()
        if not m:
            return
        opts = [(e, e) for e in QUICK_REACTS] + [(f"c:{e['id']}", f":{e['name']}:") for e in self.app.emojis[:40]]
        mine = {x.get("e") for x in m.get("rx") or [] if x.get("me")}
        opts = [(k, label + ("  ✓ (remove)" if k in mine else "")) for k, label in opts]
        self.app.push_screen(Choose("React with", opts, QUICK_REACTS[0]), lambda v: v and self.react(m["id"], v))

    @work(group="react")
    async def react(self, mid: int, emoji: str) -> None:
        r = await self.app.api.j("/api/chat/react", {"msg_id": mid, "emoji": emoji})
        if r.get("error"):
            self.note(r["error"])
            return
        self.set_rx(int(r.get("id") or mid), r.get("rx") or [])

    def act_delete(self) -> None:
        m = self.cur()
        if not m:
            return
        own = m.get("uid") == self.app.me.get("id")
        if not own and not self.app.me.get("staff"):
            self.note("You can only delete your own messages")
            return
        self.app.push_screen(Confirm("Delete message", ("Delete your message for everyone? This can't be undone." if own else
                                                        f"Delete {m.get('username')}'s message?"), "Delete", True),
                             lambda ok: ok and self.delete(m["id"]))

    @work(group="del")
    async def delete(self, mid: int) -> None:
        r = await self.app.api.j(f"/api/chat/{mid}", method="DELETE")
        if r.get("error") and "No such message" not in r["error"]:
            self.note(r["error"])
            return
        self.msgs = [m for m in self.msgs if m["id"] != mid]
        self.redraw()

    def act_mute(self) -> None:
        m = self.cur()
        if not m:
            return
        durs = [("300", "5 minutes"), ("3600", "1 hour"), ("86400", "1 day"), ("604800", "7 days"), ("0", "Until lifted")]

        def got(d):
            if d is None:
                return
            self.app.push_screen(Prompt(f"Mute {m.get('username')}", "reason (optional)", max_length=120),
                                 lambda reason: reason is not None and self.run_worker(self._mute(m["uid"], int(d), reason)))
        self.app.push_screen(Choose(f"Mute {m.get('username')} for", durs, "3600"), got)

    async def _mute(self, uid: int, secs: int, reason: str) -> None:
        r = await self.app.api.j("/api/chat/mute", {"user_id": uid, "seconds": secs, "reason": reason})
        self.app.notify(r.get("error") or "Muted", severity="error" if r.get("error") else "information")


def prepare_image(p: Path) -> tuple[bytes, str]:
    # shrink and re-encode like the site does; also strips metadata
    from PIL import Image, ImageOps
    if not p.is_file():
        raise ValueError(f"No file at {p}")
    raw = p.read_bytes()
    with Image.open(io.BytesIO(raw)) as im:
        fmt = (im.format or "").upper()
        if fmt == "GIF":
            if len(raw) > 8 * 1048576:
                raise ValueError("GIFs can be at most 8 MB")
            return raw, "image/gif"
        if fmt not in ("PNG", "JPEG", "WEBP", "MPO"):
            raise ValueError("Only PNG, JPG, WebP and GIF pictures can be sent")
        im = ImageOps.exif_transpose(im)
        im.thumbnail((2048, 2048))
        buf = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P") and fmt == "PNG":
            im.save(buf, "PNG", optimize=True)
            ctype = "image/png"
        else:
            im.convert("RGB").save(buf, "JPEG", quality=88)
            ctype = "image/jpeg"
    data = buf.getvalue()
    if len(data) > 5 * 1048576:
        raise ValueError("That picture is too large even after shrinking it")
    return data, ctype


# ====================================================================== news

class NewsPane(Widget):
    BINDINGS = [Binding("ctrl+r", "load", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Label("ANNOUNCEMENTS", classes="panel-title")
        with VerticalScroll(id="newsview"):
            yield Static("Loading…", id="newsbody")

    def on_show(self) -> None:
        self.action_load()

    @work(exclusive=True)
    async def action_load(self) -> None:
        body = self.query_one("#newsbody", Static)
        site = await self.app.api.j("/api/site")
        if site.get("announcements_enabled") is False:
            body.update(Text("Announcements are switched off on the site right now.", style=DIM))
            return
        r = await self.app.api.j("/api/announcements")
        if r.get("error"):
            body.update(Text(r["error"], style=f"{C.err}"))
            return
        items = r.get("announcements") or []
        if not items:
            body.update(Text("No announcements.", style=DIM))
            return
        t = Text()
        for k, a in enumerate(items):
            if k:
                t.append("\n\n" + "─" * 60 + "\n\n", style=f"{C.inactive}")
            if a.get("pinned"):
                t.append(" PINNED ", style=f"bold {C.bg} on {C.warn}")
                t.append(" ")
            pr = a.get("priority")
            if pr and pr != "normal":
                t.append(f" {pr.upper()} ", style=f"bold {C.bg} on {'{C.accent}' if pr == 'critical' else '#ff8a5c'}")
                t.append(" ")
            t.append(a.get("title") or "", style=f"bold {RED}")
            when = a.get("published_at") or a.get("created")
            t.append(f"\n{a.get('author') or 'Admin'} · {full(when)}" + (f" · expires {full(a['expires'])}" if a.get("expires") else ""), style=DIM)
            t.append("\n\n")
            t.append_text(self.app.chat_text(a.get("body") or ""))
        body.update(t)


# ====================================================================== profile

class ProfileScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q", "dismiss(None)", "Close")]

    def __init__(self, uid: int):
        super().__init__()
        self.uid = uid
        self.p: dict = {}

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            with VerticalScroll():
                yield Static("", id="pbanner")
                with Horizontal(id="phead"):
                    yield Static("", id="pavatar")
                    yield Static("Loading…", id="pbody")
            with Horizontal(classes="row", id="pbtns"):
                yield Button("Message", id="pmsg", classes="-primary")
                yield Button("Add friend", id="pfriend")
                yield Button("+ Rep", id="pup")
                yield Button("- Rep", id="pdown")
                yield Button("Edit bio", id="pbio")
                yield Button("Close", id="pclose")

    def on_mount(self) -> None:
        mine = self.uid == self.app.me.get("id")
        for b in ("pmsg", "pfriend", "pup", "pdown"):
            self.query_one(f"#{b}").display = not mine
        self.query_one("#pbio").display = mine
        self.load()

    @work(exclusive=True)
    async def load(self) -> None:
        r = await self.app.api.j(f"/api/profile/{self.uid}")
        if r.get("error"):
            self.query_one("#pbody", Static).update(Text(r["error"], style=f"{C.err}"))
            return
        self.p = p = r.get("profile") or {}
        self.draw_avatar()
        t = Text()
        t.append_text(self.app.name_text(p))
        if p.get("level"):
            t.append(f"   Lv {p['level']}", style=f"bold {C.warn}")
        now = p.get("now") or time.time()
        on_ = p.get("last_seen") and now - p["last_seen"] < 60
        t.append("   ● online" if on_ else (f"   ○ last seen {ago(p['last_seen'])}" if p.get("last_seen") else ""),
                 style=f"{C.ok}" if on_ else DIM)
        roles = self.app.roles_of(p, "profile")
        if roles:
            t.append("\n")
            for r_ in roles:
                t.append(f" {r_.get('label', r_.get('id'))} ", style=f"bold {C.bg} on {r_.get('color') or '{C.muted}'}")
                t.append(" ")
        if p.get("created"):
            t.append(f"\nJoined {p['created']}", style=DIM)
        if p.get("rep") is not None and not p.get("rep_exempt"):
            t.append(f"   Reputation {p['rep']}", style=DIM)
            if p.get("my_vote"):
                t.append(" (you voted " + ("+" if p["my_vote"] > 0 else "-") + ")", style=DIM)
        if (p.get("ml") or {}).get("t") and on_:
            t.append(f"\n♪ Listening to {p['ml']['t']}", style=f"{C.music}")
        if (p.get("vc") or {}).get("name") and on_:
            t.append(f"\n🎙 In voice: {p['vc']['name']}", style=f"{C.ok}")
        if p.get("theme"):
            th = p["theme"]
            t.append(f"\n♫ Profile song: {th.get('name', '')}" + (f" - {th['artist']}" if th.get("artist") else ""), style=DIM)
        t.append("\n\n")
        if p.get("bio"):
            t.append_text(self.app.chat_text(p["bio"]))
        elif p.get("bio_hidden"):
            t.append("(bio hidden by the word filter)", style=f"italic {DIM}")
        else:
            t.append("No bio yet.", style=f"italic {DIM}")
        for s in p.get("socials") or []:
            u = s.get("u") or ""
            t.append(f"\n{s.get('p', '')}: ", style=f"bold {RED}")
            if u.startswith("https://"):
                t.append(s.get("d") or u, style=f"underline {LINK} link {u}")
            else:
                t.append(s.get("d") or "")
        if p.get("muted"):
            mu = p["muted"]
            t.append(f"\n\nMuted {'permanently' if mu.get('perm') else 'until ' + full(mu.get('until'))}" + (f": {mu['reason']}" if mu.get("reason") else ""),
                     style=f"{C.warn}")
        fr = await self.app.api.j(f"/api/forums/user/{self.uid}")
        if not fr.get("error") and (fr.get("threads") or fr.get("replies")):
            th, rp = int(fr.get("threads") or 0), int(fr.get("replies") or 0)
            t.append(f"\n\nForums: {th} thread{'' if th == 1 else 's'} · {rp} repl{'y' if rp == 1 else 'ies'}", style=DIM)
        self.query_one("#pbody", Static).update(t)
        s = self.app.social_sum
        fb = self.query_one("#pfriend", Button)
        if any(f.get("id") == self.uid for f in s.get("friends") or []):
            fb.label, fb.disabled = "Friends ✓", True
        elif any(f.get("id") == self.uid for f in s.get("outgoing") or []):
            fb.label, fb.disabled = "Request sent", True
        elif any(f.get("id") == self.uid for f in s.get("incoming") or []):
            fb.label = "Accept friend request"

    def draw_avatar(self) -> None:
        p, pics = self.p, self.app.pics
        uid = p.get("id", self.uid)
        self.query_one("#pavatar", Static).update(
            pics.avatar(uid, p.get("av"), p.get("username", ""), 32, 16, on_ready=self.draw_avatar, mode=pics.mode))
        banner = self.query_one("#pbanner", Static)
        bv = p.get("bv") or 0
        banner.display = bool(pics.enabled and bv and bv > 0)
        if banner.display:
            banner.update(pics.preview(f"/api/banner/{uid}?v={bv}", None, None, 80, 9, label="banner",
                                       on_ready=self.draw_avatar))

    @on(Button.Pressed)
    async def _btn(self, e: Button.Pressed) -> None:
        b = e.button.id
        if b == "pclose":
            self.dismiss(None)
        elif b == "pmsg":
            self.dismiss(None)
            self.app.open_dm(self.uid)
        elif b == "pfriend":
            incoming = any(f.get("id") == self.uid for f in self.app.social_sum.get("incoming") or [])
            r = await self.app.api.j("/api/friends/accept" if incoming else "/api/friends/request", {"uid": self.uid})
            if r.get("error"):
                self.app.notify(r["error"], severity="error")
            else:
                self.app.notify("You're now friends" if incoming or r.get("friends") else "Friend request sent")
                await self.app.load_social()
                self.load()
        elif b in ("pup", "pdown"):
            r = await self.app.api.j(f"/api/rep/{self.uid}", {"dir": 1 if b == "pup" else -1})
            if r.get("error"):
                self.app.notify(r["error"], severity="error")
            else:
                self.load()
        elif b == "pbio":
            def done(v):
                if v is not None:
                    self.run_worker(self._save_bio(v))
            self.app.push_screen(Prompt("Your bio", value=self.app.plain(self.p.get("bio") or ""), multiline=True, ok="Save",
                                        help="Up to 500 characters. :emoji: names work."), done)

    async def _save_bio(self, v: str) -> None:
        r = await (self.app.api.j("/api/bio", {"bio": v}) if v.strip() else self.app.api.j("/api/bio", method="DELETE"))
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
        self.load()


# ====================================================================== main screen

TABS = [("chat", "Chat"), ("dms", "Messages"), ("forums", "Forums"), ("news", "News"), ("img", "Image Data")]


class MainScreen(Screen):
    BINDINGS = [
        Binding("f1", "app.help", "Help"),
        Binding("f2", "tab('chat')", "Chat"),
        Binding("f3", "tab('dms')", "Messages"),
        Binding("f4", "tab('forums')", "Forums"),
        Binding("f5", "tab('news')", "News"),
        Binding("f6", "tab('img')", "Image Data"),
        Binding("ctrl+b", "toggle_members", "Members"),
        Binding("f7", "toggle_pics", "Pictures"),
        Binding("f8", "pic_mode", "Sharpness"),
        Binding("f9", "toggle_transparent", "See-through"),
        Binding("f10", "app.logout_ask", "Log out"),
    ]

    def __init__(self):
        super().__init__()
        self._restore, self._why = "", ""
        try:                 # after a restart, reopen the previous tab
            f = CONF_DIR / "devstate.json"
            st = json.loads(f.read_text())
            f.unlink()
            self._restore, self._why = st.get("tab") or "", st.get("why") or ""
        except (OSError, ValueError):
            pass

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("JIINSEC", classes="brand")
            yield Static("Stay safe online", classes="sub")
            yield Static("", id="who")
        with Horizontal(id="body"):
            with TabbedContent(id="tabs", initial=self._restore or "chat"):
                with TabPane("Chat", id="chat"):
                    yield ChatPane(id="chatpane")
                with TabPane("Messages", id="dms"):
                    yield SocialPane(id="social")
                with TabPane("Forums", id="forums"):
                    yield ForumsPane(id="forumspane")
                with TabPane("News", id="news"):
                    yield NewsPane(id="newspane")
                with TabPane("Image Data", id="img"):
                    yield ImagePane(id="imgpane")
            with Vertical(id="members"):
                yield Static("MEMBERS", classes="panel-title", id="memtitle")
                yield OptionList(id="memlist")
        yield Footer()

    def on_mount(self) -> None:
        self.app.main = self
        self.app.draw_who()
        self.members_loop()
        self.me_loop()
        self.social_loop()
        self.app.load_roles()
        self.app.load_emojis()
        self.call_after_refresh(self.action_tab, self._restore or "chat")   # also focuses the tab
        if self._why:
            self.app.notify(self._why + (f" - now using “{C.name}”" if self._why.startswith("Theme") else ""), timeout=3)

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab
        focus = {"chat": "#cin", "dms": "#dmconvs", "forums": "#forumlist", "img": "#imgpath"}.get(tab)
        if focus:
            try:
                self.query_one(focus).focus()
            except Exception:  # noqa: BLE001
                pass

    @on(TabbedContent.TabActivated)
    def _tab(self, e: TabbedContent.TabActivated) -> None:
        if e.pane.id == "chat":
            self.call_after_refresh(lambda: self.query_one("#cin").focus())

    def action_toggle_members(self) -> None:
        self.query_one("#members").toggle_class("hidden")

    def _redraw_pictures(self) -> None:
        self.query_one("#chatpane", ChatPane).redraw()
        sp = self.query_one("#social", SocialPane)
        if sp.sum:
            sp.set_summary(sp.sum, reload_conv=False)
        if sp.open:
            sp._draw_msgs()
        self.draw_members()

    def action_pic_mode(self) -> None:
        from .pictures import MODE_ORDER, MODES
        pics = self.app.pics
        pics.mode = MODE_ORDER[(MODE_ORDER.index(pics.mode) + 1) % len(MODE_ORDER)]
        self.app.save_prefs()
        self._redraw_pictures()
        self.app.notify(f"Pictures: {MODES[pics.mode][2]}. F8 to switch again"
                        + (" - if you see boxes or gaps, your font lacks these characters" if pics.mode == "sext" else ""),
                        timeout=4)

    def action_toggle_transparent(self) -> None:
        app = self.app
        app.transparent = not app.transparent
        app.set_class(app.transparent, "-transparent")
        app.ansi_color = app.transparent
        app.save_prefs()
        app.notify("See-through background on (set the amount in ~/.config/kitty/kitty.conf)" if app.transparent
                   else "Solid background", timeout=3)

    def action_toggle_pics(self) -> None:
        pics = self.app.pics
        pics.enabled = not pics.enabled
        self.app.save_prefs()
        self._redraw_pictures()
        self.app.notify("Pictures shown in messages" if pics.enabled else "Pictures hidden - press i on a message to view one",
                        timeout=3)

    # ---------- members ----------
    @work(group="members", exclusive=True)
    async def members_loop(self) -> None:
        sig = None
        while True:
            r = await self.app.api.j("/api/members", retries=0)
            if r.get("_signed_out"):
                return
            if r.get("members") is not None:
                self.app.mem_now = r.get("now") or time.time()
                self.app.members = {u["id"]: u for u in r["members"]}
                if r.get("rv") is not None and r["rv"] != self.app.roles_ver:
                    self.app.load_roles()
                new_sig = repr([(u["id"], u.get("username"), tuple(u.get("roles") or []), self.app.online(u), bool(u.get("vc")),
                                 (u.get("ml") or {}).get("t")) for u in r["members"]]) + str(self.app.roles_ver)
                if new_sig != sig:
                    sig = new_sig
                    self.draw_members()
            await asyncio.sleep(10)

    def draw_members(self) -> None:
        app = self.app
        ol = self.query_one("#memlist", OptionList)
        keep = ol.highlighted_option.id if ol.highlighted_option else None
        ol.clear_options()
        users = list(app.members.values())
        online = [u for u in users if app.online(u)]
        offline = sorted([u for u in users if not app.online(u)], key=lambda u: -(u.get("last_seen") or 0))
        buckets: dict[str, list] = {}
        order = []
        for r in app.roles:
            if r.get("off") or (r.get("show") or {}).get("members") is False or (r.get("show") or {}).get("sep") is False:
                continue
            order.append(r)
        rest = []
        for u in sorted(online, key=lambda u: u.get("username", "").lower()):
            g = next((r for r in app.roles_of(u, "members") if (r.get("show") or {}).get("sep") is not False), None)
            if g:
                buckets.setdefault(g["id"], []).append(u)
            else:
                rest.append(u)
        self.query_one("#memtitle", Static).update(Text.assemble(("MEMBERS ", f"bold {RED}"), (f"{len(online)} online / {len(users)}", DIM)))

        def row(u, dim=False):
            t = Text()
            t.append("● " if not dim else "○ ", style=f"{C.ok}" if not dim else f"{C.faint}")
            nt = app.name_text(u)
            if dim:
                nt.stylize(DIM)
            t.append_text(nt)
            if not dim:
                if u.get("vc"):
                    t.append(" 🎙", style=f"{C.ok}")
                if "m" in (u.get("dev") or []) and "d" not in (u.get("dev") or []):
                    t.append(" 📱", style=DIM)
                if (u.get("ml") or {}).get("t"):
                    t.append(f"\n  ♪ {u['ml']['t'][:22]}", style=f"{C.music}")
                elif (u.get("vc") or {}).get("name"):
                    t.append(f"\n  in {u['vc']['name'][:22]}", style=f"{C.ok}")
                if app.pics.enabled:
                    av = app.pics.avatar(u.get("id"), u.get("av"), u.get("username", ""), 8, 4, on_ready=self._members_pic_ready)
                    return Option(with_avatar(av, t, 8), id=f"u{u['id']}")
            return Option(t, id=f"u{u['id']}")
        for r in order:
            us = buckets.get(r["id"])
            if us:
                ol.add_option(Option(Text(f"{r.get('label', r['id']).upper()} — {len(us)}", style=f"bold {r.get('color') or RED}"), disabled=True))
                for u in us:
                    ol.add_option(row(u))
        if rest:
            ol.add_option(Option(Text(f"ONLINE USERS — {len(rest)}", style=f"bold {C.ok}"), disabled=True))
            for u in rest:
                ol.add_option(row(u))
        if offline:
            ol.add_option(Option(Text(f"OFFLINE USERS — {len(offline)}", style=f"bold {DIM}"), disabled=True))
            for u in offline[:200]:
                ol.add_option(row(u, dim=True))
        if keep:
            try:
                ol.highlighted = ol.get_option_index(keep)
            except Exception:  # noqa: BLE001
                pass

    def _members_pic_ready(self) -> None:
        if getattr(self, "_mem_redraw", False):
            return
        self._mem_redraw = True

        def go():
            self._mem_redraw = False
            self.draw_members()
        self.set_timer(0.2, go)

    @on(OptionList.OptionSelected, "#memlist")
    def _member(self, e: OptionList.OptionSelected) -> None:
        if (e.option.id or "").startswith("u"):
            self.app.open_profile(int(e.option.id[1:]))

    # ---------- me ----------
    @work(group="me", exclusive=True)
    async def me_loop(self) -> None:
        while True:
            await asyncio.sleep(15)
            r = await self.app.api.j("/api/me", retries=0)
            if r.get("_signed_out"):
                return
            if r.get("user"):
                self.app.me.update(r["user"])
                self.app.draw_who()
                self.app.set_badge("forums", int(self.app.me.get("fm_unread") or 0))
                if r["user"].get("rv") is not None and r["user"]["rv"] != self.app.roles_ver:
                    self.app.load_roles()
            elif "user" in r and r["user"] is None:
                self.app.signed_out()
                return

    # ---------- social long-poll ----------
    @work(group="social", exclusive=True)
    async def social_loop(self) -> None:
        await self.app.load_social()
        fail = 0
        while True:
            t0 = time.monotonic()
            r = await self.app.api.j(f"/api/social/poll?v={self.app.social_v}", retries=0, timeout=90)
            if r.get("_signed_out"):
                return
            if r.get("error"):
                fail += 1
                await asyncio.sleep(min(15, 1.5 * fail))
                continue
            fail = 0
            if r.get("v") != self.app.social_v:
                self.app.social_v = r.get("v") or 0
                await self.app.load_social()
            elif time.monotonic() - t0 < 1:
                await asyncio.sleep(2)   # empty reply came back instantly, avoid busy-looping


# ====================================================================== app

class JiinApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "JIINSEC"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("ctrl+q", "quit", "Quit", priority=True)]

    def __init__(self, dev: bool = False):
        # dev mode: css edits apply live, py edits restart via the launcher loop
        super().__init__(watch_css=dev)
        self.dev = dev
        self.api = Api(self)
        self.pics = Pictures(self.api.http.raw)
        from .pictures import KITTY
        self.transparent = KITTY          # transparent by default in kitty
        self.load_prefs()
        self.me: dict = {}
        self.members: dict[int, dict] = {}
        self.mem_now = 0.0
        self.roles: list[dict] = FALLBACK_ROLES
        self.roles_ver = None
        self.emojis: list[dict] = []
        self.emoji_ev = None
        self.social_sum: dict = {}
        self.social_v = 0
        self.seen_convs: dict[str, float] = {}
        self.notes_primed = False
        self.main: MainScreen | None = None
        self._out = False

    def on_mount(self) -> None:
        self.register_theme(Theme(name="jiin", primary=f"{C.accent}", secondary=f"{C.border}", accent=f"{C.accent}", warning=f"{C.warn}",
                                  error=f"{C.err}", success=f"{C.ok}", foreground=f"{C.fg}", background=f"{C.bg}",
                                  surface=f"{C.surface}", panel=f"{C.surface}", dark=lum(C.bg) < 0.4,
                                  variables=textual_variables()))
        self.theme = "jiin"
        self.set_class(self.transparent, "-transparent")
        # keep the terminal default background (otherwise Textual forces a near-black)
        self.ansi_color = self.transparent
        # kitty: let the picture loader write image data straight to the terminal
        self.pics.write = lambda data: self._driver.write(data) if self._driver else None
        self._palette_mtime = palette_mtime()
        self.set_interval(2.0, self._palette_check)
        if self.dev:
            self._py_mtime = self._scan_py()
            self._py_changed = 0.0
            self.set_interval(0.4, self._dev_check)
        self.boot()

    def get_theme_variable_defaults(self) -> dict[str, str]:
        # expose the palette to the stylesheet
        return {**super().get_theme_variable_defaults(), **textual_variables()}

    # ---------- remembered preferences ----------
    def load_prefs(self) -> None:
        try:
            pr = json.loads((CONF_DIR / "prefs.json").read_text())
        except (OSError, ValueError):
            return
        from .pictures import KITTY, MODE_ORDER
        # kitty and text-only terminals remember their mode separately
        mode = pr.get("pic_mode_kitty" if KITTY else "pic_mode")
        if mode in MODE_ORDER:
            self.pics.mode = mode
        self.transparent = pr.get("transparent", KITTY) if KITTY else pr.get("transparent", False)
        if pr.get("pics") is False:
            self.pics.enabled = False

    def save_prefs(self) -> None:
        try:
            CONF_DIR.mkdir(parents=True, exist_ok=True)
            from .pictures import KITTY
            try:
                pr = json.loads((CONF_DIR / "prefs.json").read_text())
            except (OSError, ValueError):
                pr = {}
            pr["pic_mode_kitty" if KITTY else "pic_mode"] = self.pics.mode
            pr["pics"] = self.pics.enabled
            pr["transparent"] = self.transparent
            (CONF_DIR / "prefs.json").write_text(json.dumps(pr))
        except OSError:
            pass

    # ---------- dev mode: restart on code changes ----------
    @staticmethod
    def _scan_py() -> float:
        return max((p.stat().st_mtime for p in Path(__file__).parent.glob("*.py")), default=0.0)

    def _palette_check(self) -> None:
        # Saber rewrote the palette: restart to pick up the new colours
        m = palette_mtime()
        if m and m != self._palette_mtime:
            self._palette_mtime = m
            self._restart("Theme changed")

    def _restart(self, why: str = "") -> None:
        try:
            CONF_DIR.mkdir(parents=True, exist_ok=True)
            tab = self.main.query_one(TabbedContent).active if self.main else ""
            (CONF_DIR / "devstate.json").write_text(json.dumps({"tab": tab, "why": why}))
        except Exception:  # noqa: BLE001
            pass
        self.exit(return_code=3)

    def _dev_check(self) -> None:
        m = self._scan_py()
        if m != self._py_mtime:
            self._py_mtime, self._py_changed = m, time.monotonic()    # debounce a burst of saves
        elif self._py_changed and time.monotonic() - self._py_changed > 0.6:
            self._restart("Reloaded with the latest code")

    @work(exclusive=True, group="boot")
    async def boot(self) -> None:
        if not self.api.http.has_device_cookie():
            try:
                await self.api.http.client.get("/")
                self.api.http.save_cookies()
            except Exception:  # noqa: BLE001
                pass
        r = await self.api.j("/api/me")
        if r.get("user"):
            self.me = r["user"]
            if r["user"].get("tos") is False:
                self.push_screen(LoginScreen("tos"))
            else:
                self.push_screen(MainScreen())
        else:
            self.push_screen(LoginScreen())
            if r.get("error"):
                self.notify(f"Couldn't reach {BASE}: {r['error']}", severity="error", timeout=10)

    async def after_login(self) -> None:
        r = await self.api.j("/api/me")
        if not r.get("user"):
            self.notify(r.get("error") or "Logged in, but the server didn't return your account. Try again.", severity="error")
            return
        self.me = r["user"]
        self._out = False
        if self.me.get("tos") is False:
            self.switch_screen(LoginScreen("tos"))
        else:
            self.switch_screen(MainScreen())

    def signed_out(self) -> None:
        if self._out:
            return
        self._out = True
        self.api.http.forget()
        self.me, self.social_sum, self.social_v, self.main = {}, {}, 0, None
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(LoginScreen())
        self.notify("You're signed out - log in again.", severity="warning")

    def action_logout_ask(self) -> None:
        self.push_screen(Confirm("Log out", "Log out of JIINSEC on this computer?", "Log out"), lambda ok: ok and self.logout())

    @work(group="logout")
    async def logout(self) -> None:
        await self.api.j("/api/logout", {})
        self.signed_out()

    def action_help(self) -> None:
        self.push_screen(TextView("JIINSEC terminal - keys", Text.from_markup(HELP)))

    # ---------- shared helpers used by every pane ----------
    def user(self, ref: dict | None) -> dict:
        ref = ref or {}
        out = {"roles": [], "hb": []}
        out.update(ref)
        m = self.members.get(ref.get("id"))
        if m:
            out.update(m)
        return out

    def find_user(self, name: str) -> dict | None:
        n = name.lower()
        return next((u for u in self.members.values() if u.get("username", "").lower() == n), None)

    def online(self, u: dict) -> bool:
        ls = u.get("last_seen")
        return bool(ls) and (self.mem_now or time.time()) - ls < 60

    def roles_of(self, u: dict, ctx: str) -> list[dict]:
        ids = set(u.get("roles") or [])
        hidden = set(u.get("hb") or [])
        return [r for r in self.roles if r.get("id") in ids and r.get("id") not in hidden and not r.get("off")
                and (r.get("show") or {}).get(ctx) is not False]

    def name_text(self, u: dict, bold: bool = True) -> Text:
        col = f"{C.fg_bright}"
        for r in self.roles_of(u, "chat"):
            if r.get("nc") is not False and r.get("color"):
                col = r["color"]
                break
        return Text(u.get("username") or "?", style=("bold " if bold else "") + col)

    _EMO = re.compile(r"<:([a-z0-9_]{2,32}):(\d{1,9})>")
    _MEN = re.compile(r"(?<![A-Za-z0-9_.@-])@([A-Za-z0-9_.-]{1,40})")
    _URL = re.compile(r"https?://[^\s<>\"']+[^\s<>\"'.,!?;:)]")

    def plain(self, s: str) -> str:
        return self._EMO.sub(lambda m: f":{m.group(1)}:", s or "")

    def chat_text(self, s: str, men: list | None = None) -> Text:
        # render chat text: custom emoji, @mentions and links
        s = s or ""
        me_name = (self.me.get("username") or "").lower()
        known = {x.get("name", "").lower() for x in men} if men is not None else None
        out = Text()
        pos = 0
        pat = re.compile("|".join(f"(?P<{n}>{p.pattern})" for n, p in (("emo", self._EMO), ("men", self._MEN), ("url", self._URL))))
        for m in pat.finditer(s):
            out.append(s[pos:m.start()])
            g = m.lastgroup
            tok = m.group(0)
            if g == "emo":
                out.append(f":{self._EMO.match(tok).group(1)}:", style=f"bold {C.warn}")
            elif g == "men":
                name = tok[1:].rstrip(".-").lower()
                ok = (name in known) if known is not None else any(u.get("username", "").lower() == name for u in self.members.values())
                if ok:
                    out.append(tok, style=f"bold {C.bg} on {C.warn}" if name == me_name else f"bold {C.link} on {C.sel}")
                else:
                    out.append(tok)
            else:
                out.append(tok, style=f"underline {LINK} link {tok}")
            pos = m.end()
        out.append(s[pos:])
        return out

    def emoji_label(self, key: str | None) -> str:
        key = key or ""
        if key.startswith("c:"):
            e = next((e for e in self.emojis if str(e.get("id")) == key[2:]), None)
            return f":{e['name']}:" if e else ":?:"
        return key

    def draw_who(self) -> None:
        if not self.main:
            return
        t = Text()
        t.append_text(self.name_text(self.me))
        if self.me.get("level"):
            t.append(f"  Lv {self.me['level']}", style=f"{C.warn}")
        t.append("   F1 help", style=DIM)
        try:
            self.main.query_one("#who", Static).update(t)
        except Exception:  # noqa: BLE001
            pass

    def set_badge(self, tab: str, n: int) -> None:
        if not self.main:
            return
        label = dict(TABS)[tab]
        try:
            self.main.query_one(TabbedContent).get_tab(tab).label = Text.assemble(label, (f" ({n})", f"bold {RED}")) if n else label
        except Exception:  # noqa: BLE001
            pass

    def show_tab(self, tab: str) -> None:
        if self.main:
            self.main.query_one(TabbedContent).active = tab

    def open_profile(self, uid: int) -> None:
        self.push_screen(ProfileScreen(uid))

    def open_dm(self, uid: int) -> None:
        if self.main:
            self.main.query_one("#social", SocialPane).open_dm(uid)

    @work(group="roles", exclusive=True)
    async def load_roles(self) -> None:
        r = await self.api.j("/api/roles")
        if r.get("roles"):
            self.roles = r["roles"]
            self.roles_ver = r.get("ver")
            if self.main:
                self.main.draw_members()
                self.draw_who()

    @work(group="emojis", exclusive=True)
    async def load_emojis(self) -> None:
        r = await self.api.j("/api/emojis")
        if r.get("emojis") is not None:
            self.emojis = r["emojis"]
            self.emoji_ev = r.get("ev")

    def refresh_social(self) -> None:
        self.run_worker(self.load_social(), group="socialrefresh", exclusive=True)

    async def load_social(self) -> None:
        r = await self.api.j("/api/social")
        if r.get("error"):
            return
        self.social_v = max(self.social_v, r.get("v") or 0)
        self.social_sum = r
        if not self.main:
            return
        pane = self.main.query_one("#social", SocialPane)
        pane.set_summary(r)
        self._notify_new(r, pane)

    def _notify_new(self, r: dict, pane: SocialPane) -> None:
        me_id = self.me.get("id")
        tabs = self.main.query_one(TabbedContent)
        for cv in r.get("convs") or []:
            l = cv.get("last") or {}
            u = self.user(cv.get("user"))
            k = f"d{u.get('id')}"
            if not l or l.get("uid") == me_id or l.get("kind") in ("sys", "call"):
                continue
            if l.get("at", 0) <= self.seen_convs.get(k, 0):
                continue
            self.seen_convs[k] = l.get("at", 0)
            if not self.notes_primed or r.get("dm_silence"):
                continue
            if pane.open == ("dm", u.get("id")) and tabs.active == "dms":
                continue
            self.bell()
            self.notify(f"{u.get('username', '?')}: {(l.get('text') or ('📷 Photo' if l.get('img') else '📎 ' + str(l.get('file') or 'file')))[:120]}",
                        title="New message")
        for g in r.get("groups") or []:
            l = g.get("last") or {}
            k = f"g{g.get('id')}"
            if not l or l.get("uid") == me_id or l.get("kind") == "sys" or g.get("muted"):
                continue
            if l.get("at", 0) <= self.seen_convs.get(k, 0):
                continue
            self.seen_convs[k] = l.get("at", 0)
            if not self.notes_primed or r.get("gc_silence"):
                continue
            if pane.open == ("gc", g.get("id")) and tabs.active == "dms":
                continue
            self.notify(f"{l.get('name') or 'someone'}: {(l.get('text') or '📎')[:120]}", title=f"# {g.get('name') or 'Group'}")
        ring = r.get("ring")
        if ring and ring.get("rid") != getattr(self, "_last_ring", None):
            self._last_ring = ring.get("rid")
            self.bell()
            self.notify(f"{(ring.get('from') or {}).get('username', 'Someone')} is calling you - calls need the website.",
                        title="📞 Incoming call", timeout=15)
        self.notes_primed = True


def main() -> None:
    import os
    import sys
    app = JiinApp(dev="--dev" in sys.argv or bool(os.environ.get("JIIN_DEV")))
    app.run()
    sys.exit(app.return_code or 0)


if __name__ == "__main__":
    main()
