"""Fill the database with the sample conversations (no Groq key needed).

    docker compose exec api python -m scripts.seed_demo           # only if there are no leads yet
    docker compose exec api python -m scripts.seed_demo --reset   # wipe conversations first
"""
import argparse

import app.automations  # noqa: F401  (registers the automations)
from app.db import SessionLocal, init_db
from app.demo import seed_demo
from app.registry import seed_automations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete existing runs, leads and approvals first")
    args = parser.parse_args()
    init_db()
    with SessionLocal() as db:
        seed_automations(db)
    added = seed_demo(SessionLocal, reset=args.reset)
    print(f"added {added} sample conversations" if added else "there are leads already; use --reset to start over")


if __name__ == "__main__":
    main()
