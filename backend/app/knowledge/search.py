"""Keyword search (BM25) over the knowledge base, ported from flowpath's assistant.

Why BM25 and not embeddings: the knowledge base is ~20 short passages. At
that size keyword search is accurate, free and instant, and flowpath's own
assistant passed its 29-case eval set with it. Customers write in Roman Urdu,
Urdu or Arabic, which keyword search can't match against English passages,
so the classify step first rewrites the request as a short English search
query. Whether embeddings would find passages BM25 misses is measured in the
Phase 6 evals before adding them.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from app.knowledge import flowpath

STOP = set(
    "a an and are as at be but by can could do does for from get had has have how i if in is it its me my of on or "
    "our so than that the their them then there these they this to us was we what when where which who will with "
    "would you your any some about am been did not tell more please know want need like give show explain detail "
    "thing also just really".split()
)

# Words a customer might use, mapped to the words the site uses
SYNONYMS: dict[str, list[str]] = {
    "price": ["cost", "fee", "spend"], "pricing": ["cost", "fee", "spend"], "charge": ["cost", "fee"],
    "expensive": ["cost", "fee"], "rate": ["cost", "fee"], "budget": ["cost", "spend"],
    "ad": ["advertising", "campaign"], "ads": ["advertising", "campaign"], "advert": ["advertising"],
    "facebook": ["meta"], "insta": ["instagram", "social"], "instagram": ["social"], "tiktok": ["social"],
    "google": ["search"], "rank": ["ranking", "seo", "search"], "seo": ["search", "ranking"],
    "restaurant": ["food"], "cafe": ["restaurant"], "property": ["housing"], "estate": ["housing"],
    "fashion": ["clothing"], "clothes": ["clothing"], "beauty": ["skincare"],
    "job": ["role", "hiring"], "career": ["role", "hiring"], "vacancy": ["role", "hiring"], "hire": ["hiring", "role"],
    "location": ["based", "address", "studio"], "office": ["studio", "address"], "phone": ["call", "whatsapp"],
    "reach": ["contact", "email"], "abroad": ["worldwide"], "international": ["worldwide"],
    "process": ["step", "work"], "approach": ["step", "process"], "staff": ["team"], "people": ["team"],
    "employee": ["team"], "long": ["soon", "month", "week"], "fast": ["soon"], "quickly": ["soon"],
    "contract": ["minimum"], "commitment": ["minimum", "contract"], "startup": ["small", "business"],
    "sme": ["small", "business"],
}

K1 = 1.4
B = 0.6
MIN_SCORE = 0.5


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str, expand: bool = False) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    words = [w for w in re.sub(r"[^a-z0-9\s]", " ", text).split() if w and w not in STOP]
    out: list[str] = []
    for word in words:
        out.append(_stem(word))
        if expand:
            for extra in SYNONYMS.get(word) or SYNONYMS.get(_stem(word)) or []:
                out.append(_stem(extra))
    return out


@dataclass(frozen=True)
class Passage:
    id: str
    title: str
    label: str
    url: str
    text: str


class KnowledgeBase:
    def __init__(self, passages: list[dict]):
        self.passages = [Passage(**p) for p in passages]
        self.by_id = {p.id: p for p in self.passages}
        # a short fingerprint of the content, stored on every retrieval step,
        # so a run can be traced back to the exact knowledge it used
        self.version = hashlib.sha256(json.dumps(passages, sort_keys=True).encode()).hexdigest()[:10]

        self._docs = []
        for p in self.passages:
            tokens = tokenize(p.title) * 2 + tokenize(p.text)  # the title counts double
            counts: dict[str, int] = {}
            for t in tokens:
                counts[t] = counts.get(t, 0) + 1
            self._docs.append((p, counts, len(tokens)))
        self._avg_len = sum(d[2] for d in self._docs) / len(self._docs)
        self._df: dict[str, int] = {}
        for _, counts, _ in self._docs:
            for t in counts:
                self._df[t] = self._df.get(t, 0) + 1

    def search(self, query: str, limit: int = 3) -> list[tuple[Passage, float]]:
        terms = set(tokenize(query, expand=True))
        n = len(self._docs)
        hits = []
        for passage, counts, length in self._docs:
            score = 0.0
            for term in terms:
                tf = counts.get(term)
                if not tf:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / self._avg_len))
            if score > MIN_SCORE:
                hits.append((passage, round(score, 3)))
        hits.sort(key=lambda h: h[1], reverse=True)
        return hits[:limit]

    def full_text(self) -> str:
        return "\n".join(p.text for p in self.passages)


@lru_cache
def get_kb() -> KnowledgeBase:
    return KnowledgeBase(flowpath.build_passages())
