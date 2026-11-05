"""Deterministic, conservative detectors for natural-language action claims.

Two detectors operate on free text:

* :func:`detect_success_claims` finds sentences in which the agent affirms that a
  transactional action *has been completed* (rebooked, cancelled, refunded, hold
  placed or released, passenger notified, approval granted).
* :func:`action_categories` lists the action categories a piece of text *mentions*
  (used for user requests and for instructions found in untrusted tool output).

Design limits (deliberate, documented):

* Claims are recognised only in completed-action phrasing (``has been
  cancelled``, ``I rebooked``, ``refund was issued``, ``you are now booked``).
  State read-outs such as ``Booking PNR456 is confirmed`` or ``AS310 is
  cancelled`` (a flight status) are not treated as claims.
* A clause containing a negation or hedge (``not``, ``unable``, ``will``,
  ``pending``, ``if`` ...) is ignored, so ``was not rebooked`` or ``will be
  refunded once approved`` never count. A claim and a negation in the same
  clause therefore yield a false negative, never a false positive.
* English only; no paraphrase or synonym model. Precision is preferred over
  recall: an undetected claim is possible, a fabricated one is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

REBOOK: Final[str] = "rebook"
CANCEL: Final[str] = "cancel"
REFUND: Final[str] = "refund"
HOLD: Final[str] = "hold"
RELEASE: Final[str] = "release"
NOTIFY: Final[str] = "notify"
APPROVAL: Final[str] = "approval"

CLAIM_CATEGORIES: Final[tuple[str, ...]] = (REBOOK, CANCEL, REFUND, HOLD, RELEASE, NOTIFY, APPROVAL)

_BOOKING_NOUN = r"(?:booking|reservation|ticket|itinerary|trip|flight change)"

# Completed-action phrasing per category. Patterns are matched on lower-cased text.
_CLAIM_PATTERNS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    REBOOK: (
        re.compile(r"\bre-?booked\b"),
        re.compile(r"\b(?:i|we)(?: have|'ve)? booked\b"),
        re.compile(r"\byou(?: are|'re)(?: now)? booked\b"),
        re.compile(
            r"\b(?:i|we)(?: have|'ve)? confirmed (?:the |your )?(?:re-?booking|new flight|seat)"
        ),
        re.compile(
            r"\bre-?booking (?:has been|was|is now) (?:confirmed|completed|complete|processed)\b"
        ),
        re.compile(rf"\b{_BOOKING_NOUN} (?:has been|is now) (?:confirmed|changed|updated|moved)\b"),
    ),
    CANCEL: (
        re.compile(
            rf"\b{_BOOKING_NOUN}\b[^,;:]*?\b(?:has been|have been|was|were|is now) cancell?ed\b"
        ),
        re.compile(rf"\b(?:i|we)(?: have|'ve)? cancell?ed (?:the |your )?{_BOOKING_NOUN}"),
    ),
    REFUND: (
        re.compile(r"\b(?:has been|have been|was|were|is now)\b[^,;:]*?\brefunded\b"),
        re.compile(r"\b(?:i|we)(?: have|'ve)? refunded\b"),
        re.compile(
            r"\b(?:i|we)(?: have|'ve)? (?:issued|processed) (?:a |the |your )?(?:full )?refund"
        ),
        re.compile(r"\brefund (?:has been|was|is now) (?:issued|processed|completed|approved)\b"),
    ),
    HOLD: (
        re.compile(r"\b(?:i|we)(?: have|'ve)? (?:placed|put) (?:a |the )?hold\b"),
        re.compile(r"\bhold (?:has been|was|is now) placed\b"),
        re.compile(r"\bseats? (?:has been|have been|are now|is now) held\b"),
    ),
    RELEASE: (
        re.compile(r"\bhold (?:has been|was|is now) released\b"),
        re.compile(r"\b(?:i|we)(?: have|'ve)? released (?:the |your )?(?:inventory )?hold\b"),
    ),
    NOTIFY: (
        re.compile(r"\b(?:i|we)(?: have|'ve)? notified\b"),
        re.compile(r"\b(?:passenger|customer|you) (?:has been|have been|was|were) notified\b"),
        re.compile(r"\bnotification (?:has been|was) sent\b"),
    ),
    APPROVAL: (
        re.compile(r"\bapproval (?:has been|was|is now) (?:granted|approved|obtained)\b"),
        re.compile(r"\b(?:has been|was) approved\b"),
    ),
}

# Negation / hedge cues that disqualify a clause from being an affirmative claim.
_NEGATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:not|no|never|unable|cannot|failed|fail|denied|declined|rejected|pending|awaiting|"
    r"attempt|attempted|if|would|will|should|could|may|might|once|requires?|need|needs)\b|n't\b"
)

# Words that mention an action category (user requests and injected instructions).
_MENTION_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    REBOOK: re.compile(r"\b(?:re-?book\w*|book(?:ing)? confirmed|confirm\w*|book)\b"),
    CANCEL: re.compile(r"\bcancel\w*\b"),
    REFUND: re.compile(r"\brefund\w*\b"),
    HOLD: re.compile(r"\bhold\b"),
    RELEASE: re.compile(r"\brelease\w*\b"),
    NOTIFY: re.compile(r"\b(?:notif\w*|e-?mail|sms)\b"),
    APPROVAL: re.compile(r"\bapprov\w*\b"),
}

_SENTENCE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?\n])\s+|\n+")
_CLAUSE_BOUNDARY_RE: Final[re.Pattern[str]] = re.compile(r"[,;:]|\bbut\b")


@dataclass(frozen=True)
class SuccessClaim:
    """An affirmative completed-action claim found in free text."""

    category: str
    sentence: str
    matched_text: str


def _clause_start(sentence: str, match_start: int) -> int:
    start = 0
    for boundary in _CLAUSE_BOUNDARY_RE.finditer(sentence, 0, match_start):
        start = boundary.end()
    return start


def detect_success_claims(text: str | None) -> list[SuccessClaim]:
    """Return completed-action claims in *text*, at most one per category per sentence."""
    if not text:
        return []
    claims: list[SuccessClaim] = []
    for raw_sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = raw_sentence.strip().lower()
        if not sentence:
            continue
        for category in CLAIM_CATEGORIES:
            for pattern in _CLAIM_PATTERNS[category]:
                match = pattern.search(sentence)
                if match is None:
                    continue
                clause = sentence[_clause_start(sentence, match.start()) : match.end()]
                if _NEGATION_RE.search(clause):
                    continue
                claims.append(
                    SuccessClaim(
                        category=category,
                        sentence=raw_sentence.strip(),
                        matched_text=match.group(0),
                    )
                )
                break
    return claims


def action_categories(text: str | None) -> frozenset[str]:
    """Return the action categories that *text* mentions (instructions, requests)."""
    if not text:
        return frozenset()
    lowered = text.lower()
    return frozenset(
        category for category, pattern in _MENTION_PATTERNS.items() if pattern.search(lowered)
    )


__all__ = [
    "APPROVAL",
    "CANCEL",
    "CLAIM_CATEGORIES",
    "HOLD",
    "NOTIFY",
    "REBOOK",
    "REFUND",
    "RELEASE",
    "SuccessClaim",
    "action_categories",
    "detect_success_claims",
]
