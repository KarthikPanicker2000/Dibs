"""Private value and fairness attestation (PLAN.md 7.1, 7.7). Runs inside each agent."""
from __future__ import annotations

from .models import Item, Outcome


def private_value(market: float, rating: int, max_price: float | None) -> float:
    if rating == 0:
        return 0.0                      # refuses the item
    if max_price is not None:
        return max_price                # explicit private max wins
    return market * (0.5 + rating / 10) # 5 -> 1.0x market, 7 -> 1.2x, 10 -> 1.5x


def attest(me: str, outcomes: list[Outcome], cash: dict[str, float],
           items: dict[str, Item], my_values: dict[str, float]) -> dict:
    """'I got at least my ownership share of everything, by my own valuation.'"""
    u = sum(my_values.get(o.item_id, 0.0) for o in outcomes if o.winner == me) + cash.get(me, 0.0)
    prop = sum(items[o.item_id].shares.get(me, 0) * my_values.get(o.item_id, 0.0) for o in outcomes)
    return {"proportional_ok": u >= prop - 0.01}
