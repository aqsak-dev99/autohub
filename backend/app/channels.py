"""Outbound replies. Phase 2 runs in dry-run mode: the reply is recorded on the
run as "would send", nothing leaves the system. Phase 4 adds real WhatsApp
delivery through Twilio behind this same function, so the automation code
doesn't change."""
from __future__ import annotations


def send_reply(channel: str, contact: str, text: str) -> dict:
    return {
        "delivered": False,
        "mode": "dry_run",
        "channel": channel,
        "to": contact,
        "characters": len(text),
        "note": "Real delivery arrives in Phase 4 (Twilio WhatsApp).",
    }
