"""App entry point. `lifespan` runs once on startup: create tables, seed automations."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

import app.automations  # noqa: F401  (registers automation implementations)
from app.api import automations, digest, email, health, leads, runs, webhooks
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.registry import seed_automations

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_automations(db)
    yield


settings = get_settings()

app = FastAPI(
    title="AutoHub",
    description="One hub for AI automations: every run traced step by step, "
                "with human approval when the AI isn't sure.",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


app.include_router(health.router)
app.include_router(automations.router)
app.include_router(runs.router)
app.include_router(leads.router)
app.include_router(webhooks.router)
app.include_router(digest.router)
app.include_router(email.router)
