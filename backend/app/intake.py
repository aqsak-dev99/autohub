"""The one way outside events become runs, exactly once: a customer message (email poll, contact form)
becomes a Lead Handler run, and a quiet lead becomes one Follow-up Nudge run."""
import logging

from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engine.dispatch import dispatch
from app.engine.executor import create_run
from app.models import InboundMessage

log = logging.getLogger("autohub.intake")


def start_lead(db: Session, background: BackgroundTasks, *, provider: str, external_id: str, payload: dict) -> bool:
    """Record a message once and queue a Lead Handler run for it. False if it was a duplicate."""
    return start_once(db, background, slug="lead_handler", provider=provider, external_id=external_id, payload=payload)


def start_once(db: Session, background: BackgroundTasks, *, slug: str, provider: str, external_id: str,
               payload: dict) -> bool:
    """Queue a run of `slug` for this external event, unless one was already started for it."""
    # claim the message id first: the unique constraint makes a second delivery fail here,
    # before any run exists, even if two deliveries arrive at the same moment
    inbound = InboundMessage(provider=provider, external_id=external_id)
    db.add(inbound)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        log.info("duplicate delivery of %s ignored", external_id)
        return False

    run = create_run(db, slug, payload)
    inbound.run_id = run.id
    db.commit()
    dispatch(run.id, background)
    return True
