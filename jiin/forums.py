"""Forums: directory → thread list → thread view."""
from __future__ import annotations

import webbrowser
from urllib.parse import urlencode

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Footer, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from .dialogs import Choose, Confirm, ImageView, Prompt
from .markup import DIM, RED, ago, forum_body, full, snip
from .pictures import with_avatar
from .theme import C

FORUM_SORTS = [("active", "Recently active"), ("popular", "Popular"), ("top", "Top rated"), ("new", "Newest"), ("name", "A–Z")]
THREAD_SORTS = [("active", "Latest activity"), ("new", "Newest"), ("top", "Top voted"), ("popular", "Most viewed"),
                ("replies", "Most replies"), ("old", "Oldest")]


def _n(n, one: str, many: str | None = None) -> str:
    n = int(n or 0)
    return f"{n} {one if n == 1 else (many or one + 's')}"


def uname(u) -> str:
    return (u or {}).get("username") or "deleted"


class ForumsPane(Widget):
    BINDINGS = [
        Binding("n", "new_thread", "New thread"),
        Binding("s", "sort", "Sort"),
        Binding("slash", "search", "Search"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("right_square_bracket", "page(1)", "Next page"),
        Binding("left_square_bracket", "page(-1)", "Prev page"),
        Binding("f", "follow", "Follow forum"),
        Binding("i", "notifs", "Notifications"),
    ]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.forums: list[dict] = []
        self.fpage = 1
        self.fsort = "active"
        self.fmore = False
        self.cur: dict | None = None        # the open forum's response
        self.fid: int | None = None
        self.tsort = "active"
        self.tpage = 1
        self.tq = ""
        self.loaded = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="fmside"):
                yield Label("FORUMS", classes="panel-title")
                yield OptionList(id="forumlist")
            with Vertical():
                yield Static("", id="fminfo", classes="panel-title")
                yield OptionList(id="threadlist")
                with Horizontal(id="fmbar"):
                    yield Button("New thread (n)", id="fmnew")
                    yield Button("Sort (s)", id="fmsort")
                    yield Button("Search (/)", id="fmsearch")
                    yield Button("Notifications (i)", id="fmnotif")
                    yield Static("", id="fmpager")

    def on_show(self) -> None:
        if not self.loaded:
            self.loaded = True
            self.load_forums()

    # ---------- directory ----------
    @work(exclusive=True, group="fdir")
    async def load_forums(self) -> None:
        qs = urlencode({"q": "", "cat": "", "sort": self.fsort, "page": self.fpage, "mine": 0, "deleted": 0})
        r = await self.app.api.j("/api/forums?" + qs)
        ol = self.query_one("#forumlist", OptionList)
        ol.clear_options()
        if r.get("error"):
            ol.add_option(Option(Text(r["error"], style=f"{C.err}"), disabled=True))
            return
        self.forums = r.get("forums") or []
        self.fmore = bool(r.get("more"))
        for f in self.forums:
            t = Text()
            t.append((f.get("icon") or "#")[:2] + " ", style=RED)
            t.append(f.get("name") or "?", style="bold")
            if f.get("new"):
                t.append(" ●", style=RED)
            if f.get("status") in ("locked", "archived"):
                t.append(f" [{f['status']}]", style=DIM)
            t.append(f"\n   {f.get('threads', 0)} threads · {f.get('posts', 0)} posts · {ago(f.get('last_at'))}", style=DIM)
            ol.add_option(Option(t, id=f"f{f['id']}"))
        if self.fmore or self.fpage > 1:
            ol.add_option(None)
            if self.fpage > 1:
                ol.add_option(Option(Text("◀ previous page", style=DIM), id="fprev"))
            if self.fmore:
                ol.add_option(Option(Text("next page ▶", style=DIM), id="fnext"))
        if not self.forums:
            ol.add_option(Option(Text("No forums yet.", style=DIM), disabled=True))
        if self.fid is None and self.forums:
            self.open_forum(self.forums[0]["id"])

    @on(OptionList.OptionSelected, "#forumlist")
    def _pick_forum(self, e: OptionList.OptionSelected) -> None:
        oid = e.option.id or ""
        if oid == "fprev":
            self.fpage -= 1
            self.load_forums()
        elif oid == "fnext":
            self.fpage += 1
            self.load_forums()
        elif oid.startswith("f"):
            self.tpage, self.tq = 1, ""
            self.open_forum(int(oid[1:]))
            self.query_one("#threadlist").focus()

    # ---------- thread list ----------
    @work(exclusive=True, group="tlist")
    async def open_forum(self, fid: int) -> None:
        self.fid = fid
        qs = urlencode({"sort": self.tsort, "tag": "", "q": self.tq, "show": "", "page": self.tpage})
        r = await self.app.api.j(f"/api/forums/{fid}?{qs}")
        tl = self.query_one("#threadlist", OptionList)
        tl.clear_options()
        info = self.query_one("#fminfo", Static)
        if r.get("error"):
            info.update(Text(r["error"], style=f"{C.err}"))
            return
        self.cur = r
        f = r.get("forum") or {}
        me = r.get("me") or {}
        head = Text()
        head.append(f"{f.get('icon') or '#'} {f.get('name', '')}", style=f"bold {RED}")
        if f.get("handle"):
            head.append(f"  #{f['handle']}", style=DIM)
        head.append(f"  · {f.get('threads', 0)} threads · score {f.get('score', 0)}", style=DIM)
        if f.get("following"):
            head.append("  ★ following", style=f"{C.warn}")
        if self.tq:
            head.append(f"  · search: {self.tq}", style=f"{C.warn}")
        sort_label = dict(THREAD_SORTS).get(self.tsort, self.tsort)
        head.append(f"  · {sort_label}", style=DIM)
        info.update(head)
        if f.get("descr"):
            tl.add_option(Option(Text(f["descr"], style=f"italic {DIM}"), disabled=True))
            tl.add_option(None)
        for t in r.get("threads") or []:
            x = Text()
            flags = ("📌 " if t.get("pinned") else "") + ("🔒 " if t.get("locked") else "") + ("✔ " if t.get("resolved") else "")
            if flags:
                x.append(flags)
            if t.get("tag"):
                x.append(f"[{t['tag']}] ", style=f"{C.warn}")
            x.append(t.get("title") or "(untitled)", style="bold" + (f" {RED}" if t.get("unread") else ""))
            if t.get("unread"):
                x.append(" ●", style=RED)
            if not t.get("approved", True):
                x.append(" (awaiting approval)", style=DIM)
            sub = f"\n  {uname(t.get('user'))} · {ago(t.get('created'))} · {_n(t.get('replies', 0), 'reply', 'replies')} · {_n(t.get('views', 0), 'view')}"
            if t.get("replies") and t.get("last_user"):
                sub += f" · last by {uname(t['last_user'])} {ago(t.get('last_at'))}"
            x.append(sub, style=DIM)
            if t.get("excerpt"):
                x.append("\n  " + t["excerpt"][:160].replace("\n", " "), style=f"{C.text_dim}")
            tl.add_option(Option(x, id=f"t{t['id']}"))
        if not r.get("threads"):
            tl.add_option(Option(Text("No threads here yet." + ("" if me.get("thread") else f"  {me.get('why') or ''}"), style=DIM), disabled=True))
        self.query_one("#fmpager", Static).update(f"page {r.get('page', 1)} / {r.get('pages', 1)}   [ ] to flip")

    @on(OptionList.OptionSelected, "#threadlist")
    def _pick_thread(self, e: OptionList.OptionSelected) -> None:
        oid = e.option.id or ""
        if oid.startswith("t"):
            self.app.push_screen(ThreadScreen(int(oid[1:])), lambda _: self.fid and self.open_forum(self.fid))

    # ---------- actions ----------
    def action_refresh(self) -> None:
        self.load_forums()
        if self.fid:
            self.open_forum(self.fid)

    def action_page(self, d: int) -> None:
        if not self.cur:
            return
        np = self.tpage + d
        if 1 <= np <= int(self.cur.get("pages") or 1):
            self.tpage = np
            self.open_forum(self.fid)

    def action_sort(self) -> None:
        def done(v):
            if v:
                self.tsort, self.tpage = v, 1
                self.open_forum(self.fid)
        self.app.push_screen(Choose("Sort threads by", THREAD_SORTS, self.tsort), done)

    def action_search(self) -> None:
        def done(v):
            if v is None:
                return
            v = v.strip()
            if not v:
                self.tq, self.tpage = "", 1
                if self.fid:
                    self.open_forum(self.fid)
                return
            self.search_all(v)
        self.app.push_screen(Prompt("Search forums", "words to look for", help="Searches every forum's thread titles and posts. Leave empty to clear."), done)

    @work(group="fsearch")
    async def search_all(self, q: str) -> None:
        if len(q) < 2:
            self.app.notify("Type at least 2 characters", severity="warning")
            return
        r = await self.app.api.j("/api/forums/search?" + urlencode({"q": q}))
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
            return
        tl = self.query_one("#threadlist", OptionList)
        tl.clear_options()
        self.query_one("#fminfo", Static).update(Text(f"Search results for “{q}”", style=f"bold {RED}"))
        for it in r.get("items") or []:
            x = Text()
            x.append(f"{it.get('icon') or '#'} ", style=RED)
            x.append(it.get("title") or "", style="bold")
            x.append(f"  in {it.get('forum', '')} · {it.get('replies', 0)} replies · {ago(it.get('last_at'))}\n  ", style=DIM)
            x.append_text(snip(it.get("snip") or ""))
            tl.add_option(Option(x, id=f"t{it['id']}"))
        if not r.get("items"):
            tl.add_option(Option(Text("Nothing found.", style=DIM), disabled=True))
        self.query_one("#fmpager", Static).update("")
        tl.focus()

    def action_new_thread(self) -> None:
        if not self.cur:
            return
        me = self.cur.get("me") or {}
        if not me.get("thread"):
            self.app.notify(me.get("why") or "You can't start a thread here.", severity="warning")
            return
        f = self.cur.get("forum") or {}
        tags = f.get("tags") or []

        def got_title(title):
            if not title or not title.strip():
                return

            def got_body(body):
                if body is None:
                    return
                if tags:
                    def got_tag(tag):
                        self.post_thread(title.strip(), body, tag or "")
                    self.app.push_screen(Choose("Tag", [("", "(none)")] + [(t, t) for t in tags], ""), got_tag)
                else:
                    self.post_thread(title.strip(), body, "")
            self.app.push_screen(Prompt(f"New thread in {f.get('name', '')}: {title.strip()}", multiline=True, ok="Post",
                                        help="Markup: **bold** *italic* __underline__ ~~strike~~ `code` > quote, - list, # heading"), got_body)
        self.app.push_screen(Prompt("New thread: title", "Thread title", max_length=140), got_title)

    @work(group="fpost")
    async def post_thread(self, title: str, body: str, tag: str) -> None:
        r = await self.app.api.j(f"/api/forums/{self.fid}/thread", {"title": title, "body": body, "tag": tag, "imgs": []})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
            return
        if r.get("pending"):
            self.app.notify("Posted - it will show once a moderator approves it.")
        self.open_forum(self.fid)
        if r.get("id") and not r.get("pending"):
            self.app.push_screen(ThreadScreen(int(r["id"])))

    @work(group="ffollow")
    async def action_follow(self) -> None:
        if not self.cur:
            return
        f = self.cur.get("forum") or {}
        r = await self.app.api.j(f"/api/forums/{f['id']}/follow", {"on": not f.get("following")})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
        else:
            self.app.notify("Following " + f.get("name", "") if not f.get("following") else "Unfollowed " + f.get("name", ""))
            self.open_forum(self.fid)

    def action_notifs(self) -> None:
        self.app.push_screen(ForumNotifs())

    @on(Button.Pressed, "#fmnew")
    def _b1(self) -> None:
        self.action_new_thread()

    @on(Button.Pressed, "#fmsort")
    def _b2(self) -> None:
        self.action_sort()

    @on(Button.Pressed, "#fmsearch")
    def _b3(self) -> None:
        self.action_search()

    @on(Button.Pressed, "#fmnotif")
    def _b4(self) -> None:
        self.action_notifs()


