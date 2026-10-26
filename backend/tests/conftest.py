"""Loaded by pytest before any test module.

Forces test settings no matter what's running on the machine: a throwaway
SQLite file, no Groq key, and an unreachable Redis, so tests never touch
the real database or queue even while `docker compose up` is running.
"""
import os
import pathlib

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["RUN_MODE"] = "inline"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ["GROQ_API_KEY"] = ""
os.environ["INBOUND_API_KEY"] = ""

pathlib.Path("test.db").unlink(missing_ok=True)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    # tenacity would really sleep between retries; make tests instant
    import tenacity.nap

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda s: None)


def pytest_sessionfinish(session, exitstatus):
    pathlib.Path("test.db").unlink(missing_ok=True)
