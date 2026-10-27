# Mock jiin.party API for --offline mode. Fake members, chat, DMs and forums.
# Uploads are kept in memory and echoed back. Logged in as "tester".
import io
import json
import re
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOCK = threading.Condition()
NOW = time.time
LOG = []

USERS = {
    1: {"id": 1, "username": "jiin", "roles": ["owner"], "hb": [], "av": 3, "last_seen": NOW()},
    2: {"id": 2, "username": "alice", "roles": ["mod"], "hb": [], "av": 2, "last_seen": NOW(), "dev": ["d"], "ml": {"t": "Song — Artist"}},
    3: {"id": 3, "username": "bob", "roles": [], "hb": [], "av": 0, "last_seen": NOW() - 4000},
    4: {"id": 4, "username": "carol", "roles": ["vip"], "hb": [], "av": 0, "last_seen": NOW(), "vc": {"name": "Lounge"}},
    5: {"id": 5, "username": "tester", "roles": [], "hb": [], "av": 4, "last_seen": NOW()},
}
ME = 5
SESS = {"offline": 5}     # offline session
UPLOADS = {}              # id -> (bytes, content type, name)
CHAT = [
    {"id": 1, "uid": 2, "username": "alice", "ts": NOW() - 600, "text": "welcome to the terminal <:wave:7>", "roles": ["mod"], "av": 2, "rx": [{"e": "👍", "n": 2, "me": False, "who": ["bob", "carol"]}]},
    {"id": 2, "uid": 2, "username": "alice", "ts": NOW() - 590, "text": "second line, grouped", "roles": ["mod"], "av": 2},
    {"id": 3, "uid": 4, "username": "carol", "ts": NOW() - 300, "text": "hey @tester look https://example.com", "roles": ["vip"], "av": 0,
     "men": [{"name": "tester", "id": 5}], "ping": True},
    {"id": 4, "uid": 3, "username": "bob", "ts": NOW() - 200, "text": "", "roles": [], "media": {"url": "/media/pic.png", "w": 640, "h": 400, "anim": False},
     "reply": {"id": 3, "username": "carol", "text": "hey @tester look"}},
]
DSEQ = [0]
RSEQ = [0]
RXCH = {}
DELETED = []
TYPING = {}
SOC_V = [1]
DMS = {2: [{"id": 10, "uid": 2, "at": NOW() - 900, "kind": "msg", "text": "hi tester!", "rx": []},
           {"id": 11, "uid": 5, "at": NOW() - 800, "kind": "msg", "text": "hey alice", "reply": {"id": 10, "uid": 2, "username": "alice", "text": "hi tester!"}},
           {"id": 12, "uid": 2, "at": NOW() - 700, "kind": "call", "text": "ended:125"},
           {"id": 13, "uid": 2, "at": NOW() - 600, "kind": "msg", "text": "file for you", "files": [{"name": "notes.txt", "url": "/media/notes.txt", "size": 2048, "ext": "txt", "cat": "doc"}]},
           {"id": 14, "uid": 2, "at": NOW() - 500, "kind": "msg", "text": "look at this view", "media": "/media/view.png", "rx": []},
           {"id": 15, "uid": 2, "at": NOW() - 400, "kind": "msg", "text": "", "files": [{"name": "holiday.png", "url": "/media/holiday.png", "size": 81234, "ext": "png", "cat": "image"}]}]}
GC = {7: {"gc": {"id": 7, "name": "night crew", "owner": 2, "pv": 0, "muted": False},
          "members": [{"id": 2, "username": "alice", "owner": True, "read": 21}, {"id": 5, "username": "tester", "owner": False, "read": 20}],
          "messages": [{"id": 20, "uid": 2, "at": NOW() - 500, "kind": "sys", "sys": {"t": "create", "by": 2, "who": []}},
                       {"id": 21, "uid": 2, "at": NOW() - 400, "kind": "msg", "text": "group hello"}], "names": {}, "friends": [2], "call": None, "more": False}}
