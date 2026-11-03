"""Request limits: per-IP rate limits on the API and room sockets, and a cap on request bodies.

Everything is in memory, like the drafts and rooms themselves, so the server must run as a
single process. Behind a reverse proxy, run uvicorn with --proxy-headers and set
FORWARDED_ALLOW_IPS to the proxy's address, or every player shares the proxy's IP.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


class TokenBucket:
    """`per_minute` tokens a minute, up to `burst` saved up; one request spends one."""

    def __init__(self, per_minute: float, burst: int):
        self.rate = per_minute / 60.0
        self.burst = burst
        self.tokens = float(burst)
        self.stamp = time.monotonic()

    def take(self) -> float:
        """0 if the request may go ahead, otherwise the seconds until it could."""
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.stamp) * self.rate)
        self.stamp = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.rate

    def full(self) -> bool:
        return self.tokens + (time.monotonic() - self.stamp) * self.rate >= self.burst


@dataclass
class Rule:
    per_minute: float
    burst: int
    buckets: Dict[str, TokenBucket] = field(default_factory=dict)

    def take(self, key: str) -> float:
        bucket = self.buckets.get(key)
        if bucket is None:
            if len(self.buckets) > 10_000:
                self.prune()
            bucket = self.buckets[key] = TokenBucket(self.per_minute, self.burst)
        return bucket.take()

    def prune(self) -> None:
        """Forget the clients whose buckets have refilled: they'd start full anyway."""
        for key in [k for k, b in self.buckets.items() if b.full()]:
            del self.buckets[key]


@dataclass
class Limits:
    create: Tuple[float, int] = (30, 10)     # new drafts and rooms, per IP
    api: Tuple[float, int] = (300, 60)       # every other /api request, per IP
    sockets: Tuple[float, int] = (30, 10)    # room socket connections, per IP
    open_sockets: int = 20                   # room sockets one IP may hold open at once
    messages: Tuple[float, int] = (120, 20)  # messages on one room socket
    max_body: int = 16 * 1024                # bytes in an HTTP request body
    max_message: int = 4 * 1024              # bytes in a room socket message
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "Limits":
        return cls(enabled=os.environ.get("DRAFTIC_RATE_LIMITS", "on").lower() not in ("0", "off", "false"))


def client_ip(scope) -> str:
    client = scope.get("client")
    return client[0] if client else "unknown"


class LimitMiddleware:
    """Plain ASGI so it covers the WebSocket handshake too, not just HTTP."""

    def __init__(self, app, limits: Limits):
        self.app = app
        self.limits = limits
        self.rules = {name: Rule(*getattr(limits, name)) for name in ("create", "api", "sockets")}
        self.open: Dict[str, int] = {}   # IP -> room sockets it holds open

    def rule_for(self, scope) -> Optional[Rule]:
        path = scope["path"]
        if scope["type"] == "websocket":
            return self.rules["sockets"] if path.startswith("/ws/") else None
        if scope["method"] == "POST" and path in ("/api/drafts", "/api/rooms"):
            return self.rules["create"]
        if path.startswith("/api/"):
            return self.rules["api"]
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not self.limits.enabled:
            return await self.app(scope, receive, send)
        ip = client_ip(scope)
        rule = self.rule_for(scope)
        wait = rule.take(ip) if rule else 0.0
        if scope["type"] == "websocket":
            if wait or (rule and self.open.get(ip, 0) >= self.limits.open_sockets):
                await send({"type": "websocket.close", "code": 1008})  # refuses the handshake
                return
            if not rule:
                return await self.app(scope, receive, send)
            self.open[ip] = self.open.get(ip, 0) + 1
            try:
                return await self.app(scope, receive, send)
            finally:
                self.open[ip] -= 1
                if not self.open[ip]:
                    del self.open[ip]
        if wait:
            return await _reply(send, 429, "Too many requests. Slow down.", {"retry-after": str(int(wait) + 1)})
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length and length.isdigit() and int(length) > self.limits.max_body:
            return await _reply(send, 413, "Request too large.")
        await self._capped(scope, receive, send)

    async def _capped(self, scope, receive, send):
        """Counts the body as it arrives, for requests that don't send a Content-Length: past the
        cap, the client gets a 413 and the app sees a disconnect, and nothing it sends goes out."""
        seen = 0
        refused = False

        async def capped_receive():
            nonlocal seen, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limits.max_body:
                    refused = True
                    await _reply(send, 413, "Request too large.")
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if not refused:
                await send(message)

        try:
            await self.app(scope, capped_receive, guarded_send)
        except Exception:
            if not refused:
                raise


async def _reply(send, status: int, detail: str, extra: Optional[dict] = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers += [(k.encode(), v.encode()) for k, v in (extra or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
