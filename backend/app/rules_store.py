"""The Lead Handler's routing rules, as the business owner sets them on the Rules page.

Some checks are not switches: unsupported claims, a reply in the wrong language and
an unsupported customer language always go to a person, because those are the ways an
AI reply can be wrong or embarrassing without anyone noticing.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AppSetting

KEY = "lead_rules"
LANGUAGES = ("english", "roman_urdu", "urdu", "arabic")


class LeadRules(BaseModel):
    auto_send_confidence: float = Field(ge=0.5, le=1.0)
    review_languages: list[str]
    review_price_not_on_site: bool = True
    review_existing_client: bool = True
    review_unoffered_service: bool = True

    @field_validator("review_languages")
    @classmethod
    def known_languages(cls, value: list[str]) -> list[str]:
        unknown = set(value) - set(LANGUAGES)
        if unknown:
            raise ValueError(f"unknown language(s): {', '.join(sorted(unknown))}")
        return [lang for lang in LANGUAGES if lang in value]  # stable order


def defaults(settings: Settings) -> LeadRules:
    return LeadRules(auto_send_confidence=settings.auto_send_confidence,
                     review_languages=[x for x in LANGUAGES if x in settings.review_language_set])


def get_rules(db: Session, settings: Settings) -> LeadRules:
    row = db.get(AppSetting, KEY)
    if row is None:
        return defaults(settings)
    return LeadRules(**{**defaults(settings).model_dump(), **row.value})


def save_rules(db: Session, rules: LeadRules) -> LeadRules:
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=rules.model_dump()))
    else:
        row.value = rules.model_dump()
    db.commit()
    return rules
