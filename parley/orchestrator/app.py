"""Orchestrator (PLAN.md sections 5, 10). Knows only public info.

State machine: SETUP -> APPRAISE -> INTAKE -> EASY_ALLOC -> NEGOTIATE -> AUCTION -> JUDGE -> REVEAL

Run: uvicorn orchestrator.app:app --port 8000
Env: AGENT_URLS=http://localhost:8001,http://localhost:8002,... (participant i -> URL i;
     unset => in-process LocalAgents), SCENARIO=inheritance, TICK_DELAY=0.25, PHASE_PAUSE=1.2
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from agent import llm
from core.allocation import auction_order, classify_all, compute_credits, spend_caps
from core.auction import run_clock_auction, start_price
from core.models import SCENARIO_DIR, Event, Outcome, Scenario, load_scenario

from . import juror
from .agents import Agent, LocalAgent, RemoteAgent
from .appraiser import appraise

PHASES = ["SETUP", "APPRAISE", "INTAKE", "EASY_ALLOC", "NEGOTIATE", "AUCTION", "JUDGE", "REVEAL"]
UI = Path(__file__).resolve().parent.parent / "ui" / "index.html"


def money(x: float) -> str:
    return juror.money(x)


def pmap(fn, xs: list) -> list:
    """Call independent agents (or Gemma) in parallel; results keep the input order."""
    xs = list(xs)
    if len(xs) <= 1:
        return [fn(x) for x in xs]
    with ThreadPoolExecutor(max_workers=len(xs)) as ex:
        return list(ex.map(fn, xs))


class Engine:
    def __init__(self, agent_urls: list[str] | None = None, tick_delay: float | None = None,
                 phase_pause: float | None = None):
        if agent_urls is None:
            agent_urls = [u.strip() for u in os.environ.get("AGENT_URLS", "").split(",") if u.strip()]
        self.agent_urls = agent_urls
        self.tick_delay = float(os.environ.get("TICK_DELAY", "0.25")) if tick_delay is None else tick_delay
        self.phase_pause = float(os.environ.get("PHASE_PAUSE", "1.2")) if phase_pause is None else phase_pause
        self.lock = threading.RLock()
        self.busy = False
        self.scenario: Scenario | None = None
        self.agents: dict[str, Agent] = {}
        self._local_cache: dict[str, LocalAgent] = {}
        self._reset_state()

    # ---- state -------------------------------------------------------------
    def _reset_state(self):
        self.phase = "SETUP"
        self.events: list[Event] = []
        self.t0 = time.time()
        self.interest: dict[str, dict[str, str]] = {}
        self.classes: dict[str, str] = {}
        self.contestants: dict[str, list[str]] = {}
        self.outcomes: list[Outcome] = []
        self.credits: dict[str, float] = {}
        self.caps: dict[str, float] = {}
        self.remaining: dict[str, float] = {}
        self.auction: dict | None = None
        self.auction_results: list[dict] = []
        self.negotiation: dict | None = None
        self.deal: list[Outcome] | None = None       # negotiated outcomes for contested items, if all accepted
        self.verdict: dict | None = None
        self.reveal: dict | None = None
        self.intake: dict[str, bool] = {}
        self._intake_checked = 0.0
        self.error: str | None = None
        self.appraisal_notes: dict[str, str] = {}

    def emit(self, kind: str, text: str, actor: str | None = None):
        with self.lock:
            self.events.append(Event(t=round(time.time() - self.t0, 2), kind=kind, actor=actor, text=text))

    def name(self, pid: str | None) -> str:
        if pid is None:
            return "Unwanted pile"
        for p in self.scenario.participants:
            if p.id == pid:
                return p.name
        return pid

    @property
    def items(self):
        return {i.id: i for i in self.scenario.items}

    # ---- setup -------------------------------------------------------------
    def load(self, scenario_id: str):
        if self.busy:
            raise RuntimeError("busy")
        sc = load_scenario(scenario_id)
        with self.lock:
            self.scenario = sc
            self._reset_state()
            self.agents = {}
            for i, p in enumerate(sc.participants):
                url = self.agent_urls[i] if i < len(self.agent_urls) else p.agent_url
                if url:
                    self.agents[p.id] = RemoteAgent(p.id, url)
                else:
                    self.agents[p.id] = self._local_cache.setdefault(f"{sc.id}:{p.id}", LocalAgent(p.id))
        for a in self.agents.values():
            a.setup(sc, reset=True)
        self.intake = {pid: False for pid in self.agents}
        self.emit("phase", f"Loaded scenario: {sc.title}")
        for n in sc.notes:
            self.emit("message", n)

    def push_catalog(self):
        for a in self.agents.values():
            a.setup(self.scenario)

    def refresh_intake(self, force: bool = False):
        if not self.scenario or (not force and time.time() - self._intake_checked < 1.0):
            return
        self._intake_checked = time.time()
        for pid, a in self.agents.items():
            try:
                self.intake[pid] = bool(a.status().get("has_prefs"))
            except Exception:
                self.intake[pid] = False

    # ---- phase runner --------------------------------------------------------
    def next_phase(self) -> str | None:
        i = PHASES.index(self.phase)
        return PHASES[i + 1] if i + 1 < len(PHASES) else None

    def step(self):
        """Run the next phase (blocking)."""
        nxt = self.next_phase()
        if nxt is None:
            return
        with self.lock:
            self.phase = nxt
        self.emit("phase", nxt.replace("_", " ").title())
        getattr(self, f"_phase_{nxt.lower()}")()

    def start(self, run_all: bool):
        if not self.scenario:
            raise RuntimeError("load a scenario first")
        with self.lock:
            if self.busy:
                raise RuntimeError("busy")
            self.busy = True

        def work():
            try:
                self.step()
                while run_all and self.next_phase():
                    time.sleep(self.phase_pause)
                    self.step()
            except Exception as e:
                traceback.print_exc()
                self.error = f"{type(e).__name__}: {e}"
                self.emit("error", f"⚠️ {self.error}")
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True).start()

    # ---- phases --------------------------------------------------------------
    def _phase_appraise(self):
        new_items = []
        for it in self.scenario.items:
            if it.market_value is None:
                upd, why = appraise(it)
                self.emit("message", f"🔎 Appraiser: {upd.name} ≈ {money(upd.market_value)} "
                                     f"({upd.value_source}, {upd.confidence} confidence). {why}", "appraiser")
                self.appraisal_notes[it.id] = why
                new_items.append(upd)
            else:
                new_items.append(it)
        with self.lock:
            self.scenario = self.scenario.model_copy(update={"items": new_items})
        if not self.appraisal_notes:
            src = {i.value_source for i in new_items}
            self.emit("message", f"🔎 Appraiser: all values already set ({', '.join(sorted(src))}).", "appraiser")
        self.push_catalog()

    def _phase_intake(self):
        self.refresh_intake(force=True)
        self.emit("message", "📱 Private intake is open. Each person rates every item 0–10 on their own agent. "
                             "Those numbers never leave the agent.")

    def _phase_easy_alloc(self):
        self.refresh_intake(force=True)
        for pid, a in self.agents.items():
            if not self.intake.get(pid):
                a.demo_fill()
                self.intake[pid] = True
                self.emit("message", f"{self.name(pid)}'s agent had no intake yet, so it loaded the demo ratings.")
        for pid, a in self.agents.items():
            buckets = a.interest()
            with self.lock:
                self.interest[pid] = buckets
            n_strong = sum(b == "STRONG" for b in buckets.values())
            n_want = sum(b == "WANT" for b in buckets.values())
            self.emit("message", f"{self.name(pid)}'s agent published interest only: "
                                 f"{n_strong} STRONG, {n_want} WANT, rest NONE.")
        classes, contestants, outcomes = classify_all(self.scenario, self.interest)
        with self.lock:
            self.classes, self.contestants, self.outcomes = classes, contestants, outcomes
        items = self.items
        for o in outcomes:
            it = items[o.item_id]
            if o.method == "locked":
                self.emit("win", f"{it.emoji} {it.name} → {self.name(o.winner)} (specific bequest in the will).", o.winner)
            elif o.method == "easy":
                others = [p for p in it.shares if p != o.winner]
                buy = (f" Buys out {', '.join(self.name(p) for p in others)} at the {money(it.market_value)} market value."
                       if others else " Already theirs, no cash.")
                self.emit("win", f"{it.emoji} {it.name} → {self.name(o.winner)} (no conflict).{buy}", o.winner)
            else:
                sale = self.scenario.sale_estimates.get(o.item_id)
                fate = f"sell for about {money(sale)}, split by ownership" if sale else "donate"
                self.emit("message", f"{it.emoji} {it.name} → unwanted pile ({fate}).")
        for item_id, people in contestants.items():
            it = items[item_id]
            self.emit("bid", f"⚔️ {it.emoji} {it.name} is contested: {' vs '.join(self.name(p) for p in people)}.")

    def _settle_contestants(self) -> dict[str, list[str]]:
        contestants = dict(self.contestants)
        for o in self.outcomes:
            if o.method in ("easy", "locked"):
                contestants.setdefault(o.item_id, [o.winner])
        return contestants

    def _filtered(self, pid: str, res: dict):
        for _ in range(int(res.get("filtered", 0))):
            self.emit("filtered", f"🛡️ message filtered: {self.name(pid)}'s agent drafted a line that "
                                  "revealed a private number. Blocked in code and rewritten.", pid)

    def _valid_proposal(self, proposal: dict) -> bool:
        """Section 8: contested items only (all of them), winners must be contestants, prices > 0."""
        try:
            return (set(proposal) == set(self.contestants)
                    and all(d["winner"] in self.contestants[i] and float(d["price"]) > 0 for i, d in proposal.items()))
        except (KeyError, TypeError, ValueError, AttributeError):
            return False

    def _phase_negotiate(self):
        if not self.contestants:
            self.emit("message", "No conflicts, nothing to negotiate.")
            return
        if os.environ.get("NEGOTIATE", "1") == "0":
            self.emit("message", "Negotiation skipped. Deadlocked items go straight to the bidding war.")
            return
        items = self.items
        base = list(self.outcomes)
        order = [p.id for p in self.scenario.participants if any(p.id in ps for ps in self.contestants.values())]
        transcript: list[dict] = []
        self.emit("message", f"🤝 Agents negotiate the {len(self.contestants)} contested items, up to 4 rounds. "
                             "Messages stay sealed until the reveal.")
        rnd = 0
        for rnd in range(1, 5):
            proposer = order[(rnd - 1) % len(order)]
            res = self.agents[proposer].negotiate({"type": "propose", "round": rnd, "contested": self.contestants})
            self._filtered(proposer, res)
            transcript.append(res)
            proposal = res.get("proposal") or {}
            if not self._valid_proposal(proposal):
                self.emit("message", f"Round {rnd}: {self.name(proposer)}'s proposal was invalid and bounced back.")
                continue
            self.emit("bid", f"🤝 Round {rnd}: {self.name(proposer)}'s agent proposed a deal covering "
                             f"{len(proposal)} items.", proposer)
            outs = base + [Outcome(item_id=i, winner=d["winner"], price=float(d["price"]), method="negotiated")
                           for i, d in proposal.items()]
            cash, _, _ = juror.settlement(outs, self._settle_contestants(), self.scenario)
            accepted = True
            body = {"type": "respond", "round": rnd, "from": proposer, "proposal": proposal,
                    "outcomes": [o.model_dump() for o in outs], "cash": cash}
            replies = pmap(lambda pid: self.agents[pid].negotiate(body), list(self.agents))
            for pid, r in zip(self.agents, replies):
                self._filtered(pid, r)
                transcript.append(r)
                accepted &= r.get("type") == "accept"
                if pid != proposer:
                    self.emit("message" if r.get("type") == "accept" else "drop",
                              f"{self.name(pid)}'s agent {'accepted ✓' if r.get('type') == 'accept' else 'rejected ✗'}.")
            time.sleep(self.phase_pause / 2)
            if accepted:
                with self.lock:
                    self.deal = [o for o in outs if o.method == "negotiated"]
                self.emit("win", f"🤝 Deal reached in round {rnd}: every agent accepted.")
                break
        else:
            self.emit("message", "No deal after 4 rounds. The deadlocked items go to the bidding war.")
        with self.lock:
            self.negotiation = {"rounds": rnd, "deal": bool(self.deal), "transcript": transcript}

    def _phase_auction(self):
        items = self.items
        if not self.contestants:
            self.emit("message", "No conflicts, so no bidding war is needed.")
            return
        if self.deal:
            self.emit("message", "Everyone agreed to the negotiated deal, so no bidding war is needed.")
            return
        credits = compute_credits(items, self.contestants)
        caps = spend_caps(credits, self.scenario.topup_pct)
        with self.lock:
            self.credits, self.caps, self.remaining = credits, caps, dict(caps)
        self.emit("message", "💳 Bidding credits (contested value ÷ contestants): "
                  + " · ".join(f"{p.name} {money(credits[p.id])}" for p in self.scenario.participants if p.id in credits)
                  + f". Spend cap = credits + {self.scenario.topup_pct:.0%}.")
        order = auction_order(items, self.contestants)
        won: dict[str, int] = {}
        for k, item_id in enumerate(order):
            it = items[item_id]
            people = self.contestants[item_id]
            later = [{"item_id": j, "market": items[j].market_value, "contestants": self.contestants[j]}
                     for j in order[k + 1:]]
            with self.lock:
                self.auction = {"item_id": item_id, "market": it.market_value, "price": start_price(it.market_value),
                                "contestants": people, "active": list(people), "dropped": {}, "winner": None,
                                "status": "starting", "tiebreak": None}
            self.emit("bid", f"🔨 Bidding opens on {it.emoji} {it.name} (market {money(it.market_value)}): "
                             f"{' vs '.join(self.name(p) for p in people)}.")
            starts = pmap(lambda p: self.agents[p].auction_start({
                "item_id": item_id, "market": it.market_value, "cap": round(self.remaining.get(p, 0.0), 2),
                "credits": round(credits.get(p, 0.0), 2), "rivals": [self.name(q) for q in people if q != p],
                "remaining": later}), people)
            for p, res in zip(people, starts):
                self._filtered(p, res)
                if res.get("comment"):
                    self.emit("message", res["comment"], p)
            with self.lock:
                self.auction["status"] = "running"

            def on_tick(price, active):
                with self.lock:
                    self.auction["price"] = price
                    self.auction["active"] = list(active)
                time.sleep(self.tick_delay)

            def on_drop(pid, price, item=it):
                with self.lock:
                    self.auction["dropped"][pid] = price
                self.emit("drop", f"{self.name(pid)}'s agent drops out at {money(price)}.", pid)

            result = run_clock_auction(
                item_id, it.market_value,
                {p: (lambda price, p=p, iid=item_id: self.agents[p].auction_tick(iid, price)) for p in people},
                won_so_far=won, seed=self.scenario.id, on_tick=on_tick, on_drop=on_drop)
            if result.tiebreak:
                self.emit("message", f"🪙 Tie at {money(result.price)} between "
                                     f"{' and '.join(self.name(p) for p in result.tied)}. "
                                     f"Tiebreak: {result.tiebreak} → {self.name(result.winner)}.")
            won[result.winner] = won.get(result.winner, 0) + 1
            with self.lock:
                self.remaining[result.winner] = self.remaining.get(result.winner, 0.0) - result.price
                self.outcomes.append(Outcome(item_id=item_id, winner=result.winner, price=result.price, method="auction"))
                self.auction.update({"price": result.price, "winner": result.winner, "status": "done",
                                     "active": [result.winner], "tiebreak": result.tiebreak})
                self.auction_results.append({"item_id": item_id, "winner": result.winner, "price": result.price,
                                             "contestants": people, "tiebreak": result.tiebreak})
            self.emit("win", f"🏆 {self.name(result.winner)} wins the {it.emoji} {it.name} at {money(result.price)}.",
                      result.winner)
            time.sleep(self.phase_pause)

    def _phase_judge(self):
        contestants = self._settle_contestants()
        order = [i.id for i in self.scenario.items]
        candidates = []
        if self.deal:
            base = [o for o in self.outcomes if o.method != "auction"]
            candidates.append({"name": "negotiated", "contestants": contestants,
                               "outcomes": sorted(base + self.deal, key=lambda o: order.index(o.item_id))})
        if self.auction_results or not self.deal:
            candidates.append({"name": "auction", "contestants": contestants,
                               "outcomes": sorted(self.outcomes, key=lambda o: order.index(o.item_id))})
        self.emit("message", "⚖️ Juror asks every agent to check the result privately against its own values.", "juror")
        evaluated = [juror.evaluate(c, self.agents, self.scenario) for c in candidates]
        chosen, summary = juror.pick(evaluated)
        for pid, ok in chosen["attestations"].items():
            self.emit("verdict", f"{self.name(pid)}'s agent: {'✅ fair share' if ok else '⚠️ below fair share'}", pid)
        explained = pmap(lambda pid: juror.explain(pid, chosen, self.scenario), list(self.agents))
        explanations = {pid: text for pid, (text, _) in zip(self.agents, explained)}
        sources = {src for _, src in explained}
        transfers = [{"payer": t.payer, "payee": t.payee, "amount": t.amount,
                      "text": f"{self.name(t.payer)} pays {self.name(t.payee)} {money(t.amount)}"}
                     for t in chosen["transfers"]]
        with self.lock:
            self.outcomes = list(chosen["outcomes"])
            self.verdict = {"chosen": chosen["name"], "summary": summary, "attestations": chosen["attestations"],
                            "transfers": transfers, "sold": chosen["sold"], "cash": chosen["cash"],
                            "explanations": explanations, "llm": sorted(sources),
                            "outcomes": [o.model_dump() for o in chosen["outcomes"]]}
        self.emit("verdict", "⚖️ Verdict: " + summary, "juror")
        for t in transfers:
            self.emit("verdict", f"💸 {t['text']}", "juror")

    def _phase_reveal(self):
        reveal = {}
        for pid, a in self.agents.items():
            a.unlock()
            reveal[pid] = a.reveal()
        with self.lock:
            self.reveal = reveal
        self.emit("phase", "🔓 Verdict is final. Agents released their secret inputs so anyone can check the math.")

    # ---- public view ---------------------------------------------------------
    def snapshot(self) -> dict:
        if self.scenario and self.phase in ("SETUP", "APPRAISE", "INTAKE") and not self.busy:
            self.refresh_intake()
        with self.lock:
            sc = self.scenario
            return {
                "run_id": self.t0, "phase": self.phase, "phases": PHASES, "busy": self.busy, "error": self.error,
                "llm": llm.MODE, "llm_label": llm.LABEL, "llm_error": llm.disabled_reason,
                "scenario": None if sc is None else {
                    "id": sc.id, "title": sc.title, "kind": sc.kind, "will": sc.will, "notes": sc.notes,
                    "topup_pct": sc.topup_pct, "sale_estimates": sc.sale_estimates,
                    "participants": [{"id": p.id, "name": p.name,
                                      "agent_url": getattr(self.agents.get(p.id), "url", None)} for p in sc.participants],
                },
                "items": [i.model_dump() for i in sc.items] if sc else [],
                "intake": self.intake, "interest": self.interest, "classes": self.classes,
                "contestants": self.contestants, "outcomes": [o.model_dump() for o in self.outcomes],
                "credits": self.credits, "caps": self.caps, "remaining": self.remaining,
                "auction": self.auction, "auction_results": self.auction_results,
                "verdict": self.verdict, "reveal": self.reveal,
                "negotiation": None if self.negotiation is None else {
                    "rounds": self.negotiation["rounds"], "deal": self.negotiation["deal"],
                    # full transcripts only after the reveal (section 8)
                    "transcript": self.negotiation["transcript"] if self.reveal else None},
                "events": [e.model_dump() for e in self.events[-200:]],
            }


engine = Engine()
app = FastAPI(title="Parley orchestrator")


@app.on_event("startup")
def _startup():
    sid = os.environ.get("SCENARIO", "inheritance")
    try:
        engine.load(sid)
    except Exception as e:  # agents may still be booting; the UI can load it again
        print(f"[orchestrator] could not load {sid} at startup: {e}")


@app.get("/", response_class=HTMLResponse)
def index():
    return UI.read_text()


@app.get("/scenarios")
def scenarios():
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


@app.post("/scenario/{scenario_id}")
def load(scenario_id: str):
    try:
        engine.load(scenario_id)
    except FileNotFoundError:
        raise HTTPException(404, "no such scenario")
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "phase": engine.phase}


@app.get("/catalog")
def catalog():
    if not engine.scenario:
        raise HTTPException(409, "no scenario")
    return [i.model_dump() for i in engine.scenario.items]


@app.post("/next")
def next_():
    try:
        engine.start(run_all=False)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.post("/run")
def run():
    try:
        engine.start(run_all=True)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.get("/state")
def state():
    return engine.snapshot()
