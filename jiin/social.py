"""Social: direct messages, group chats, message requests and friends."""
from __future__ import annotations

import webbrowser
from urllib.parse import quote

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Footer, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .dialogs import Choose, Confirm, ImageView, Prompt
from .markup import DIM, RED, ago, hhmm
from .pictures import dropped_path, indent, with_avatar
from .theme import C

QUICK_REACTS = ["👍", "❤️", "😂", "😮", "😢", "🔥", "💀", "👀"]


def call_text(t: str) -> str:
    t = t or ""
    if t == "started":
        return "📞 Call started"
    if t == "missed":
        return "📞 Missed call"
    if t == "declined":
        return "📞 Call declined"
    if t.startswith("ended"):
        secs = t.split(":", 1)[1] if ":" in t else ""
        if secs.isdigit():
            s = int(secs)
            return f"📞 Call ended · {s // 60}:{s % 60:02d}"
        return "📞 Call ended"
    return "📞 Call"


def preview(last: dict | None, me_id: int, status: str = "") -> str:
    if not last:
        return "Message request" if status == "req" else ""
    if last.get("kind") == "call":
        return call_text(last.get("text") or "")
    who = "You: " if last.get("uid") == me_id else (f"{last['name']}: " if last.get("name") else "")
    if last.get("img") and not last.get("text"):
        return who + "📷 Photo"
    if not last.get("text") and last.get("file"):
        return who + "📎 " + str(last["file"])
    return who + (last.get("text") or "")


