"""Loaded by pytest before any test module.

Forces test settings no matter what's running on the machine: a throwaway
SQLite file, no Groq key, and an unreachable Redis, so tests never touch
the real database or queue even while `docker compose up` is running.
"""
import os
import pathlib

# Tests must not depend on the machine they run on. Inside the API container (docker compose exec api
# pytest) the real .env is loaded: ADMIN_PASSWORD would switch login on, EMAIL_SEND_ALLOWLIST would turn
# sends into dry runs, and so on. So every AutoHub setting is cleared first and only the test values below apply.
from app.config import Settings  # noqa: E402  (only the class: nothing connects to anything yet)

_test_db = os.environ.get("TEST_DATABASE_URL")
for _name in Settings.model_fields:
    os.environ.pop(_name.upper(), None)
Settings.model_config["env_file"] = None  # and don't read a .env file from the current folder either

# TEST_DATABASE_URL runs the same tests on Postgres (an empty database; it is wiped first)
os.environ["DATABASE_URL"] = _test_db or "sqlite:///./test.db"
os.environ["RUN_MODE"] = "inline"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ["GROQ_API_KEY"] = ""
os.environ["INBOUND_API_KEY"] = ""

pathlib.Path("test.db").unlink(missing_ok=True)
if os.environ["DATABASE_URL"].startswith("postgresql"):
    import sqlalchemy

    with sqlalchemy.create_engine(os.environ["DATABASE_URL"]).begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    # tenacity would really sleep between retries; make tests instant
    import tenacity.nap

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda s: None)


def pytest_sessionfinish(session, exitstatus):
    pathlib.Path("test.db").unlink(missing_ok=True)
