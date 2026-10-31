"""Classify items and compute auction credits (PLAN.md 7.2-7.4). Public info only."""
from __future__ import annotations

from .models import Item, Outcome, Scenario


def interest_bucket(rating: int, contest_threshold: int = 7) -> str:
    """7.2: 0-4 -> NONE, 5-6 -> WANT, >= contest_threshold -> STRONG."""
    if rating >= contest_threshold:
        return "STRONG"
    if rating >= 5:
        return "WANT"
    return "NONE"


def classify(item: Item, interest: dict[str, str]) -> tuple[str, list[str]]:
    """7.3. interest: {pid: "NONE"|"WANT"|"STRONG"}."""
    if item.locked_to:
        return ("locked", [item.locked_to])
    strong = [p for p, b in interest.items() if b == "STRONG"]
    want = [p for p, b in interest.items() if b == "WANT"]
    if len(strong) >= 2:
        return ("contested", strong)
    if len(strong) == 1:
        return ("easy", strong)
    if len(want) == 1:
        return ("easy", want)
    if len(want) >= 2:
        return ("contested", want)      # tie among WANTs
    return ("unwanted", [])


def classify_all(scenario: Scenario, interest: dict[str, dict[str, str]]):
    """interest: {pid: {item_id: bucket}} as published by each agent.

    Returns (classes, contestants, outcomes) where classes is {item_id: kind},
    contestants is {item_id: [pid]} for contested items, and outcomes holds the
    locked / easy / unwanted results.
    """
    classes: dict[str, str] = {}
    contestants: dict[str, list[str]] = {}
    outcomes: list[Outcome] = []
    for it in scenario.items:
        per_item = {p.id: interest.get(p.id, {}).get(it.id, "NONE") for p in scenario.participants}
        kind, people = classify(it, per_item)
        classes[it.id] = kind
        if kind == "contested":
            contestants[it.id] = people
        elif kind in ("locked", "easy"):
            outcomes.append(Outcome(item_id=it.id, winner=people[0], price=it.market_value or 0.0, method=kind))
        else:
            outcomes.append(Outcome(item_id=it.id, winner=None, price=0.0, method="unwanted"))
    return classes, contestants, outcomes


def compute_credits(items: dict[str, Item], contestants: dict[str, list[str]]) -> dict[str, float]:
    """7.4: each contested item's market value split evenly among its contestants."""
    credits: dict[str, float] = {}
    for item_id, people in contestants.items():
        for p in people:
            credits[p] = credits.get(p, 0.0) + (items[item_id].market_value or 0.0) / len(people)
    return credits


def spend_caps(credits: dict[str, float], topup_pct: float) -> dict[str, float]:
    return {p: c * (1 + topup_pct) for p, c in credits.items()}


def auction_order(items: dict[str, Item], contestants: dict[str, list[str]]) -> list[str]:
    """7.5: one item at a time, highest market value first."""
    return sorted(contestants, key=lambda i: -(items[i].market_value or 0.0))
