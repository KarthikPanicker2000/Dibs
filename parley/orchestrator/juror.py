"""Juror (PLAN.md 7.9): collect private pass/fail attestations, pick an outcome, explain it."""
from __future__ import annotations

import json

from agent import llm, prompts
from core.models import Outcome, Scenario
from core.settlement import minimal_transfers, settle


def money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def settlement(outs: list[Outcome], contestants: dict[str, list[str]], scenario: Scenario):
    """Returns (cash incl. unwanted-pile sales, transfers between people, sales)."""
    items = {i.id: i for i in scenario.items}
    sold = {o.item_id: scenario.sale_estimates[o.item_id] for o in outs
            if o.winner is None and o.item_id in scenario.sale_estimates}
    cash = settle(outs, items, contestants, sold)                # what each person ends with
    internal = settle(outs, items, contestants)                  # money moving between people
    return cash, minimal_transfers(internal), sold


def evaluate(candidate: dict, agents: dict, scenario: Scenario) -> dict:
    """candidate: {name, outcomes, contestants}. Adds cash, transfers, sales and attestations."""
    outs: list[Outcome] = candidate["outcomes"]
    cash, transfers, sold = settlement(outs, candidate["contestants"], scenario)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, len(agents))) as ex:
        oks = list(ex.map(lambda a: bool(a.attest(outs, cash)), agents.values()))
    attest = dict(zip(agents, oks))
    return {**candidate, "cash": {p: round(v, 2) for p, v in cash.items()}, "transfers": transfers,
            "sold": sold, "attestations": attest, "passes": sum(attest.values())}


def pick(evaluated: list[dict]) -> tuple[dict, str]:
    """Prefer a candidate where everyone passes, negotiated first (consensual); else most passes."""
    full = [c for c in evaluated if c["passes"] == len(c["attestations"])]
    if full:
        full.sort(key=lambda c: c["name"] != "negotiated")
        return full[0], f"Every agent privately confirmed the {full[0]['name']} result gives them at least their fair share."
    best = max(evaluated, key=lambda c: c["passes"])
    n, total = best["passes"], len(best["attestations"])
    return best, (f"No candidate passed every check. The {best['name']} result passes {n} of {total}; "
                  "the failing check is shown openly below (spending-cap edge case).")


def public_facts(c: dict, scenario: Scenario) -> tuple[str, str, str]:
    names = {p.id: p.name for p in scenario.participants}
    items = {i.id: i for i in scenario.items}
    outs = "; ".join(
        f"{items[o.item_id].name} -> {names.get(o.winner, 'unwanted pile')} ({o.method}"
        + (f", {money(o.price)}" if o.winner and o.method != "locked" else "") + ")"
        for o in c["outcomes"])
    trans = "; ".join(f"{names[t.payer]} pays {names[t.payee]} {money(t.amount)}" for t in c["transfers"]) or "no transfers"
    unwanted = "; ".join(f"{items[i].name} sold for about {money(v)}, split by ownership" for i, v in c["sold"].items())
    donated = [items[o.item_id].name for o in c["outcomes"] if o.winner is None and o.item_id not in c["sold"]]
    if donated:
        unwanted += ("; " if unwanted else "") + ", ".join(donated) + " donated"
    return outs, trans, unwanted or "none"


def explain(pid: str, c: dict, scenario: Scenario) -> tuple[str, str]:
    names = {p.id: p.name for p in scenario.participants}
    items = {i.id: i for i in scenario.items}
    name = names[pid]
    ok = c["attestations"][pid]
    outs, trans, unwanted = public_facts(c, scenario)
    got = [items[o.item_id].name for o in c["outcomes"] if o.winner == pid]
    pays = sum(t.amount for t in c["transfers"] if t.payer == pid)
    gets = sum(t.amount for t in c["transfers"] if t.payee == pid)
    money_line = (f"you pay {money(pays)} in total" if pays > gets else
                  f"you receive {money(gets)} in total" if gets > 0 else "no money changes hands for you")
    mock = (f"{name}, you take home {', '.join(got) if got else 'no items'}, and {money_line}. "
            + ("Your own agent checked privately that this gives you at least your fair share by your own values."
               if ok else "Your agent reported this falls short of your fair share by your own values, "
                          "most likely because a spending cap stopped it bidding to your true value."))
    prompt = prompts.JUROR_EXPLAIN.format(name=name, outcomes=outs, transfers=trans, unwanted=unwanted,
                                          pass_or_fail="PASS" if ok else "FAIL")
    ans, src = llm.ask_json_or(prompt, {"explanation": mock})
    return str(ans.get("explanation") or mock), src
