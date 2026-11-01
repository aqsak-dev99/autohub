"""Login for the dashboard and API.

Three kinds of caller:
- owner:   logged in with ADMIN_PASSWORD; can do everything
- viewer:  "Explore the demo" (only when DEMO_MODE is on); can look at everything and use
           Try it, and approve replies only to their own test messages
- machine: n8n or a script sending the X-AutoHub-Key header; treated like the owner

The session is a signed cookie (role + expiry + HMAC), so there's no session table and
nothing to clean up. With no ADMIN_PASSWORD set, login is off and every caller is the
owner, which keeps local development and the tests simple.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, Header, HTTPException, Request

from app.config import Settings, get_settings

COOKIE = "autohub_session"
ROLES = {"owner", "viewer"}
_fallback_secret = secrets.token_urlsafe(32)  # used if SECRET_KEY is unset: logins reset on restart


def _secret(settings: Settings) -> bytes:
    return (settings.secret_key or _fallback_secret).encode()


def _sign(settings: Settings, body: str) -> str:
    digest = hmac.new(_secret(settings), body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_token(role: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    body = f"{role}.{int(time.time()) + settings.session_days * 86400}"
    return f"{body}.{_sign(settings, body)}"


def read_token(token: str | None, settings: Settings | None = None) -> str | None:
    """The role in a valid, unexpired token; None otherwise."""
    settings = settings or get_settings()
    try:
        role, expires, signature = (token or "").split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(settings, f"{role}.{expires}")):
        return None
    if role not in ROLES or int(expires) < time.time():
        return None
    if role == "viewer" and not settings.demo_mode:
        return None  # turning the demo off logs every visitor out
    return role


def password_ok(given: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.admin_password) and secrets.compare_digest(given.encode(), settings.admin_password.encode())


def current_role(request: Request, x_autohub_key: str | None = Header(default=None)) -> str:
    """FastAPI dependency: who is calling. 401 if nobody we know."""
    settings = get_settings()
    if not settings.auth_enabled:
        return "owner"
    if x_autohub_key and settings.inbound_api_key and secrets.compare_digest(x_autohub_key, settings.inbound_api_key):
        return "machine"
    role = read_token(request.cookies.get(COOKIE), settings)
    if role is None:
        raise HTTPException(401, "Please log in")
    return role


def require_owner(role: str = Depends(current_role)) -> str:
    if role == "viewer":
        raise HTTPException(403, "Demo visitors can look around but not change this. Log in as the owner to do that.")
    return role
