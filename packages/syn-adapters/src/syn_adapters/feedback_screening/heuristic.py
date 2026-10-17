"""HeuristicScreener: a model-free ScreeningPort (ADR-076-feedback-ticketing).

Pattern rules only, so it is deterministic, free and offline. It is the floor
of the classifier bench and the default where no model is configured. Its
confidences are fixed per rule, not calibrated: ``ScreeningPolicy`` decides
what they mean.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from syn_domain.contexts.feedback import Priority, ScreeningResult, ScreeningVerdict, TicketType

if TYPE_CHECKING:
    from syn_domain.contexts.feedback import ScreenedText

# Text addressed to the classifier or an agent rather than to the owner.
_INJECTION = re.compile(
    r"ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+"
    r"(?:instructions?|prompts?|messages?|rules?)"
    r"|disregard\s+(?:all\s+|the\s+|your\s+)?(?:previous|prior|above|system)"
    r"|forget\s+(?:all\s+|everything\s+|your\s+)?(?:previous|prior|above|instructions?)"
    r"|\bsystem\s+prompt\b"
    r"|\byou\s+are\s+now\b"
    r"|\b(?:classify|mark|label|rate)\s+(?:this|me|it)\s+(?:as\s+)?(?:clean|safe|p0|benign)\b"
    r"|\b(?:call|invoke|run|use)\s+the\s+[\w.-]+\s+tool\b"
    r"|\bdeveloper\s+mode\b"
    r"|</?(?:system|instructions?|assistant|tool_use|admin)>",
    re.IGNORECASE,
)
_SPAM_TERMS = re.compile(
    r"\b(?:casino|crypto|bitcoin|airdrop|forex|viagra|cialis|backlinks?|seo\s+services?"
    r"|guaranteed\s+(?:returns?|profits?|ranking)|buy\s+followers|giveaway|loan\s+approval"
    r"|work\s+from\s+home|earn\s+\$?\d+|100x|presale|wallet\s+connect)\b",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z]+")
_VOWEL = re.compile(r"[aeiouAEIOU]")

_TYPE_RULES: tuple[tuple[re.Pattern[str], TicketType], ...] = (
    (re.compile(r"\b(?:slow|lag|latency|timeout|memory|cpu)\b", re.I), TicketType.PERFORMANCE),
    (
        re.compile(
            r"\b(?:crash(?:es|ed)?|errors?|broken|fail(?:s|ed)?|bugs?|exception|500)\b", re.I
        ),
        TicketType.BUG,
    ),
    (re.compile(r"\b(?:button|layout|colour|color|ui|dark mode|font)\b", re.I), TicketType.UI_UX),
    (
        re.compile(r"\b(?:please add|would be nice|feature|support for|wish)\b", re.I),
        TicketType.FEATURE,
    ),
)
_URGENT = re.compile(r"\b(?:data loss|lost (?:my )?data|security|cannot log ?in|outage)\b", re.I)

_INJECTION_CONFIDENCE = 0.95
_SPAM_CONFIDENCE = 0.9
_CLEAN_CONFIDENCE = 0.7
_SPAM_TERM_THRESHOLD = 2
_URL_THRESHOLD = 3
_GIBBERISH_MIN_WORDS = 6
_GIBBERISH_VOWEL_RATIO = 0.2


class HeuristicScreener:
    """Injection beats spam beats clean: doubt about intent outranks doubt about value."""

    async def screen(self, text: ScreenedText) -> ScreeningResult:
        return classify(text.text)


def classify(text: str) -> ScreeningResult:
    """The rule set, synchronous so the bench and the port share one body."""
    if _INJECTION.search(text):
        return _result(
            ScreeningVerdict.QUARANTINE, TicketType.OTHER, Priority.P3, _INJECTION_CONFIDENCE
        )
    if _is_spam(text):
        return _result(ScreeningVerdict.SPAM, TicketType.OTHER, Priority.P3, _SPAM_CONFIDENCE)
    ticket_type = next((kind for pattern, kind in _TYPE_RULES if pattern.search(text)), None)
    if ticket_type is None:
        ticket_type = TicketType.QUESTION if text.rstrip().endswith("?") else TicketType.OTHER
    priority = Priority.P1 if _URGENT.search(text) else Priority.P2
    return _result(ScreeningVerdict.CLEAN, ticket_type, priority, _CLEAN_CONFIDENCE)


def _is_spam(text: str) -> bool:
    if len(_SPAM_TERMS.findall(text)) >= _SPAM_TERM_THRESHOLD:
        return True
    if len(_URL.findall(text)) >= _URL_THRESHOLD:
        return True
    words = _WORD.findall(text)
    if len(words) < _GIBBERISH_MIN_WORDS:
        return False
    letters = "".join(words)
    return len(_VOWEL.findall(letters)) / len(letters) < _GIBBERISH_VOWEL_RATIO


def _result(
    verdict: ScreeningVerdict, ticket_type: TicketType, priority: Priority, confidence: float
) -> ScreeningResult:
    return ScreeningResult(
        verdict=verdict, type=ticket_type, priority=priority, confidence=confidence
    )