class SocialPane(Widget):
    BINDINGS = [
        Binding("ctrl+n", "new_dm", "New DM"),
        Binding("ctrl+f", "friends", "Friends"),
        Binding("ctrl+g", "new_group", "New group"),
        Binding("escape", "cancel_reply", "Cancel reply", show=False),
        Binding("tab", "cycle_focus", "Next panel", show=False, priority=True),
    ]

    def action_cycle_focus(self) -> None:
        convs, log, inp = self.query_one("#dmconvs"), self.query_one("#dmlog", OptionList), self.query_one("#dmin")
        order = [convs] + ([log, inp] if self.open else [])
        cur = next((k for k, w in enumerate(order) if w.has_focus), -1)
        nxt = order[(cur + 1) % len(order)]
        nxt.focus()
        if nxt is log and log.highlighted is None and log.option_count:
            log.highlighted = log.option_count - 1

    def __init__(self, **kw):
        super().__init__(**kw)
        self.sum: dict = {}
        self.open: tuple[str, int] | None = None   # ("dm", uid) | ("gc", gid)
        self.conv: dict = {}
        self.msgs: list[dict] = []
        self.reply: dict | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="dmside"):
                yield Label("MESSAGES", classes="panel-title", id="dmtitle")
                yield OptionList(id="dmconvs")
            with Vertical():
                yield Static("", id="dmhead", classes="panel-title")
                yield Static("Pick a conversation on the left, or press Ctrl+N to message someone.\n\n"
                             "Ctrl+F  friends & requests      Ctrl+G  new group chat\n\n"
                             "In a conversation: select a message with ↑/↓ then\n"
                             "  r  reply   e  react   d  delete   i  view picture   o  open file", id="dmempty")
                yield OptionList(id="dmlog")
                yield Static("", id="dmreply")
                with Horizontal(classes="composer"):
                    yield Input(placeholder="Message…", id="dmin", max_length=2000)
                    yield Button("Send", id="dmsend")

    def on_mount(self) -> None:
        self.query_one("#dmlog").display = False
        self.query_one("#dmreply").display = False

    # summary from /api/social
    def _list_ready(self) -> None:
        # an avatar in the conversation list loaded; redraw (debounced)
        if getattr(self, "_list_redraw", False):
            return
        self._list_redraw = True

        def go():
            self._list_redraw = False
            if self.sum:
                self.set_summary(self.sum, reload_conv=False)
        self.set_timer(0.15, go)

    def set_summary(self, s: dict, reload_conv: bool = True) -> None:
        self.sum = s
        me_id = self.app.me.get("id")
        ol = self.query_one("#dmconvs", OptionList)
        keep = ol.highlighted_option.id if ol.highlighted_option else None
        ol.clear_options()
        reqs = s.get("requests") or []
        inc = s.get("incoming") or []
        if reqs or inc:
            ol.add_option(Option(Text("REQUESTS", style=f"bold {RED}"), disabled=True))
            for r in reqs:
                u = self.app.user(r.get("user"))
                t = Text()
                t.append("✉ ", style=f"{C.warn}")
                t.append(u.get("username", "?"), style="bold")
                t.append(" wants to message you" + (" ●" if r.get("new") else ""), style=DIM)
                if (r.get("last") or {}).get("text"):
                    t.append("\n  " + r["last"]["text"][:60], style=f"{C.text_dim}")
                ol.add_option(Option(t, id=f"q{u['id']}"))
            for r in inc:
                u = self.app.user(r)
                t = Text()
                t.append("＋ ", style=f"{C.ok}")
                t.append(u.get("username", "?"), style="bold")
                t.append(" sent a friend request" + (" ●" if r.get("new") else ""), style=DIM)
                ol.add_option(Option(t, id=f"r{u['id']}"))
            ol.add_option(None)
        groups = s.get("groups") or []
        if groups:
            ol.add_option(Option(Text("GROUPS", style=f"bold {RED}"), disabled=True))
            for g in groups:
                t = Text()
                t.append("# ", style=RED)
                t.append(g.get("name") or "Group", style="bold" + (f" {RED}" if g.get("unread") else ""))
                if g.get("unread"):
                    t.append(f" ({g['unread']})", style=RED)
                if g.get("muted"):
                    t.append(" 🔕", style=DIM)
                t.append(f"  {ago((g.get('last') or {}).get('at') or g.get('at'))}", style=DIM)
                t.append("\n  " + preview(g.get("last"), me_id)[:60].replace("\n", " "), style=f"{C.text_dim}")
                ol.add_option(Option(t, id=f"g{g['id']}"))
            ol.add_option(None)
        convs = s.get("convs") or []
        ol.add_option(Option(Text("DIRECT MESSAGES", style=f"bold {RED}"), disabled=True))
        for c in convs:
            u = self.app.user(c.get("user"))
            t = Text()
            t.append("● " if self.app.online(u) else "○ ", style=f"{C.ok}" if self.app.online(u) else DIM)
            t.append_text(self.app.name_text(u, bold=bool(c.get("unread"))))
            if c.get("unread"):
                t.append(f" ({c['unread']})", style=RED)
            if c.get("pending"):
                t.append(" · request sent", style=f"{C.warn}")
            t.append(f"  {ago((c.get('last') or {}).get('at') or c.get('at'))}", style=DIM)
            t.append("\n  " + preview(c.get("last"), me_id, c.get("status") or "")[:60].replace("\n", " "), style=f"{C.text_dim}")
            if self.app.pics.enabled:
                t = with_avatar(self.app.pics.avatar(u.get("id"), u.get("av"), u.get("username", ""), 8, 4, on_ready=self._list_ready), t, 8)
            ol.add_option(Option(t, id=f"d{u['id']}"))
        if not convs:
            ol.add_option(Option(Text("No conversations yet.\nCtrl+N to start one.", style=DIM), disabled=True))
        if keep:
            try:
                ol.highlighted = ol.get_option_index(keep)
            except Exception:  # noqa: BLE001
                pass
        c = s.get("counts") or {}
        n = int(c.get("unread") or 0) + int(c.get("gc_unread") or 0) + int(c.get("req_new") or 0) + int(c.get("friend_new") or 0)
        self.app.set_badge("dms", n)
        if self.open and reload_conv:
            self.load_conv(quiet=True)

    @on(OptionList.OptionSelected, "#dmconvs")
    def _pick(self, e: OptionList.OptionSelected) -> None:
        oid = e.option.id or ""
        kind, num = oid[:1], int(oid[1:] or 0)
        if kind == "d":
            self.open_dm(num)
        elif kind == "q":
            self.msg_request_prompt(num)
        elif kind == "g":
            self.open_gc(num)
        elif kind == "r":
            self.friend_request_prompt(num)

    def friend_request_prompt(self, uid: int) -> None:
        u = self.app.user({"id": uid})

        def done(v):
            if v == "accept":
                self.post("/api/friends/accept", {"uid": uid}, f"You and {u.get('username')} are now friends")
            elif v == "decline":
                self.post("/api/friends/decline", {"uid": uid}, "Request declined")
            elif v == "profile":
                self.app.open_profile(uid)
        self.app.push_screen(Choose(f"Friend request from {u.get('username', '?')}",
                                    [("accept", "Accept"), ("decline", "Decline"), ("profile", "View profile")], "accept"), done)

    def msg_request_prompt(self, uid: int) -> None:
        u = self.app.user({"id": uid})
        if (self.sum.get("counts") or {}).get("req_new"):
            self.post("/api/dm/requests/seen", {})

        def done(v):
            if v == "read":
                self.open_dm(uid)
            elif v == "accept":
                self.post(f"/api/dm/{uid}/accept", {}, "Request accepted")
                self.open_dm(uid)
            elif v == "delete":
                self.app.push_screen(Confirm("Delete request", f"Delete the message request from {u.get('username', '?')}?", "Delete", True),
                                     lambda ok: ok and self.post(f"/api/dm/{uid}/delete", {}, "Request deleted"))
            elif v == "block":
                self.app.push_screen(Confirm("Block", f"Block {u.get('username', '?')}? They won't be able to message you.", "Block", True),
                                     lambda ok: ok and self.post("/api/blocks/add", {"uid": uid}, f"Blocked {u.get('username', '?')}"))
            elif v == "profile":
                self.app.open_profile(uid)
        self.app.push_screen(Choose(f"Message request from {u.get('username', '?')}",
                                    [("read", "Read it"), ("accept", "Accept"), ("delete", "Delete"), ("block", "Block"),
                                     ("profile", "View profile")], "read"), done)

    @work(group="spost")
    async def post(self, url: str, body: dict, ok: str = "") -> dict:
        r = await self.app.api.j(url, body)
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
        elif ok:
            self.app.notify(ok)
        self.app.refresh_social()
        return r

    # open a conversation
    def open_dm(self, uid: int) -> None:
        self.open = ("dm", uid)
        self.msgs, self.reply = [], None
        self._show_reply()
        self.load_conv()
        self.app.show_tab("dms")
        self.query_one("#dmin", Input).focus()

    def open_gc(self, gid: int) -> None:
        self.open = ("gc", gid)
        self.msgs, self.reply = [], None
        self._show_reply()
        self.load_conv()
        self.query_one("#dmin", Input).focus()

    @work(exclusive=True, group="conv")
    async def load_conv(self, quiet: bool = False) -> None:
        if not self.open:
            return
        kind, cid = self.open
        r = await self.app.api.j(f"/api/{kind}/{cid}", retries=0 if quiet else None)
        if self.open != (kind, cid):
            return
        head = self.query_one("#dmhead", Static)
        self.query_one("#dmempty").display = False
        log = self.query_one("#dmlog", OptionList)
        log.display = True
        if r.get("error"):
            if not quiet:
                head.update(Text(r["error"], style=f"{C.err}"))
            return
        new = r.get("messages") or []
        if quiet and self.msgs and new:
            older = [m for m in self.msgs if m["id"] < new[0]["id"]]
            new = older + new
            more = self.conv.get("more")
        else:
            more = r.get("more")
        if kind == "gc" and quiet and self.conv.get("names"):
            r["names"] = {**self.conv.get("names", {}), **(r.get("names") or {})}
        changed = [m.get("id") for m in new] != [m.get("id") for m in self.msgs] or \
            [str(m.get("rx")) for m in new] != [str(m.get("rx")) for m in self.msgs]
        self.conv = r
        self.conv["more"] = more
        self.msgs = new
        self._draw_head()
        if changed or not quiet:
            self._draw_msgs()

    def _draw_head(self) -> None:
        kind, cid = self.open
        r = self.conv
        t = Text()
        if kind == "dm":
            u = self.app.user(r.get("user") or {"id": cid})
            t.append("@ ", style=RED)
            t.append_text(self.app.name_text(u))
            on_ = self.app.online(u)
            t.append("  ● online" if on_ else f"  ○ {('seen ' + ago(u.get('last_seen'))) if u.get('last_seen') else 'offline'}",
                     style=f"{C.ok}" if on_ else DIM)
            if r.get("friends"):
                t.append("  · friends", style=DIM)
            conv = r.get("conv") or {}
            note = ""
            if r.get("blocked_by_me"):
                note = "You blocked this person. Unblock them (Ctrl+F) to message."
            elif r.get("blocked_me"):
                note = "You can't message this person."
            elif conv.get("status") == "req" and conv.get("req_from") == cid:
                note = "Message request - pick it under REQUESTS on the left to accept or delete it."
            elif conv.get("status") == "req":
                note = "Message request sent - you can send more once they accept."
            elif not r.get("friends") and not conv and not r.get("dm_open"):
                note = "They only accept messages from friends."
            elif not r.get("friends") and not conv:
                note = "Your first message is sent as a message request (text only)."
            if note:
                t.append("\n" + note, style=f"{C.warn}")
        else:
            g = r.get("gc") or {}
            t.append("# ", style=RED)
            t.append(g.get("name") or "Group", style=f"bold {RED}")
            mem = r.get("members") or []
            t.append(f"  · {len(mem)} members: ", style=DIM)
            t.append(", ".join(m.get("username", "?") for m in mem)[:120], style=DIM)
            if r.get("call"):
                t.append("  · 📞 call live", style=f"{C.ok}")
        self.query_one("#dmhead", Static).update(t)

    def _name_of(self, uid: int) -> str:
        if uid == self.app.me.get("id"):
            return self.app.me.get("username", "you")
        r = self.conv
        if self.open and self.open[0] == "dm":
            u = r.get("user") or {}
            if u.get("id") == uid:
                return self.app.user(u).get("username", "?")
        for m in r.get("members") or []:
            if m.get("id") == uid:
                return m.get("username", "?")
        n = (r.get("names") or {}).get(str(uid))
        if n:
            return n
        return self.app.user({"id": uid}).get("username") or "someone"

    def _sys_text(self, m: dict) -> str:
        s = m.get("sys") or {}
        by = self._name_of(s["by"]) if s.get("by") else "Someone"
        who = ", ".join(self._name_of(x) for x in s.get("who") or [])
        return {
            "create": f"{by} created the group",
            "add": f"{by} added {who}",
            "kick": f"{by} removed {who}",
            "leave": f"{who or by} left",
            "owner": f"{who} is now the owner",
            "rename": f"{by} renamed the group to “{s.get('name', '')}”",
            "pic": f"{by} changed the group picture",
            "unpic": f"{by} removed the group picture",
        }.get(s.get("t"), m.get("text") or "")

    def _draw_msgs(self) -> None:
        log = self.query_one("#dmlog", OptionList)
        at_end = log.highlighted is None or log.highlighted >= log.option_count - 2
        hi = log.highlighted
        log.clear_options()
        if self.conv.get("more"):
            log.add_option(Option(Text("↑ load older messages", style=DIM), id="older"))
        me_id = self.app.me.get("id")
        other_read = self.conv.get("other_read") or 0
        last_mine = max((m["id"] for m in self.msgs if m.get("uid") == me_id), default=0)
        prev = None
        for m in self.msgs:
            t = Text()
            kind = m.get("kind") or "msg"
            if kind == "sys":
                t.append(f"  — {self._sys_text(m)} · {hhmm(m.get('at'))}", style=f"italic {DIM}")
                log.add_option(Option(t, id=f"m{m['id']}"))
                prev = None
                continue
            if kind == "call":
                t.append(f"  {call_text(m.get('text') or '')} · {hhmm(m.get('at'))}", style=DIM)
                log.add_option(Option(t, id=f"m{m['id']}"))
                prev = None
                continue
            grouped = prev and prev.get("uid") == m.get("uid") and (m.get("at", 0) - prev.get("at", 0)) < 300 and not m.get("reply")
            pics = self.app.pics
            nm = self._name_of(m.get("uid"))
            if not grouped:
                t.append(nm, style=f"bold {'{C.fg_bright}' if m.get('uid') == me_id else RED}")
                t.append(f"  {hhmm(m.get('at'))}", style=DIM)
            rp = m.get("reply")
            if rp:
                t.append("\n↩ ", style=DIM)
                if rp.get("gone"):
                    t.append("original message unavailable", style=f"italic {DIM}")
                else:
                    t.append(f"{rp.get('username', '')}: ", style=f"bold {DIM}")
                    t.append((rp.get("text") or "")[:80].replace("\n", " ") or "🖼 picture", style=f"italic {DIM}")
            body = m.get("text") or ""
            if body:
                if t:
                    t.append("\n")
                t.append_text(self.app.chat_text(body))
            if m.get("media"):
                if t:
                    t.append("\n")
                if pics.enabled:
                    t.append_text(pics.preview(m["media"], None, None, 64, 16, on_ready=self._pic_ready))
                    t.append("\npicture · i for full size", style=DIM)
                else:
                    t.append("🖼 picture (i to view)", style=f"{C.warn}")
            for f in m.get("files") or []:
                if t:
                    t.append("\n")
                if f.get("cat") == "image" and pics.enabled and f.get("url"):
                    t.append_text(pics.preview(f["url"], None, None, 64, 16, on_ready=self._pic_ready, label=f.get("name", "picture")))
                    t.append(f"\n{f.get('name', 'picture')} ({_size(f.get('size'))}) · i for full size", style=DIM)
                else:
                    t.append(f"📎 {f.get('name', 'file')} ({_size(f.get('size'))})", style=f"{C.warn}")
            rx = m.get("rx") or []
            if rx:
                t.append("\n")
                for x in rx:
                    t.append(f" {self.app.emoji_label(x.get('e'))} {x.get('n', 0)} ", style=f"on {C.sel_strong}" if x.get("me") else f"on {C.code_bg}")
                    t.append(" ")
            if m.get("uid") == me_id and m["id"] == last_mine and self.open[0] == "dm" and other_read >= m["id"]:
                t.append("\nSeen", style=DIM)
            if pics.enabled:
                who = self.app.me if m.get("uid") == me_id else self.app.user({"id": m.get("uid")})
                av = "" if grouped else pics.avatar(m.get("uid"), who.get("av"), nm, 10, 5, on_ready=self._pic_ready)
                t = with_avatar(av, t, 10, f"on {C.ping_bg}" if m.get("rp") else None)
            else:
                t = indent(t, "▌ " if m.get("rp") else "  ", f"{C.warn}")
            log.add_option(Option(t, id=f"m{m['id']}"))
            prev = m
        if at_end and log.option_count:
            log.highlighted = log.option_count - 1
            log.scroll_end(animate=False)
        elif hi is not None and hi < log.option_count:
            log.highlighted = hi

    def _pic_ready(self) -> None:
        if getattr(self, "_pic_redraw", False):
            return
        self._pic_redraw = True

        def go():
            self._pic_redraw = False
            if self.open:
                self._draw_msgs()
        self.set_timer(0.15, go)

    def cur_msg(self) -> dict | None:
        log = self.query_one("#dmlog", OptionList)
        o = log.highlighted_option
        if not o or not (o.id or "").startswith("m"):
            return None
        mid = int(o.id[1:])
        return next((m for m in self.msgs if m["id"] == mid), None)

    @on(OptionList.OptionSelected, "#dmlog")
    def _msg_sel(self, e: OptionList.OptionSelected) -> None:
        if e.option.id == "older":
            self.load_older()
        else:
            self.action_msg_menu()

    @work(group="older")
    async def load_older(self) -> None:
        if not self.open or not self.msgs:
            return
        kind, cid = self.open
        q = await self.app.api.j(f"/api/{kind}/{cid}?before={self.msgs[0]['id']}")
        if q.get("error"):
            self.app.notify(q["error"], severity="error")
            return
        self.msgs = (q.get("messages") or []) + self.msgs
        self.conv["more"] = q.get("more")
        if q.get("names"):
            self.conv["names"] = {**(self.conv.get("names") or {}), **q["names"]}
        self._draw_msgs()
        self.query_one("#dmlog", OptionList).highlighted = 0

    # message actions
    def on_key(self, event) -> None:
        log = self.query_one("#dmlog", OptionList)
        if not log.has_focus:
            return
        k = event.key
        if k == "r":
            self.action_reply()
        elif k == "e":
            self.action_react()
        elif k == "d":
            self.action_delete()
        elif k == "i":
            self.action_view()
        elif k == "o":
            self.action_open_file()
        else:
            return
        event.stop()

    def action_msg_menu(self) -> None:
        m = self.cur_msg()
        if not m:
            return
        opts = [("reply", "Reply (r)")] if self.open[0] == "dm" else []
        if self.open[0] == "dm":
            opts.append(("react", "React (e)"))
        if m.get("media"):
            opts.append(("view", "View picture (i)"))
        if m.get("files"):
            opts.append(("file", "Open file (o)"))
        if m.get("uid") == self.app.me.get("id") and self.open[0] == "dm":
            opts.append(("delete", "Delete for everyone (d)"))
        opts.append(("profile", "View sender's profile"))

        def done(v):
            {"reply": self.action_reply, "react": self.action_react, "view": self.action_view, "file": self.action_open_file,
             "delete": self.action_delete, "profile": lambda: self.app.open_profile(m.get("uid"))}.get(v, lambda: None)()
        self.app.push_screen(Choose("Message", opts, opts[0][0]), done)

    def action_reply(self) -> None:
        m = self.cur_msg()
        if not m or self.open[0] != "dm":
            return
        self.reply = m
        self._show_reply()
        self.query_one("#dmin", Input).focus()

    def _show_reply(self) -> None:
        bar = self.query_one("#dmreply", Static)
        if self.reply:
            bar.update(Text(f"↩ replying to {self._name_of(self.reply.get('uid'))}: {(self.reply.get('text') or '')[:70]}   (Esc to cancel)"))
            bar.display = True
        else:
            bar.display = False

    def action_react(self) -> None:
        m = self.cur_msg()
        if not m or self.open[0] != "dm":
            return
        opts = [(e, e) for e in QUICK_REACTS] + [(f"c:{e['id']}", f":{e['name']}:") for e in self.app.emojis[:30]]

        def done(v):
            if v:
                self.react(m["id"], v)
        self.app.push_screen(Choose("React with", opts, QUICK_REACTS[0]), done)

    @work(group="dmreact")
    async def react(self, mid: int, emoji: str) -> None:
        r = await self.app.api.j(f"/api/dm/{self.open[1]}/react", {"msg_id": mid, "emoji": emoji})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
            return
        for m in self.msgs:
            if m["id"] == mid:
                m["rx"] = r.get("rx") or []
        self._draw_msgs()

    def action_delete(self) -> None:
        m = self.cur_msg()
        if not m or self.open[0] != "dm" or m.get("uid") != self.app.me.get("id"):
            return

        def done(ok):
            if ok:
                self._del(m["id"])
        self.app.push_screen(Confirm("Delete message", "Delete this message for everyone? This can't be undone.", "Delete", True), done)

    @work(group="dmdel")
    async def _del(self, mid: int) -> None:
        r = await self.app.api.j(f"/api/dm/{self.open[1]}/msg/{mid}/delete", {})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
        self.load_conv()

    def action_view(self) -> None:
        m = self.cur_msg()
        if m and m.get("media"):
            self.app.push_screen(ImageView(f"Picture from {self._name_of(m.get('uid'))}", m["media"]))
        elif m:
            imgs = [f for f in m.get("files") or [] if f.get("cat") == "image"]
            if imgs:
                self.app.push_screen(ImageView(imgs[0].get("name", "picture"), imgs[0]["url"]))

    def action_open_file(self) -> None:
        m = self.cur_msg()
        files = (m or {}).get("files") or []
        if not files:
            return

        def go(f):
            url = f["url"]
            if f.get("cat") == "image":
                self.app.push_screen(ImageView(f.get("name", "picture"), url))
            else:
                webbrowser.open(url if url.startswith("http") else self.app.api.http.base + url)
                self.app.notify(f"Opened {f.get('name')} in your browser (you may need to be signed in there).")
        if len(files) == 1:
            go(files[0])
        else:
            self.app.push_screen(Choose("Which file?", [(str(k), f.get("name", "file")) for k, f in enumerate(files)], "0"),
                                 lambda v: v is not None and go(files[int(v)]))

    # sending
    @on(Input.Submitted, "#dmin")
    @on(Button.Pressed, "#dmsend")
    def _send(self) -> None:
        inp = self.query_one("#dmin", Input)
        t = inp.value.strip()
        if not t or not self.open:
            return
        inp.value = ""
        dropped = dropped_path(t)
        if dropped:
            self.send_file(str(dropped), "")
            return
        if t.startswith(("/file", "/img")):
            import re
            m = re.match(r"/(?:file|img)\s+(\"[^\"]+\"|'[^']+'|\S+)\s*(.*)$", t)
            if not m:
                self.app.notify("Usage: /file ~/path/to/file [message]", severity="warning")
                return
            self.send_file(m.group(1).strip("'\""), m.group(2))
            return
        body = {"text": t, "files": None}
        if self.reply and self.open[0] == "dm":
            body["reply_to"] = self.reply["id"]
        self.reply = None
        self._show_reply()
        self.send(body, t)

    @work(group="dmsend")
    async def send(self, body: dict, text: str) -> None:
        kind, cid = self.open
        r = await self.app.api.j(f"/api/{kind}/{cid}", body)
        if r.get("error"):
            self.query_one("#dmin", Input).value = text
            self.app.notify(r["error"], severity="error")
            return
        if r.get("request"):
            self.app.notify("Message request sent")
        self.load_conv()

    @work(group="dmfile")
    async def send_file(self, path: str, text: str) -> None:
        import mimetypes
        from pathlib import Path
        p = Path(path).expanduser()
        if not p.is_file():
            self.app.notify(f"No file at {p}", severity="error")
            return
        if p.stat().st_size > 100 * 1048576:
            self.app.notify("Files can be at most 100 MB", severity="error")
            return
        kind, cid = self.open
        self.app.notify(f"Uploading {p.name}…")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        r = await self.app.api.upload(f"/api/{kind}/{cid}/file?name={quote(p.name)}", p.read_bytes(), ctype)
        fid = (r.get("file") or {}).get("id")
        if r.get("error") or not fid:
            self.app.notify(r.get("error") or "The upload failed", severity="error")
            return
        self.send({"text": text.strip(), "files": [fid]}, "")

    def action_cancel_reply(self) -> None:
        if self.reply:
            self.reply = None
            self._show_reply()

    # new DM / group / friends
    def action_new_dm(self) -> None:
        def done(v):
            if not v:
                return
            u = self.app.find_user(v.strip().lstrip("@"))
            if not u:
                self.app.notify(f"No member called {v}", severity="error")
                return
            self.open_dm(u["id"])
        self.app.push_screen(Prompt("Message someone", "username"), done)

    def action_new_group(self) -> None:
        friends = [self.app.user(f) for f in (self.sum.get("friends") or [])]
        if not friends:
            self.app.notify("Group chats are made with friends - add some first (Ctrl+F)", severity="warning")
            return

        def got_name(name):
            if name is None:
                return

            def got_members(v):
                if not v:
                    return
                names = [x.strip().lstrip("@").lower() for x in v.replace(",", " ").split() if x.strip()]
                ids = [f["id"] for f in friends if f.get("username", "").lower() in names]
                if not ids:
                    self.app.notify("None of those are your friends", severity="error")
                    return
                self.create_gc(name.strip(), ids)
            self.app.push_screen(Prompt("Who's in it?", "usernames, separated by spaces",
                                        help="Your friends: " + ", ".join(f.get("username", "?") for f in friends)), got_members)
        self.app.push_screen(Prompt("New group chat", "Group name (optional)", max_length=40), got_name)

    @work(group="gccreate")
    async def create_gc(self, name: str, ids: list[int]) -> None:
        r = await self.app.api.j("/api/gc/create", {"members": ids, "name": name})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
            return
        self.app.refresh_social()
        self.open_gc(int(r["id"]))

    def action_friends(self) -> None:
        self.app.push_screen(FriendsScreen(self))


