"""Shared data model (PLAN.md section 6).

Fields marked "extra" are optional additions for the demo screens; everything
else matches the plan exactly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class Participant(BaseModel):
    id: str              # "alex"
    name: str
    agent_url: str | None = None   # None => LocalAgent


class Item(BaseModel):
    id: str              # "couch"
    name: str
    category: str        # furniture | kitchen | electronics | decor | other
    description: str = ""
    purchase_price: float | None = None
    age_years: float | None = None
    market_value: float | None = None   # filled by Appraiser or human
    value_source: str = ""              # "Gemma estimate", "manual", "depreciation formula"
    confidence: str = "low"             # low | medium | high
    shares: dict[str, float]            # owner id -> share, sums to 1.0
    locked_to: str | None = None        # e.g. specific bequest in a will
    emoji: str = ""                     # extra: big-screen card icon
    image: str = ""                     # extra: uploaded photo, served at /images/<file>


class Scenario(BaseModel):
    id: str
    title: str           # "Estate of Margaret Lee"
    participants: list[Participant]
    items: list[Item]
    contest_threshold: int = 7    # rating needed to contest an item
    topup_pct: float = 0.5        # extra spend allowed beyond credits, as fraction of credits
    max_top_ratings: int = 3      # max items rated 9–10 per person
    # extras (public, shown on the setup screen / used in prompts)
    kind: str = ""                # "an inheritance among siblings"
    will: str = ""                # will text, shown on screen
    notes: list[str] = []         # one-liners for the setup screen
    sale_estimates: dict[str, float] = {}   # unwanted item -> expected sale proceeds; missing => donate
    open_seats: bool = False      # people create their own seat by scanning the QR; everyone owns an equal share


# ---- private, lives only inside an agent ----
class PrivatePrefs(BaseModel):
    ratings: dict[str, int]                 # item id -> 0..10
    max_prices: dict[str, float] = {}       # optional
    reasons: dict[str, str] = {}


# ---- public ----
Interest = Literal["NONE", "WANT", "STRONG"]


class Outcome(BaseModel):
    item_id: str
    winner: str | None        # None => unwanted pile
    price: float              # clearing price (market value for easy items)
    method: Literal["easy", "negotiated", "auction", "locked", "unwanted"]


class Event(BaseModel):       # drives the live feed
    t: float
    kind: str                 # phase | message | filtered | bid | drop | win | verdict
    actor: str | None
    text: str


def scenario_path(scenario_id: str) -> Path:
    return SCENARIO_DIR / f"{scenario_id}.json"


def load_scenario(scenario_id: str) -> Scenario:
    """Public part of a scenario. `demo_prefs` in the JSON is ignored here on purpose."""
    return Scenario.model_validate(json.loads(scenario_path(scenario_id).read_text()))


def load_demo_prefs(scenario_id: str, participant_id: str) -> PrivatePrefs | None:
    """Demo ratings for one participant (read by that participant's agent only)."""
    raw = json.loads(scenario_path(scenario_id).read_text()).get("demo_prefs", {})
    return PrivatePrefs.model_validate(raw[participant_id]) if participant_id in raw else None
