"""Logging in and out of the dashboard."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth import COOKIE, make_token, password_ok, read_token
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
    if not password_ok(body.password):
        raise HTTPException(401, "That password isn't right")
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
