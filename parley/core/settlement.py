"""Buyout settlement and minimal transfers (PLAN.md 7.6)."""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from .models import Item, Outcome


class Transfer(BaseModel):
    payer: str
    payee: str
    amount: float


def settle(outcomes: list[Outcome], items: dict[str, Item],
           contestants: dict[str, list[str]] | None = None,
           sold: dict[str, float] | None = None) -> dict[str, float]:
    """Net cash per person: + receives, - pays. The winner buys out the other owners' shares."""
    contestants = contestants or {}
    sold = sold or {}
    cash: dict[str, float] = defaultdict(float)
    for o in outcomes:
        if o.winner is None:
            continue
        it = items[o.item_id]
        for owner, share in it.shares.items():
            if owner == o.winner:
                continue
            # owners who weren't bidding are protected: paid at least market value
            p = o.price if owner in contestants.get(it.id, []) else max(o.price, it.market_value or 0.0)
            cash[o.winner] -= share * p
            cash[owner] += share * p
    for item_id, proceeds in sold.items():    # unwanted pile sold externally
        for owner, share in items[item_id].shares.items():
            cash[owner] += share * proceeds
    return dict(cash)


def minimal_transfers(cash: dict[str, float]) -> list[Transfer]:
    """Greedy: biggest debtor pays biggest creditor, repeat. Balances must sum to ~0."""
    bal = {p: round(v, 2) for p, v in cash.items() if abs(v) >= 0.005}
    out: list[Transfer] = []
    while True:
        debtors = sorted((p for p in bal if bal[p] < -0.005), key=lambda p: bal[p])
        creditors = sorted((p for p in bal if bal[p] > 0.005), key=lambda p: -bal[p])
        if not debtors or not creditors:
            return out
        d, c = debtors[0], creditors[0]
        amt = round(min(-bal[d], bal[c]), 2)
        out.append(Transfer(payer=d, payee=c, amount=amt))
        bal[d] = round(bal[d] + amt, 2)
        bal[c] = round(bal[c] - amt, 2)