FRIENDS = [2]
INCOMING = [4]
NEXT = {"chat": 100, "dm": 100, "post": 100, "file": 1}
FORUMS = [{"id": 1, "name": "General", "handle": "general", "descr": "Talk about anything", "cat": "Community", "icon": "💬", "threads": 2, "posts": 5,
           "followers": 3, "last_at": NOW() - 100, "score": 4, "status": "open", "new": True}]
THREADS = {1: {"id": 1, "fid": 1, "title": "Terminal clients?", "tag": "", "uid": 2, "user": {"id": 2, "username": "alice", "level": 12}, "created": NOW() - 5000,
               "replies": 1, "views": 40, "last_at": NOW() - 100, "last_user": {"id": 3, "username": "bob"}, "pinned": True, "approved": True, "unread": True,
               "excerpt": "Anyone building one?"}}
POSTS = {1: [{"id": 1, "uid": 2, "user": {"id": 2, "username": "alice", "level": 12, "av": 2}, "body": "# Hello\nAnyone building a **terminal** client?\n- one\n- two\n`code` and [link](https://x.org)",
              "created": NOW() - 5000, "approved": True, "first": True, "imgs": [], "score": 3, "my_vote": 0, "votable": True, "can_edit": False, "can_del": False},
             {"id": 2, "uid": 3, "user": {"id": 3, "username": "bob"}, "body": "> Anyone building\nyes!", "created": NOW() - 100, "approved": True,
              "quote": {"username": "alice", "body": "Anyone building a terminal client?"}, "imgs": ["/media/pic.png"], "score": 0, "my_vote": 0, "votable": True}]}