NOTIF_TXT = {"reply": "replied to your thread", "quote": "quoted you", "thread": "started a thread", "approved": "approved your post",
             "rejected": "rejected your post", "removed": "removed your post", "lock": "locked a thread", "hide": "hid a thread",
             "warn": "warned you", "mute": "muted you", "ban": "banned you", "unban": "unbanned you", "unmute": "unmuted you",
             "modded": "made you a moderator", "moved": "moved a thread", "owner": "gave you ownership"}


class ForumNotifs(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back"), Binding("a", "all_seen", "Mark all read")]

    def compose(self) -> ComposeResult:
        yield Label("FORUM NOTIFICATIONS", classes="panel-title")
        yield OptionList(id="nlist")
        yield Footer()

    def on_mount(self) -> None:
        self.load()

    @work(exclusive=True)
    async def load(self) -> None:
        r = await self.app.api.j("/api/forums/notif")
        ol = self.query_one(OptionList)
        ol.clear_options()
        if r.get("error"):
            ol.add_option(Option(Text(r["error"], style=f"{C.err}"), disabled=True))
            return
        self.items = r.get("items") or []
        for it in self.items:
            x = Text()
            x.append("● " if not it.get("seen") else "  ", style=RED)
            x.append(uname(it.get("by")) if it.get("by") else "Moderators", style="bold")
            x.append(" " + NOTIF_TXT.get(it.get("kind"), it.get("kind") or ""))
            if it.get("forum"):
                x.append(f" in {it['forum']}", style=DIM)
            x.append(f" · {ago(it.get('at'))}", style=DIM)
            if it.get("text"):
                x.append("\n   " + str(it["text"])[:200], style=f"{C.text_dim}")
            ol.add_option(Option(x, id=str(it.get("id"))))
        if not self.items:
            ol.add_option(Option(Text("Nothing yet.", style=DIM), disabled=True))
        ol.focus()

    @on(OptionList.OptionSelected)
    async def _open(self, e: OptionList.OptionSelected) -> None:
        it = next((i for i in self.items if str(i.get("id")) == e.option.id), None)
        if not it:
            return
        await self.app.api.j("/api/forums/notif/seen", {"ids": [it["id"]]})
        if it.get("tid"):
            self.app.push_screen(ThreadScreen(int(it["tid"]), last=True, jump=it.get("pid")))
        self.load()

    async def action_all_seen(self) -> None:
        await self.app.api.j("/api/forums/notif/seen", {})
        self.load()


class ThreadScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "reply", "Reply"),
        Binding("q", "quote", "Quote"),
        Binding("plus,u", "vote(1)", "Upvote"),
        Binding("minus", "vote(-1)", "Downvote"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("i", "images", "Images"),
        Binding("f", "follow", "Follow"),
        Binding("right_square_bracket", "page(1)", "Next page"),
        Binding("left_square_bracket", "page(-1)", "Prev page"),
        Binding("ctrl+r", "reload", "Refresh"),
    ]

    def __init__(self, tid: int, last: bool = False, jump: int | None = None):
        super().__init__()
        self.tid, self.last, self.jump = tid, last, jump
        self.page = 1
        self.data: dict = {}
        self.posts: list[dict] = []
        self.rep: dict = {}

    def compose(self) -> ComposeResult:
        yield Static("Loading…", id="threadhead")
        yield OptionList(id="postlog")
        yield Footer()

    def on_mount(self) -> None:
        self.load()
        self.set_interval(6, self.poll_new)

    @work(exclusive=True, group="tload")
    async def load(self) -> None:
        q = "last=1" if self.last else f"page={self.page}"
        r = await self.app.api.j(f"/api/forums/t/{self.tid}?{q}")
        if r.get("error"):
            self.query_one("#threadhead", Static).update(Text(r["error"], style=f"{C.err}"))
            return
        self.last = False
        self.data = r
        self.page = int(r.get("page") or 1)
        self.posts = list(r.get("posts") or [])
        self.rep = dict(r.get("rep") or {})
        self.render_all()

    def render_all(self) -> None:
        r = self.data
        t, f = r.get("thread") or {}, r.get("forum") or {}
        h = Text()
        h.append(f"{f.get('icon') or '#'} {f.get('name', '')} ▸ ", style=DIM)
        if t.get("tag"):
            h.append(f"[{t['tag']}] ", style=f"{C.warn}")
        h.append(t.get("title") or "", style=f"bold {RED}")
        flags = [x for x, k in (("pinned", "pinned"), ("locked", "locked"), ("resolved", "resolved"), ("following", "following")) if t.get(k)]
        h.append(f"\n{_n(t.get('replies', 0), 'reply', 'replies')} · {_n(t.get('views', 0), 'view')} · page {self.page}/{r.get('pages', 1)}" +
                 (" · " + ", ".join(flags) if flags else ""), style=DIM)
        me = r.get("me") or {}
        if not me.get("reply") and me.get("why"):
            h.append(f"\n{me['why']}", style=f"{C.warn}")
        self.query_one("#threadhead", Static).update(h)
        ol = self.query_one("#postlog", OptionList)
        hi = ol.highlighted
        ol.clear_options()
        for p in self.posts:
            ol.add_option(Option(self.post_text(p), id=f"p{p['id']}"))
            ol.add_option(None)
        if self.jump:
            for k, p in enumerate(self.posts):
                if p["id"] == self.jump:
                    ol.highlighted = k * 2
                    break
            self.jump = None
        elif hi is not None and hi < ol.option_count:
            ol.highlighted = hi
        elif ol.option_count:
            ol.highlighted = 0
        ol.focus()

    def post_text(self, p: dict):
        t = (self.data.get("thread") or {})
        F = self.data.get("forum") or {}
        x = Text()
        x.append(uname(p.get("user")), style=f"bold {RED}")
        lvl = (p.get("user") or {}).get("level")
        if lvl:
            x.append(f" Lv{lvl}", style=f"{C.warn}")
        if p.get("uid") == t.get("uid"):
            x.append(" OP", style=f"bold {C.ok}")
        rp = self.rep.get(str(p.get("uid"))) or self.rep.get(p.get("uid"))
        if F.get("rep") and rp and not rp.get("exempt"):
            x.append(f" rep {rp.get('score', 0)}", style=DIM)
        x.append(f"  {full(p.get('created'))}", style=DIM)
        if p.get("edited"):
            x.append(" (edited)", style=DIM)
        sc, mv = p.get("score", 0), p.get("my_vote", 0)
        x.append("   ▲" if mv == 1 else "   △", style=RED if mv == 1 else DIM)
        x.append(f" {sc} ", style="bold")
        x.append("▼" if mv == -1 else "▽", style=RED if mv == -1 else DIM)
        if not p.get("approved", True):
            x.append("  awaiting approval", style=f"{C.warn}")
        q = p.get("quote")
        if q:
            x.append("\n▍ ", style=DIM)
            if q.get("gone"):
                x.append("quoted post removed", style=f"italic {DIM}")
            else:
                x.append(f"{q.get('username', '')} wrote: ", style=f"bold {DIM}")
                x.append((q.get("body") or "")[:300].replace("\n", " "), style=f"italic {DIM}")
        x.append("\n")
        if p.get("deleted") and not p.get("body"):
            x.append("[removed]", style=f"italic {DIM}")
        else:
            x.append_text(forum_body(p.get("body") or ""))
        imgs = p.get("imgs") or []
        pics = self.app.pics
        if imgs and pics.enabled:
            for k, url in enumerate(imgs):
                x.append("\n")
                x.append_text(pics.preview(url, None, None, 76, 20, label=f"image {k + 1}",
                                           on_ready=lambda pid=p["id"]: self._pic_ready(pid)))
            x.append(f"\n{_n(len(imgs), 'image')} · i for full size", style=DIM)
        elif imgs:
            x.append(f"\n🖼  {_n(len(imgs), 'image')} - press i to view", style=f"{C.warn}")
        if pics.enabled:
            u = p.get("user") or {}
            av = pics.avatar(u.get("id"), u.get("av"), u.get("username") or "?", 10, 5,
                             on_ready=lambda pid=p["id"]: self._pic_ready(pid))
            return with_avatar(av, x, 10)
        return x

    def _pic_ready(self, pid: int) -> None:
        p = next((p for p in self.posts if p["id"] == pid), None)
        if p:
            try:
                self.query_one("#postlog", OptionList).replace_option_prompt(f"p{pid}", self.post_text(p))
            except Exception:  # noqa: BLE001
                pass

    def cur_post(self) -> dict | None:
        ol = self.query_one("#postlog", OptionList)
        if ol.highlighted is None:
            return None
        o = ol.get_option_at_index(ol.highlighted)
        pid = int((o.id or "p0")[1:])
        return next((p for p in self.posts if p["id"] == pid), None)

    async def poll_new(self) -> None:
        if not self.posts or self.page < int(self.data.get("pages") or 1) or self.app.screen is not self:
            return
        after = max(p["id"] for p in self.posts)
        r = await self.app.api.j(f"/api/forums/t/{self.tid}/since?after={after}", retries=0)
        if r.get("error") or not r.get("posts"):
            return
        self.rep.update(r.get("rep") or {})
        ol = self.query_one("#postlog", OptionList)
        for p in r["posts"]:
            if any(x["id"] == p["id"] for x in self.posts):
                continue
            self.posts.append(p)
            ol.add_option(Option(self.post_text(p), id=f"p{p['id']}"))
            ol.add_option(None)

    def action_reload(self) -> None:
        self.load()

    def action_page(self, d: int) -> None:
        np = self.page + d
        if 1 <= np <= int(self.data.get("pages") or 1):
            self.page = np
            self.load()

    def _compose_reply(self, quote: dict | None) -> None:
        me = self.data.get("me") or {}
        if not me.get("reply"):
            self.app.notify(me.get("why") or "You can't reply here.", severity="warning")
            return
        pre = ""
        if quote and quote.get("body"):
            lines = [l for l in quote["body"].split("\n") if l.strip() and not l.startswith(">")][:6]
            pre = "\n".join("> " + l for l in lines) + "\n\n"

        def done(body):
            if body is None:
                return
            if not body.strip():
                self.app.notify("Write something first", severity="warning")
                return
            self.send_reply(body, quote["id"] if quote else None)
        title = f"Reply to {uname(quote.get('user'))}" if quote else "Reply"
        self.app.push_screen(Prompt(title, value=pre, multiline=True, ok="Post",
                                    help="Markup: **bold** *italic* __underline__ ~~strike~~ `code` > quote, - list, # heading"), done)

    def action_reply(self) -> None:
        self._compose_reply(None)

    def action_quote(self) -> None:
        p = self.cur_post()
        if p:
            self._compose_reply(p)

    @work(group="treply")
    async def send_reply(self, body: str, quote: int | None) -> None:
        r = await self.app.api.j(f"/api/forums/t/{self.tid}/reply", {"body": body, "imgs": [], "quote": quote})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
            return
        if r.get("pending"):
            self.app.notify("Posted - it will show once a moderator approves it.")
        self.last = True
        self.load()

    @work(group="tvote")
    async def action_vote(self, d: int) -> None:
        p = self.cur_post()
        if not p:
            return
        if p.get("uid") == self.app.me.get("id"):
            self.app.notify("You can't vote on your own post", severity="warning")
            return
        if not p.get("votable", True):
            self.app.notify(p.get("vote_why") or "Voting is off here", severity="warning")
            return
        r = await self.app.api.j(f"/api/forums/p/{p['id']}/vote", {"dir": d})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
            return
        p["score"], p["my_vote"] = r.get("score", p.get("score")), r.get("my_vote", 0)
        self.render_all()

    def action_edit(self) -> None:
        p = self.cur_post()
        if not p:
            return
        if not p.get("can_edit"):
            self.app.notify("You can't edit this post", severity="warning")
            return

        def done(body):
            if body is not None and body.strip():
                self.save_edit(p["id"], body)
        self.app.push_screen(Prompt("Edit post", value=p.get("body") or "", multiline=True, ok="Save"), done)

    @work(group="tedit")
    async def save_edit(self, pid: int, body: str) -> None:
        r = await self.app.api.j(f"/api/forums/p/{pid}/edit", {"body": body})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
        self.load()

    def action_delete(self) -> None:
        p = self.cur_post()
        if not p:
            return
        if not p.get("can_del"):
            self.app.notify("You can't delete this post", severity="warning")
            return
        first = p.get("first")
        msg = "This is the first post - deleting it removes the whole thread." if first else "Delete this post?"

        def done(ok):
            if ok:
                self.do_delete(p["id"])
        self.app.push_screen(Confirm("Delete post", msg, "Delete", danger=True), done)

    @work(group="tdel")
    async def do_delete(self, pid: int) -> None:
        r = await self.app.api.j(f"/api/forums/p/{pid}/delete", {"reason": ""})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
            return
        if r.get("thread_gone"):
            self.app.notify("Thread deleted")
            self.app.pop_screen()
            return
        self.load()

    def action_images(self) -> None:
        p = self.cur_post()
        imgs = (p or {}).get("imgs") or []
        if not imgs:
            self.app.notify("This post has no images")
            return
        if len(imgs) == 1:
            self.app.push_screen(ImageView(f"Image from {uname(p.get('user'))}", imgs[0]))
            return

        def done(v):
            if v is not None:
                self.app.push_screen(ImageView(f"Image {int(v) + 1} from {uname(p.get('user'))}", imgs[int(v)]))
        self.app.push_screen(Choose("Which image?", [(str(k), f"Image {k + 1}") for k in range(len(imgs))], "0"), done)

    @work(group="tfollow")
    async def action_follow(self) -> None:
        t = self.data.get("thread") or {}
        r = await self.app.api.j(f"/api/forums/t/{self.tid}/mod", {"action": "unfollow" if t.get("following") else "follow"})
        if r.get("error"):
            self.app.notify(r["error"], severity="error")
        else:
            self.app.notify("Unfollowed thread" if t.get("following") else "Following thread - you'll be notified of replies")
            self.load()
