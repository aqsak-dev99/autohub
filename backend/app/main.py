"""App entry point. `lifespan` runs once on startup: create tables, seed automations."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import automations, health
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.registry import seed_automations


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
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(automations.router)
