"""Check the AutoHub inbox for new enquiries. n8n calls this every minute."""
import imaplib

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.leads import require_inbound_key
from app.auth import require_owner
from app.config import get_settings
from app.db import get_db
from app.email_inbox import poll_inbox

router = APIRouter(prefix="/api/email", tags=["email"])


@router.post("/poll", dependencies=[Depends(require_inbound_key), Depends(require_owner)])
def poll(background: BackgroundTasks, db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.email_configured:
        raise HTTPException(400, "Set SMTP_USERNAME and SMTP_PASSWORD (a Google app password) first")
    try:
        result = poll_inbox(db, background, settings)
    except imaplib.IMAP4.error as exc:
        raise HTTPException(502, f"Gmail refused the IMAP login or folder: {exc}. Check the app password, "
                                 "that IMAP is allowed, and IMAP_FOLDER.")
    except OSError as exc:
        raise HTTPException(502, f"Couldn't reach the mail server: {exc}")
    return {"fetched": result.fetched, "started": result.started, "duplicates": result.duplicates,
            "skipped": result.skipped}
