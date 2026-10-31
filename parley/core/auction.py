"""Budget-capped clock auction (PLAN.md 7.5).

Agents decide privately; this module only asks each active bidder "still in at
this price?" and applies the tiebreak rules.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Callable


def start_price(market: float) -> float:
    return 0.2 * market


def tick_step(market: float) -> float:
    return max(5.0, 0.05 * market)


@dataclass
class AuctionResult:
    item_id: str
    winner: str
    price: float
    ticks: int
    drops: list[tuple[str, float]] = field(default_factory=list)   # (pid, price they dropped at)
    tiebreak: str | None = None                                     # rule that broke the tie, shown on screen
    tied: list[str] = field(default_factory=list)


def coin_flip(seed: str, tied: list[str]) -> str:
    """Seeded so the same scenario always gives the same flip."""
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16))
    return rng.choice(sorted(tied))


def break_tie(tied: list[str], won_so_far: dict[str, int], seed: str) -> tuple[str, str]:
    """Fewer contested items won so far, then a seeded coin flip."""
    fewest = min(won_so_far.get(p, 0) for p in tied)
    still = [p for p in tied if won_so_far.get(p, 0) == fewest]
    if len(still) == 1:
        return still[0], "fewer contested items won so far"
    return coin_flip(seed, still), "coin flip (seed " + seed + ")"


def run_clock_auction(
    item_id: str,
    market: float,
    stay: dict[str, Callable[[float], bool]],
    won_so_far: dict[str, int] | None = None,
    seed: str = "parley",
    on_tick: Callable[[float, list[str]], None] | None = None,
    on_drop: Callable[[str, float], None] | None = None,
    max_ticks: int = 2000,
) -> AuctionResult:
    """stay[pid](price) -> True while that bidder is still in.

    The last bidder remaining wins at the current price. If everyone still in
    drops on the same tick, they tie at the last price they all accepted.
    """
    won_so_far = won_so_far or {}
    active = list(stay)
    price = start_price(market)
    step = tick_step(market)
    last_price: float | None = None
    drops: list[tuple[str, float]] = []
    for tick in range(max_ticks):
        if on_tick:
            on_tick(price, list(active))
        staying = [p for p in active if stay[p](price)]
        dropped = [p for p in active if p not in staying]
        if len(staying) == 0:
            # everyone left dropped together -> tie among them
            winner, why = break_tie(active, won_so_far, f"{seed}:{item_id}")
            win_price = last_price if last_price is not None else price
            for p in active:
                if p != winner:
                    drops.append((p, price))
                    if on_drop:
                        on_drop(p, price)
            return AuctionResult(item_id, winner, round(win_price, 2), tick + 1, drops, why, sorted(active))
        for p in dropped:
            drops.append((p, price))
            if on_drop:
                on_drop(p, price)
        if len(staying) == 1 and (dropped or len(active) == 1):
            return AuctionResult(item_id, staying[0], round(price, 2), tick + 1, drops)
        active = staying
        last_price = price
        price = round(price + step, 2)
    winner, why = break_tie(active, won_so_far, f"{seed}:{item_id}")
    return AuctionResult(item_id, winner, round(last_price or price, 2), max_ticks, drops, f"clock limit: {why}", sorted(active))
