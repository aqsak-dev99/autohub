"""Logging in and out of the dashboard."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth import COOKIE, make_token, password_ok, read_token
from app.config import get_settings
from app.ratelimit import SlidingWindow, client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])

# wrong passwords per visitor: 5 tries, then wait. Slows guessing to a crawl; the owner, who
# knows the password, never notices. Only failures count, and a success clears them.
failed_logins = SlidingWindow(limit=5, seconds=15 * 60)


class LoginIn(BaseModel):
    password: str


class MeOut(BaseModel):
    role: str | None          # owner | viewer | None (not logged in)
    login_required: bool
    demo_available: bool


def _set_cookie(request: Request, response: Response, role: str) -> None:
    settings = get_settings()
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, make_token(role, settings), max_age=settings.session_days * 86400,
                        httponly=True, samesite="lax", secure=https)


@router.get("/me", response_model=MeOut)
def me(request: Request):
    settings = get_settings()
    if not settings.auth_enabled:
        return MeOut(role="owner", login_required=False, demo_available=False)
    return MeOut(role=read_token(request.cookies.get(COOKIE), settings), login_required=True,
                 demo_available=settings.demo_mode)


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response):
    ip = client_ip(request)
    if failed_logins.blocked(ip):
        wait = -(-failed_logins.retry_after(ip) // 60)
        raise HTTPException(429, f"Too many wrong passwords. Try again in {wait} minute{'s' if wait != 1 else ''}.",
                            headers={"Retry-After": str(failed_logins.retry_after(ip))})
    if not password_ok(body.password):
        failed_logins.add(ip)
        raise HTTPException(401, "That password isn't right")
    failed_logins.reset(ip)
    _set_cookie(request, response, "owner")
    return MeOut(role="owner", login_required=True, demo_available=get_settings().demo_mode)


@router.post("/demo", response_model=MeOut)
def demo(request: Request, response: Response):
    if not get_settings().demo_mode:
        raise HTTPException(404, "The demo isn't available on this server")
    _set_cookie(request, response, "viewer")
    return MeOut(role="viewer", login_required=True, demo_available=True)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}
