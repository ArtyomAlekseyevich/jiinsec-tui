# HTTP session for the jiin.party API. Cookies persist between runs.
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

BASE = os.environ.get("JIIN_BASE", "https://jiin.party").rstrip("/")
CONF_DIR = Path(os.environ.get("JIIN_CONFIG_DIR") or
                Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "jiinsec-tui")
SESSION_FILE = CONF_DIR / "session.json"


class SignedOut(Exception):
    """Raised on 401 (no or expired session)."""


class Http:
    def __init__(self, base: str = BASE):
        self.base = base
        self.client = httpx.AsyncClient(
            base_url=base,
            timeout=httpx.Timeout(20.0, read=40.0),
            follow_redirects=True,
            headers={
                "User-Agent": "jiinsec-tui/0.1 (terminal client)",
                "Accept": "application/json, */*",
                # match the browser's same-origin headers
                "Origin": base,
                "Referer": base + "/",
            },
        )
        self._load_cookies()
        # device-type cookie the site normally sets itself
        host = httpx.URL(base).host
        if not any(c.name == "jdev" for c in self.client.cookies.jar):
            self.client.cookies.set("jdev", "d", domain=host, path="/")

    def has_device_cookie(self) -> bool:
        return any(c.name == "jdid" for c in self.client.cookies.jar)

    # cookies
    def _load_cookies(self) -> None:
        try:
            data = json.loads(SESSION_FILE.read_text())
        except (OSError, ValueError):
            return
        if data.get("base") != self.base:
            return
        for c in data.get("cookies", []):
            self.client.cookies.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))

    def save_cookies(self) -> None:
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in self.client.cookies.jar]
        tmp = SESSION_FILE.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"base": self.base, "cookies": cookies}, f)
        os.replace(tmp, SESSION_FILE)

    def forget(self) -> None:
        self.client.cookies.clear()
        try:
            SESSION_FILE.unlink()
        except OSError:
            pass

    # requests
    async def j(self, url: str, body: Any = None, *, method: str | None = None, retries: int | None = None,
                timeout: float | None = None) -> Any:
        # body given -> POST JSON, else GET. API errors come back as {"error": ...}; 401 -> SignedOut.
        meth = method or ("POST" if body is not None else "GET")
        tries = retries if retries is not None else (0 if meth != "GET" else 2)
        kw: dict[str, Any] = {}
        if body is not None:
            kw["content"] = json.dumps(body, separators=(",", ":")).encode()
            kw["headers"] = {"Content-Type": "text/plain;charset=UTF-8"}
        if timeout is not None:
            kw["timeout"] = timeout
        n = 0
        while True:
            try:
                r = await self.client.request(meth, url, **kw)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                if n < tries:
                    n += 1
                    await asyncio.sleep(0.8 * n)
                    continue
                return {"error": f"Could not reach the server ({e.__class__.__name__})", "_net": True}
            if r.cookies:
                self.save_cookies()
            if r.status_code == 401:
                raise SignedOut()
            try:
                d = r.json()
            except ValueError:
                if n < tries and r.status_code in (429, 500, 502, 503, 504, 520, 521, 522, 523, 524):
                    n += 1
                    await asyncio.sleep(0.9 * n)
                    continue
                return {"error": f"Server error ({r.status_code})", "_status": r.status_code}
            if isinstance(d, dict) and d.get("ipban"):
                return {"error": "This connection is blocked by a ban on the site.", "ipban": True}
            return d

    async def upload(self, url: str, data: bytes, content_type: str) -> Any:
        # upload raw file bytes (pictures, attachments)
        try:
            r = await self.client.post(url, content=data, headers={"Content-Type": content_type}, timeout=120)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            return {"error": f"Upload failed ({e.__class__.__name__})"}
        if r.status_code == 401:
            raise SignedOut()
        if r.status_code == 413:
            return {"error": "That file is too large"}
        try:
            return r.json()
        except ValueError:
            return {"error": f"Server error ({r.status_code})"}

    async def raw(self, url: str) -> bytes:
        r = await self.client.get(url)
        if r.status_code == 401:
            raise SignedOut()
        r.raise_for_status()
        return r.content

    async def aclose(self) -> None:
        await self.client.aclose()
