"""Small in-memory rate limits for the public endpoints (login, the contact form, Try it).

In memory on purpose: one server, and a limit that resets on restart is fine for slowing
down guessing and spam. With several servers this would move to Redis.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request


def client_ip(request: Request) -> str:
    """The visitor's address. Behind Render's proxy it's the LAST X-Forwarded-For entry: the proxy
    appends the address it saw, while anything earlier in the header was sent by the visitor and
    could be made up to dodge a limit."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "?"


class SlidingWindow:
    """At most `limit` events per key in the last `seconds`."""

    def __init__(self, limit: int, seconds: float):
        self.limit, self.seconds = limit, seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def _trim(self, key: str) -> deque:
        now, hits = time.monotonic(), self._hits[key]
        while hits and now - hits[0] > self.seconds:
            hits.popleft()
        return hits

    def blocked(self, key: str) -> bool:
        return len(self._trim(key)) >= self.limit

    def add(self, key: str) -> None:
        self._trim(key).append(time.monotonic())

    def hit(self, key: str) -> bool:
        """Record one event; True if it was over the limit (and so not recorded)."""
        if self.blocked(key):
            return True
        self.add(key)
        return False

    def retry_after(self, key: str) -> int:
        hits = self._trim(key)
        return max(1, int(self.seconds - (time.monotonic() - hits[0]))) if hits else 0

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)