def png_bytes(kind="scene"):
    from PIL import Image, ImageDraw
    if kind == "avatar":
        im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((4, 4, 124, 124), fill=(225, 10, 31, 255))
        d.ellipse((34, 44, 94, 84), fill=(250, 240, 240, 255))
        d.ellipse((54, 54, 74, 74), fill=(10, 0, 0, 255))
    else:
        im = Image.new("RGB", (640, 400))
        d = ImageDraw.Draw(im)
        for y in range(260):
            d.line((0, y, 640, y), fill=(40 + y // 2, 20 + y // 4, 90 - y // 4))
        d.ellipse((380, 120, 520, 260), fill=(255, 190, 60))
        d.rectangle((0, 260, 640, 400), fill=(20, 40, 70))
        d.polygon([(0, 260), (160, 150), (320, 260)], fill=(30, 30, 45))
        d.polygon([(200, 260), (330, 170), (470, 260)], fill=(45, 40, 60))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


PNG = png_bytes()
AVATAR = png_bytes("avatar")


def _av5():
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (256, 256), (70, 130, 200))
    d = ImageDraw.Draw(im)
    d.ellipse((40, 30, 216, 230), fill=(240, 200, 160))          # face
    d.pieslice((36, 14, 220, 150), 180, 360, fill=(80, 50, 30))  # hair
    d.ellipse((85, 105, 115, 135), fill=(255, 255, 255)); d.ellipse((141, 105, 171, 135), fill=(255, 255, 255))
    d.ellipse((94, 112, 108, 128), fill=(30, 30, 60)); d.ellipse((150, 112, 164, 128), fill=(30, 30, 60))
    d.arc((90, 140, 166, 200), 20, 160, fill=(150, 40, 40), width=8)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


AVATAR5 = _av5()


def bump():
    with LOCK:
        SOC_V[0] += 1
        LOCK.notify_all()


def social():
    convs = [{"user": {"id": 2, "username": "alice"}, "last": {**DMS[2][-1], "file": "notes.txt"} if DMS[2] else None, "unread": 1, "at": NOW()}]
    for uid, msgs in DMS.items():
        if uid != 2 and msgs:
            convs.append({"user": {"id": uid, "username": USERS[uid]["username"]}, "last": msgs[-1], "unread": 0, "at": msgs[-1]["at"]})
    g = GC[7]
    return {"v": SOC_V[0], "counts": {"friend_new": len(INCOMING), "req_new": 1, "unread": 1, "gc_unread": 0, "mentions": 0},
            "convs": convs,
            "groups": [{"id": 7, "name": g["gc"]["name"], "pv": 0, "last": {**g["messages"][-1], "name": "alice"}, "unread": 0, "muted": False, "count": 2, "at": NOW()}],
            "friends": [{"id": i, "username": USERS[i]["username"]} for i in FRIENDS],
            "incoming": [{"id": i, "username": USERS[i]["username"], "new": True, "at": NOW()} for i in INCOMING],
            "outgoing": [], "blocked": [], "requests": [{"user": {"id": 3, "username": "bob"}, "new": True, "at": NOW(), "last": {"text": "can we talk?"}}],
            "dm_open": True, "calls": {}, "gcalls": {}, "ring": None, "grings": []}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def sid(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c["sid"].value if "sid" in c else None

    def send(self, obj, status=200, cookies=(), raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, meth):
        u = urlparse(self.path)
        p, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        raw = self.body() if meth in ("POST", "DELETE") else b""
        LOG.append((meth, self.path, raw[:200], self.headers.get("Content-Type"), self.headers.get("Origin")))
        if p == "/":
            return self.send(None, raw=b"<html></html>", ctype="text/html", cookies=["jdid=dev123; Path=/; HttpOnly"])
        if p.startswith("/api/avatar/"):
            return self.send(None, raw=AVATAR if p.startswith("/api/avatar/2") else AVATAR5, ctype="image/png")
        if p.startswith("/api/banner/"):
            return self.send(None, raw=PNG, ctype="image/png")
        if p.startswith("/up/"):
            data, ct, _ = UPLOADS.get(p[4:], (b"", "text/plain", ""))
            return self.send(None, raw=data, ctype=ct)
        if p.startswith("/media/"):
            return self.send(None, raw=PNG if p.endswith(".png") else b"hello", ctype="image/png" if p.endswith(".png") else "text/plain")
        authed = self.sid() in SESS
        if p == "/api/me":
            return self.send({"user": {**USERS[ME], "admin": False, "staff": False, "rank": 0, "level": 7, "tos": True, "tos_ver": 2, "fm_unread": 2,
                                       "lvl_req": {"chat_img": 5, "chat_gif": 50}, "rv": 1}} if authed else {"user": None, "has_users": True})
        if p == "/api/login":
            b = json.loads(raw or b"{}")
            if b.get("username") == "tester" and b.get("password") == "correct-horse":
                SESS["s1"] = ME
                return self.send({"ok": True}, cookies=["sid=s1; Path=/; HttpOnly"])
            if b.get("username") == "newbie":
                return self.send({"verify": {"pid": 99, "email": "n***@example.com", "resend_in": 30, "sends_left": 3}})
            return self.send({"error": "Wrong username or password"}, 400)
        if p == "/api/register/verify":
            b = json.loads(raw)
            if b == {"pid": 99, "code": "123456"}:
                SESS["s1"] = ME
                return self.send({"user": USERS[ME]}, cookies=["sid=s1; Path=/; HttpOnly"])
            return self.send({"error": "That code is wrong"}, 400)
        if not authed:
            return self.send({"error": "auth"}, 401)
        if p == "/api/logout":
            SESS.clear()
            return self.send({"ok": True})
        if p == "/api/members":
            for uid in (1, 2, 4, 5):
                USERS[uid]["last_seen"] = NOW()
            return self.send({"members": list(USERS.values()), "now": NOW(), "rv": 1})
        if p == "/api/roles":
            return self.send({"ver": 1, "roles": [
                {"id": "owner", "label": "Owner", "color": "#ffffff", "nc": True, "show": {"members": True, "sep": True}},
                {"id": "mod", "label": "Moderator", "color": "#394fb1", "nc": True, "show": {"members": True, "sep": True}},
                {"id": "vip", "label": "VIP", "color": "#ffd700", "nc": True, "show": {"members": True, "sep": False}}]})
        if p == "/api/emojis":
            return self.send({"emojis": [{"id": 7, "name": "wave", "a": False, "v": 1}, {"id": 8, "name": "skull", "a": False, "v": 1}], "ev": 1})
        if p == "/api/site":
            return self.send({"search_enabled": False, "announcements_enabled": True})
        if p == "/api/announcements":
            return self.send({"announcements": [{"id": 1, "title": "Terminal client spotted", "body": "Be nice to @tester", "author": "jiin",
                                                 "published_at": NOW() - 3600, "pinned": True, "priority": "important"}]})
        if p == "/api/chat" and meth == "GET":
            since = int(q.get("since", 0))
            out = {"messages": [m for m in CHAT if m["id"] > since], "dseq": DSEQ[0], "rseq": RSEQ[0], "ev": 1, "mute": None, "slow": 0}
            if "dseq" in q and int(q["dseq"]) < DSEQ[0]:
                out["deleted"] = DELETED
            if "rseq" in q and int(q["rseq"]) < RSEQ[0]:
                out["rx"] = {str(k): v for k, v in RXCH.items()}
            return self.send(out)
        if p == "/api/chat" and meth == "POST":
            b = json.loads(raw)
            if not b.get("text") and not b.get("media"):
                return self.send({"error": "empty"}, 400)
            NEXT["chat"] += 1
            m = {"id": NEXT["chat"], "uid": ME, "username": "tester", "av": 4, "ts": NOW(), "text": re.sub(r":wave:", "<:wave:7>", b.get("text", "")), "roles": []}
            if b.get("reply_to"):
                o = next(x for x in CHAT if x["id"] == b["reply_to"])
                m["reply"] = {"id": o["id"], "username": o["username"], "text": o["text"]}
            if b.get("media"):
                data, ct, _ = UPLOADS.get(str(b["media"]), (PNG, "image/png", ""))
                try:
                    from PIL import Image
                    im = Image.open(io.BytesIO(data)); w, h = im.size; anim = bool(getattr(im, "is_animated", False))
                except Exception:
                    w, h, anim = 640, 400, False
                m["media"] = {"url": f"/up/{b['media']}", "w": w, "h": h, "anim": anim}
            CHAT.append(m)
            return self.send({"ok": True, "id": m["id"]})
        if p == "/api/chat/react":
            b = json.loads(raw)
            m = next(x for x in CHAT if x["id"] == b["msg_id"])
            rx = m.setdefault("rx", [])
            ex = next((x for x in rx if x["e"] == b["emoji"]), None)
            if ex and ex["me"]:
                ex["n"] -= 1
                ex["me"] = False
                if not ex["n"]:
                    rx.remove(ex)
            elif ex:
                ex["n"] += 1
                ex["me"] = True
            else:
                rx.append({"e": b["emoji"], "n": 1, "me": True, "who": ["tester"]})
            RSEQ[0] += 1
            RXCH[m["id"]] = rx
            return self.send({"id": m["id"], "rx": rx})
        if p.startswith("/api/chat/") and meth == "DELETE":
            mid = int(p.rsplit("/", 1)[1])
            CHAT[:] = [m for m in CHAT if m["id"] != mid]
            DELETED.append(mid)
            DSEQ[0] += 1
            return self.send({"ok": True})
        if p == "/api/chat/typing":
            if meth == "POST":
                TYPING[ME] = json.loads(raw).get("typing")
                return self.send({"ok": True})
            return self.send({"typing": [{"id": 2, "username": "alice"}]})
        if p == "/api/chat/media":
            NEXT["file"] += 1
            UPLOADS[str(NEXT["file"])] = (raw, self.headers.get("Content-Type") or "image/png", "picture")
            return self.send({"media": {"id": NEXT["file"], "anim": (self.headers.get("Content-Type") or "").endswith("gif")}})
        if p == "/api/social":
            return self.send(social())
        if p == "/api/social/poll":
            v = int(q.get("v", 0))
            with LOCK:
                LOCK.wait_for(lambda: SOC_V[0] != v, timeout=25)
            return self.send({"v": SOC_V[0]})
        m = re.match(r"^/api/dm/(\d+)(/.*)?$", p)
        if m:
            uid, rest = int(m.group(1)), m.group(2) or ""
            msgs = DMS.setdefault(uid, [])
            if rest == "" and meth == "GET":
                return self.send({"user": {"id": uid, "username": USERS[uid]["username"]}, "messages": msgs, "more": False, "friends": uid in FRIENDS,
                                  "conv": {"status": "ok"} if msgs else None, "dm_open": True, "other_read": 11})
            if rest == "" and meth == "POST":
                b = json.loads(raw)
                NEXT["dm"] += 1
                nm = {"id": NEXT["dm"], "uid": ME, "at": NOW(), "kind": "msg", "text": b.get("text", ""), "rx": []}
                for fid in b.get("files") or []:
                    data, ct, name = UPLOADS.get(str(fid), (b"", "application/octet-stream", "file"))
                    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                    nm.setdefault("files", []).append({"name": name, "url": f"/up/{fid}", "size": len(data), "ext": ext,
                                                       "cat": "image" if ct.startswith("image/") else "doc"})
                if b.get("reply_to"):
                    o = next(x for x in msgs if x["id"] == b["reply_to"])
                    nm["reply"] = {"id": o["id"], "uid": o["uid"], "username": USERS[o["uid"]]["username"], "text": o.get("text", "")}
                msgs.append(nm)
                bump()
                return self.send({"ok": True, "request": uid not in FRIENDS})
            if rest == "/react":
                b = json.loads(raw)
                mm = next(x for x in msgs if x["id"] == b["msg_id"])
                mm["rx"] = [{"e": b["emoji"], "n": 1, "me": True, "who": ["tester"]}]
                return self.send({"rx": mm["rx"]})
            if rest.startswith("/msg/"):
                mid = int(rest.split("/")[2])
                msgs[:] = [x for x in msgs if x["id"] != mid]
                return self.send({"ok": True})
            if rest == "/file":
                NEXT["file"] += 1
                UPLOADS[str(NEXT["file"])] = (raw, self.headers.get("Content-Type") or "application/octet-stream", q.get("name", "file"))
                return self.send({"file": {"id": NEXT["file"]}})
            return self.send({"ok": True})
        if re.match(r"^/api/gc/\d+/file$", p):
            NEXT["file"] += 1
            UPLOADS[str(NEXT["file"])] = (raw, self.headers.get("Content-Type") or "application/octet-stream", q.get("name", "file"))
            return self.send({"file": {"id": NEXT["file"]}})
        m = re.match(r"^/api/gc/(\d+)$", p)
        if m:
            g = GC[int(m.group(1))]
            if meth == "POST":
                b = json.loads(raw)
                gm = {"id": 30 + len(g["messages"]), "uid": ME, "at": NOW(), "kind": "msg", "text": b.get("text")}
                for fid in b.get("files") or []:
                    data, ct, name = UPLOADS.get(str(fid), (b"", "application/octet-stream", "file"))
                    gm.setdefault("files", []).append({"name": name, "url": f"/up/{fid}", "size": len(data), "ext": "",
                                                       "cat": "image" if ct.startswith("image/") else "doc"})
                g["messages"].append(gm)
                bump()
                return self.send({"ok": True})
            return self.send(g)
        if p.startswith("/api/friends/") or p.startswith("/api/blocks/"):
            b = json.loads(raw or b"{}")
            if p == "/api/friends/accept" and b.get("uid") in INCOMING:
                INCOMING.remove(b["uid"])
                FRIENDS.append(b["uid"])
            bump()
            return self.send({"ok": True})
        if p == "/api/forums":
            return self.send({"forums": FORUMS, "cats": ["Community"], "can_create": True, "more": False})
        m = re.match(r"^/api/forums/(\d+)$", p)
        if m:
            return self.send({"forum": {**FORUMS[0], "tags": ["help"], "following": False, "owner": {"id": 2, "username": "alice"}},
                              "me": {"thread": True, "mod": False}, "counts": {}, "threads": list(THREADS.values()), "page": 1, "pages": 1})
        m = re.match(r"^/api/forums/(\d+)/thread$", p)
        if m:
            b = json.loads(raw)
            tid = len(THREADS) + 1
            THREADS[tid] = {"id": tid, "fid": 1, "title": b["title"], "tag": b["tag"], "uid": ME, "user": {"id": ME, "username": "tester"}, "created": NOW(),
                            "replies": 0, "views": 0, "last_at": NOW(), "approved": True}
            POSTS[tid] = [{"id": 900 + tid, "uid": ME, "user": {"id": ME, "username": "tester"}, "body": b["body"], "created": NOW(), "approved": True,
                           "first": True, "imgs": [], "score": 0, "my_vote": 0, "votable": False, "can_edit": True, "can_del": True}]
            return self.send({"id": tid, "pending": False})
        m = re.match(r"^/api/forums/t/(\d+)(/\w+)?$", p)
        if m:
            tid, rest = int(m.group(1)), m.group(2) or ""
            if rest == "/since":
                return self.send({"posts": [x for x in POSTS[tid] if x["id"] > int(q["after"])], "rep": {}})
            if rest == "/reply":
                b = json.loads(raw)
                NEXT["post"] += 1
                POSTS[tid].append({"id": NEXT["post"], "uid": ME, "user": {"id": ME, "username": "tester"}, "body": b["body"], "created": NOW(),
                                   "approved": True, "imgs": [], "score": 0, "my_vote": 0, "votable": False, "can_edit": True, "can_del": True,
                                   "quote": {"username": "alice", "body": "quoted"} if b.get("quote") else None})
                return self.send({"pending": False})
            if rest == "/mod":
                return self.send({"ok": True})
            t = THREADS[tid]
            return self.send({"thread": t, "forum": {"id": 1, "name": "General", "icon": "💬", "tags": [], "max_imgs": 4, "rep": True},
                              "me": {"reply": True}, "posts": POSTS[tid], "page": 1, "pages": 1, "rep": {"2": {"score": 9}}})
        m = re.match(r"^/api/forums/p/(\d+)/(\w+)$", p)
        if m:
            pid, act = int(m.group(1)), m.group(2)
            for ps in POSTS.values():
                for x in ps:
                    if x["id"] == pid:
                        if act == "vote":
                            d = json.loads(raw)["dir"]
                            x["my_vote"] = 0 if x["my_vote"] == d else d
                            x["score"] += d
                            return self.send({"score": x["score"], "my_vote": x["my_vote"]})
                        if act == "edit":
                            x["body"] = json.loads(raw)["body"]
                            x["edited"] = NOW()
                        if act == "delete":
                            ps.remove(x)
                        return self.send({"ok": True})
            return self.send({"error": "No such post"}, 404)
        if p == "/api/forums/notif":
            return self.send({"items": [{"id": 1, "seen": False, "kind": "reply", "by": {"id": 3, "username": "bob"}, "text": "yes!", "forum": "General", "at": NOW() - 100, "tid": 1, "pid": 2, "fid": 1}]})
        if p == "/api/forums/notif/seen":
            return self.send({"unread": 0})
        if p == "/api/forums/search":
            return self.send({"items": [{"id": 1, "title": "Terminal clients?", "snip": "Anyone building a \x02terminal\x03 client", "icon": "💬", "forum": "General", "replies": 1, "last_at": NOW()}]})
        if p.startswith("/api/forums/user/"):
            return self.send({"threads": 1, "replies": 3})
        if p.startswith("/api/profile/"):
            uid = int(p.rsplit("/", 1)[1])
            u = USERS[uid]
            return self.send({"profile": {**u, "bv": 1 if uid == 2 else 0, "level": 12, "bio": "I like <:wave:7> and terminals", "created": "Oct 2026", "now": NOW(),
                                          "socials": [{"p": "github", "d": "alice", "u": "https://github.com/alice"}], "rep": 5, "my_vote": 0}})
        if p == "/api/rep/2":
            return self.send({"rep": 6, "my_vote": 1})
        if p == "/api/bio":
            return self.send({"bio": "x"})
        return self.send({"error": f"mock: no route {meth} {p}"}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    print("mock on", port, flush=True)
    srv.serve_forever()
