"""App entry point. `lifespan` runs once on startup: migrate the database, seed automations (and demo data)."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import app.automations  # noqa: F401  (registers automation implementations)
from app.api import auth, automations, digest, email, follow_ups, forms, health, leads, rules, runs, stats
from app.auth import current_role
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.demo import seed_if_empty
from app.engine.executor import recover_interrupted
from app.registry import seed_automations

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_automations(db)
        recover_interrupted(db)  # runs a previous process left half done
    seed_if_empty(SessionLocal)  # only when DEMO_SEED is on (the public demo)
    yield


settings = get_settings()

app = FastAPI(
    title="AutoHub",
    description="One hub for AI automations: every run traced step by step, "
                "with human approval when the AI isn't sure.",
    version="0.8.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # the dashboard, plus flowpath's site, which posts the public contact form from the browser
    allow_origins=[settings.frontend_origin] + [o.strip() for o in settings.form_allowed_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)




# open: health checks, logging in, and the public contact form (which has its own protections)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(forms.router)
# everything else needs a login (or the X-AutoHub-Key for n8n and scripts)
login = [Depends(current_role)]
for module in (automations, runs, leads, digest, email, follow_ups, stats, rules):
    app.include_router(module.router, dependencies=login)


# In production one server does it all: the API above, plus the built dashboard (frontend/dist,
# copied to STATIC_DIR by the Dockerfile). Any path that isn't the API gets index.html, so
# links like /conversations/<id> work when opened directly. In development Vite serves the
# dashboard instead, and / just points at the API docs.
STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))

if (STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard(path: str):
        if path.startswith(("api/", "docs", "openapi.json", "health")):
            raise HTTPException(404)
        file = (STATIC_DIR / path).resolve()
        if path and file.is_file() and STATIC_DIR.resolve() in file.parents:
            return FileResponse(file)  # favicon and other files at the top level
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")