def _size(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return ""


class FriendsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back"), Binding("a", "add", "Add friend"),
                Binding("m", "message", "Message"), Binding("x", "remove", "Remove/cancel/unblock"),
                Binding("b", "block", "Block"), Binding("p", "profile", "Profile")]

    def __init__(self, pane: SocialPane):
        super().__init__()
        self.pane = pane

    def compose(self) -> ComposeResult:
        yield Label("FRIENDS", classes="panel-title")
        yield OptionList(id="flist")
        yield Footer()

    def on_mount(self) -> None:
        self.draw()
        if (self.pane.sum.get("counts") or {}).get("friend_new"):
            self.run_worker(self.app.api.j("/api/friends/seen", {}))

    def draw(self) -> None:
        s = self.pane.sum
        ol = self.query_one(OptionList)
        ol.clear_options()

        def sec(title, items, prefix, note=""):
            ol.add_option(Option(Text(f"{title} ({len(items)})", style=f"bold {RED}"), disabled=True))
            for x in items:
                u = self.app.user(x)
                t = Text()
                on_ = self.app.online(u)
                t.append("● " if on_ else "○ ", style=f"{C.ok}" if on_ else DIM)
                t.append_text(self.app.name_text(u))
                if note:
                    t.append(f"  {note}", style=DIM)
                ol.add_option(Option(t, id=f"{prefix}{u['id']}"))
            if not items:
                ol.add_option(Option(Text("  none", style=DIM), disabled=True))
            ol.add_option(None)
        sec("INCOMING REQUESTS", s.get("incoming") or [], "i", "enter to accept · x to decline")
        sec("FRIENDS", sorted(s.get("friends") or [], key=lambda f: not self.app.online(self.app.user(f))), "f")
        sec("SENT REQUESTS", s.get("outgoing") or [], "o", "x to cancel")
        sec("BLOCKED", s.get("blocked") or [], "b", "x to unblock")
        ol.focus()

    def _cur(self):
        o = self.query_one(OptionList).highlighted_option
        if not o or not o.id:
            return None, None
        return o.id[0], int(o.id[1:])

    async def _do(self, url: str, body: dict, ok: str) -> None:
        r = await self.app.api.j(url, body)
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
        else:
            self.app.notify(ok)
        await self.app.load_social()
        self.draw()

    @on(OptionList.OptionSelected)
    def _sel(self) -> None:
        k, uid = self._cur()
        if k == "i":
            self.run_worker(self._do("/api/friends/accept", {"uid": uid}, "Friend added"))
        elif k == "f":
            self.action_message()

    def action_add(self) -> None:
        def done(v):
            if v and v.strip():
                self.run_worker(self._add(v.strip().lstrip("@")))
        self.app.push_screen(Prompt("Add a friend", "username", max_length=40), done)

    async def _add(self, name: str) -> None:
        r = await self.app.api.j("/api/friends/request", {"username": name})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
        else:
            self.app.notify(f"You and {r.get('username', name)} are now friends" if r.get("friends") else f"Friend request sent to {r.get('username', name)}")
        await self.app.load_social()
        self.draw()

    def action_message(self) -> None:
        k, uid = self._cur()
        if uid:
            self.app.pop_screen()
            self.pane.open_dm(uid)

    def action_profile(self) -> None:
        k, uid = self._cur()
        if uid:
            self.app.open_profile(uid)

    def action_remove(self) -> None:
        k, uid = self._cur()
        if not uid:
            return
        u = self.app.user({"id": uid})
        if k == "i":
            self.run_worker(self._do("/api/friends/decline", {"uid": uid}, "Declined"))
        elif k == "o":
            self.run_worker(self._do("/api/friends/cancel", {"uid": uid}, "Request cancelled"))
        elif k == "b":
            self.run_worker(self._do("/api/blocks/remove", {"uid": uid}, f"Unblocked {u.get('username')}"))
        elif k == "f":
            self.app.push_screen(Confirm("Remove friend", f"Remove {u.get('username')} from your friends?", "Remove", True),
                                 lambda ok: ok and self.run_worker(self._do("/api/friends/remove", {"uid": uid}, "Friend removed")))

    def action_block(self) -> None:
        k, uid = self._cur()
        if not uid or k == "b":
            return
        u = self.app.user({"id": uid})
        self.app.push_screen(Confirm("Block", f"Block {u.get('username')}? They won't be able to message you.", "Block", True),
                             lambda ok: ok and self.run_worker(self._do("/api/blocks/add", {"uid": uid}, f"Blocked {u.get('username')}")))
