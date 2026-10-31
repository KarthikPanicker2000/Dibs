"""Appraiser helper agent (PLAN.md 4.2, 9). Gemma estimate, depreciation formula as fallback."""
from __future__ import annotations

from pathlib import Path

from agent import llm, prompts
from core.models import SCENARIO_DIR, Item

IMAGE_DIR = SCENARIO_DIR / "images"

DECAY = {"electronics": 0.7}     # everything else depreciates like furniture (0.8 / year)


def depreciation(item: Item) -> float:
    """purchase_price x 0.8^age (0.7^age for electronics), rounded to $10 like a resale listing."""
    if not item.purchase_price:
        return 0.0
    return float(round(item.purchase_price * DECAY.get(item.category, 0.8) ** (item.age_years or 0), -1))


def image_path(item: Item) -> Path | None:
    if item.image.startswith("/images/"):
        p = IMAGE_DIR / Path(item.image).name
        return p if p.exists() else None
    return None


def appraise(item: Item, force: bool = False) -> tuple[Item, str]:
    """Returns (item with market_value filled, one-line reasoning). Keeps existing values unless force."""
    if item.market_value is not None and not force:
        return item, f"{item.value_source or 'given'}"
    formula = depreciation(item)
    photo = image_path(item)
    prompt = prompts.APPRAISER.format(photo_note=" A photo of the item is attached: judge its condition from it." if photo else "",
                                      name=item.name, category=item.category, description=item.description or "n/a",
                                      purchase_price=item.purchase_price or "unknown", age_years=item.age_years or "unknown")
    ans, src = llm.ask_json_or(prompt, {"value": formula, "confidence": "low",
                                        "reasoning": "Purchase price depreciated per year of age."}, image=photo)
    try:
        value = round(float(ans["value"]), 2)
    except (KeyError, TypeError, ValueError):
        value, src = formula, "fallback"
    if src not in ("mock", "fallback") and value >= 0:
        label = "Gemma estimate" if src == "gemma" else "Claude Code estimate (dev)"
        label += " from photo" if photo else ""
        upd = {"market_value": value, "value_source": label,
               "confidence": str(ans.get("confidence", "low"))}
        reason = str(ans.get("reasoning", ""))
    else:
        upd = {"market_value": formula, "value_source": "depreciation formula", "confidence": "low"}
        reason = "Purchase price depreciated per year of age."
    return item.model_copy(update=upd), reason
