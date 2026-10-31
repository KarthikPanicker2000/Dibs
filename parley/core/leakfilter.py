"""Code-level leak filter (PLAN.md 7.8, Ritvik's design). Runs on every outgoing agent message."""
from __future__ import annotations

import re

BANNED = ["my max", "my limit", "most i'd pay", "most i would pay", "up to",
          "willing to pay", "my budget", "my rating", "rated it", "walk away", "drop price"]
NUM = re.compile(r"\$?\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", re.I)
CANNED = "Let's keep this moving."


def leaks(text: str, secrets: list[float], public: list[float]) -> bool:
    t = text.lower()
    if any(b in t for b in BANNED):
        return True
    for m in NUM.finditer(t):
        n = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        if n < 20:
            continue                       # ignore small numbers and ratings
        for s in secrets:                  # private values, max prices, drop prices
            if any(abs(s - pv) <= 0.03 * pv for pv in public):
                continue                   # secret equals a public market value -> not a leak
            if abs(n - s) <= 0.03 * s:
                return True
    return False


def filtered_message(drafts, secrets: list[float], public: list[float], retries: int = 2) -> tuple[str, int]:
    """drafts: callable(attempt) -> text. Regenerate up to `retries` times, then send the canned line.

    Returns (text_to_send, number_of_blocked_drafts).
    """
    blocked = 0
    for attempt in range(retries + 1):
        text = drafts(attempt)
        if not leaks(text, secrets, public):
            return text, blocked
        blocked += 1
    return CANNED, blocked
