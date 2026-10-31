"""One participant's private agent. Everything in here stays inside the agent's VM.

Used directly by LocalAgent (same process) and wrapped by agent/service.py (HTTP).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path

from core.allocation import interest_bucket
from core.fairness import attest as attest_fn
from core.fairness import private_value
from core.leakfilter import filtered_message
from core.models import Item, Outcome, PrivatePrefs, Scenario, load_demo_prefs

from . import llm, prompts

DATA_DIR = Path(os.environ.get("AGENT_DATA_DIR", Path(__file__).resolve().parent.parent / ".agent_data"))


class AgentLogic:
    def __init__(self, participant_id: str | None = None, data_dir: Path | None = None):
        self.pid = participant_id
        self.data_dir = Path(data_dir or DATA_DIR)
        self.scenario: Scenario | None = None
        self.prefs: PrivatePrefs | None = None
        self.drops: dict[str, float] = {}
        self.blocked_drafts: list[str] = []     # leak-filtered drafts, shown only at reveal
        self.attest_detail: dict = {}
        self.unlocked = False
        self.owner_token: str | None = None     # set when a phone claims this seat
        self.locked = False                     # ratings lock once interest is published
        self.caps_seen: dict[str, float] = {}   # spend cap the orchestrator gave us per auctioned item
        self.orch_url: str | None = None
        self.lock = threading.RLock()
        self._restore()

    # ---- setup / intake -------------------------------------------------
    def setup(self, scenario: dict | Scenario, participant_id: str | None = None, reset: bool = False) -> dict:
        """Receive the public catalog. Same scenario + participant keeps prefs unless reset."""
        sc = Scenario.model_validate(scenario if isinstance(scenario, dict) else scenario.model_dump())
        pid = participant_id or self.pid
        with self.lock:
            same = self.scenario is not None and self.scenario.id == sc.id and self.pid == pid
            self.scenario, self.pid = sc, pid
            if reset or not same:
                self.prefs, self.drops, self.blocked_drafts, self.attest_detail = None, {}, [], {}
                self.unlocked, self.locked, self.caps_seen = False, False, {}
                if reset:
                    self.owner_token = None
                if reset:
                    self._saved_path().unlink(missing_ok=True)
                else:
                    self._load_saved()
            self._persist()
        return self.status()

    @property
    def name(self) -> str:
        if self.scenario:
            for p in self.scenario.participants:
                if p.id == self.pid:
                    return p.name
        return self.pid or "?"

    @property
    def items(self) -> dict[str, Item]:
        return {i.id: i for i in self.scenario.items} if self.scenario else {}

    def claim(self, token: str | None = None) -> dict:
        """The first phone to open this seat gets a token; other devices are refused."""
        with self.lock:
            if self.owner_token and token != self.owner_token:
                raise PermissionError("This seat is already taken on another device. Ask the admin to reset the room.")
            if not self.owner_token:
                self.owner_token = secrets.token_urlsafe(16)
                self._persist()
        return {"token": self.owner_token, "name": self.name}

    def check_owner(self, token: str | None) -> None:
        if self.owner_token and token != self.owner_token:
            raise PermissionError("Only the phone that claimed this seat can see or change it.")

    def me(self) -> dict:
        """Private view for the seat owner's own phone."""
        return {"participant": self.pid, "name": self.name, "prefs": self.prefs.model_dump() if self.prefs else None,
                "values": {k: round(v, 2) for k, v in self.values().items()},
                "drops": {k: round(v, 2) for k, v in self.drops.items()}, "caps": self.caps_seen,
                "fairness": self.attest_detail, "locked": self.locked}

    def override(self, item_id: str, action: str, amount: float | None = None) -> dict:
        """Human bidding: drop out now, or stay in up to an amount (clamped to the spend cap)."""
        with self.lock:
            if item_id not in self.drops:
                raise ValueError("Bidding on that item hasn't opened for you.")
            cap = self.caps_seen.get(item_id, 0.0)
            self.drops[item_id] = -1.0 if action == "drop" else max(0.0, min(float(amount or 0), cap))
            self._persist()
            return {"drop": round(self.drops[item_id], 2), "cap": cap}

    def set_prefs(self, prefs: dict | PrivatePrefs) -> dict:
        if self.locked:
            raise ValueError("Ratings are locked: interest was already published.")
        p = PrivatePrefs.model_validate(prefs if isinstance(prefs, dict) else prefs.model_dump())
        items = self.items
        ratings = {i: max(0, min(10, int(p.ratings.get(i, 0)))) for i in items}
        limit = self.scenario.max_top_ratings if self.scenario else 3
        top = [i for i, r in ratings.items() if r >= 9]
        if len(top) > limit:
            raise ValueError(f"At most {limit} items can be rated 9-10 (you have {len(top)}).")
        clean = PrivatePrefs(
            ratings=ratings,
            max_prices={i: float(v) for i, v in p.max_prices.items() if i in items and v not in (None, "") and float(v) > 0},
            reasons={i: r.strip() for i, r in p.reasons.items() if i in items and r and r.strip()},
        )
        with self.lock:
            self.prefs = clean
            self._save()
            self._persist()
        return {"ok": True}

    def demo_prefs(self) -> PrivatePrefs | None:
        return load_demo_prefs(self.scenario.id, self.pid) if self.scenario else None

    def demo_fill(self) -> dict:
        d = self.demo_prefs()
        if d is None:   # custom room, no demo ratings: an empty intake means "wants nothing"
            return {**self.set_prefs(PrivatePrefs(ratings={})), "demo": False}
        return {**self.set_prefs(d), "demo": True}

    def status(self) -> dict:
        return {"participant": self.pid, "name": self.name,
                "scenario": self.scenario.id if self.scenario else None,
                "has_prefs": self.prefs is not None, "unlocked": self.unlocked, "llm": llm.MODE,
                "claimed": self.owner_token is not None}

    def _saved_path(self) -> Path:
        sid = self.scenario.id if self.scenario else "none"
        return self.data_dir / f"{sid}-{self.pid}.json"

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._saved_path().write_text(self.prefs.model_dump_json(indent=1))

    # Maritime agent boxes may sleep; only the data disk is guaranteed to survive.
    def _state_path(self) -> Path:
        return self.data_dir / "agent_state.json"

    def _persist(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._state_path().write_text(json.dumps({
                "pid": self.pid, "scenario": self.scenario.model_dump() if self.scenario else None,
                "prefs": self.prefs.model_dump() if self.prefs else None, "drops": self.drops,
                "blocked_drafts": self.blocked_drafts, "attest_detail": self.attest_detail, "unlocked": self.unlocked,
                "owner_token": self.owner_token, "locked": self.locked, "caps_seen": self.caps_seen}))
        except OSError:
            pass

    def _restore(self) -> None:
        try:
            d = json.loads(self._state_path().read_text())
        except (OSError, ValueError):
            return
        if self.pid and d.get("pid") != self.pid:
            return
        self.pid = d.get("pid")
        self.scenario = Scenario.model_validate(d["scenario"]) if d.get("scenario") else None
        self.prefs = PrivatePrefs.model_validate(d["prefs"]) if d.get("prefs") else None
        self.drops = d.get("drops", {})
        self.blocked_drafts = d.get("blocked_drafts", [])
        self.attest_detail = d.get("attest_detail", {})
        self.unlocked = bool(d.get("unlocked"))
        self.owner_token = d.get("owner_token")
        self.locked = bool(d.get("locked"))
        self.caps_seen = d.get("caps_seen", {})

    def _load_saved(self) -> None:
        path = self._saved_path()
        if path.exists():
            try:
                self.prefs = PrivatePrefs.model_validate(json.loads(path.read_text()))
            except Exception:
                self.prefs = None

    # ---- private numbers -------------------------------------------------
    def rating(self, item_id: str) -> int:
        return self.prefs.ratings.get(item_id, 0) if self.prefs else 0

    def values(self) -> dict[str, float]:
        """7.1 private value per item."""
        return {i: private_value(it.market_value or 0.0, self.rating(i), self.prefs.max_prices.get(i) if self.prefs else None)
                for i, it in self.items.items()}

    def _secrets(self) -> list[float]:
        vals = [v for v in self.values().values() if v > 0]
        return vals + list(self.prefs.max_prices.values() if self.prefs else []) + list(self.drops.values())

    def _public_numbers(self, extra: list[float] = ()) -> list[float]:
        return [it.market_value for it in self.items.values() if it.market_value] + [x for x in extra if x]

    # ---- public outputs --------------------------------------------------
    def interest(self) -> dict[str, str]:
        """7.2: only the coarse bucket leaves the agent."""
        thr = self.scenario.contest_threshold if self.scenario else 7
        if not self.locked:
            self.locked = True
            self._persist()
        return {i: interest_bucket(self.rating(i), thr) for i in self.items}

    def auction_start(self, info: dict) -> dict:
        """info: item_id, market, cap, rivals [names], remaining [{item_id, market, contestants}].

        Picks a private drop price (LLM suggests, code clamps) and returns only a public comment.
        """
        item_id = info["item_id"]
        item = self.items[item_id]
        market = float(info.get("market") or item.market_value or 0.0)
        cap = float(info.get("cap", 0.0))
        values = self.values()
        v = values[item_id]
        upcoming = [r for r in info.get("remaining", []) if self.pid in r.get("contestants", []) and r["item_id"] != item_id]
        # mock strategy: split the remaining cap across the items I'm still contesting, by private value
        saved_for_later = sum(values.get(r["item_id"], 0.0) for r in upcoming)
        mock_drop = cap * v / (v + saved_for_later) if v > 0 else 0.0
        reason = (self.prefs.reasons.get(item_id) if self.prefs else None) or ""
        clean = self._clean_comment(item.name, reason)
        first = self._leaky_demo_comment(item.name, mock_drop) if self.rating(item_id) == 10 else clean

        prompt = prompts.AUCTION_STRATEGY.format(
            name=self.name, scenario_title=self.scenario.title, scenario_kind=self.scenario.kind or "a shared-items split",
            ratings=json.dumps({self.items[i].name: r for i, r in (self.prefs.ratings if self.prefs else {}).items()}),
            reasons=json.dumps({self.items[i].name: r for i, r in (self.prefs.reasons if self.prefs else {}).items()}),
            item=item.name, market=market, rivals=", ".join(info.get("rivals", [])) or "none",
            remaining=", ".join(f"{self.items[r['item_id']].name} (${r['market']:,.0f})" for r in upcoming) or "none",
            cap=cap, value=v)
        ans, src = llm.ask_json_or(prompt, {"drop_price": mock_drop, "comment": first})
        try:
            suggestion = float(ans.get("drop_price", mock_drop))
        except (TypeError, ValueError):
            suggestion = mock_drop
        drop = max(0.0, min(suggestion, v, cap))          # 7.5 step 2: code clamps the LLM
        with self.lock:
            self.drops[item_id] = drop
            self.caps_seen[item_id] = cap

        def drafts(attempt: int) -> str:
            if attempt == 0:
                return str(ans.get("comment") or clean)
            if src in ("mock", "fallback"):
                return clean
            retry = prompts.COMMENT_RETRY.format(name=self.name, scenario_title=self.scenario.title,
                                                 item=item.name, reason=reason or "none given")
            return str(llm.ask_json_or(retry, {"comment": clean})[0].get("comment") or clean)

        secrets = self._secrets()
        public = self._public_numbers([cap, float(info.get("credits", 0) or 0)])
        sent, blocked = filtered_message(drafts, secrets, public)
        if blocked:
            self.blocked_drafts.append(str(ans.get("comment")))
        self._persist()
        return {"comment": sent, "filtered": blocked, "llm": src}

    def _clean_comment(self, item_name: str, reason: str) -> str:
        if reason:
            return f"This one matters to {self.name}: “{reason}”"
        return f"{self.name} would be glad to give the {item_name.lower()} a good home."

    def _leaky_demo_comment(self, item_name: str, drop: float) -> str:
        # Mock mode drafts one over-sharing line for the client's top item, so the
        # leak filter visibly blocks it on the big screen (PLAN.md 7.8).
        return f"Honestly, {self.name} would go up to ${drop:,.0f} for the {item_name.lower()}."

    # ---- negotiation (PLAN.md section 8) ---------------------------------------
    def negotiate(self, body: dict) -> dict:
        """body.type == "propose": {round, contested {item: [pids]}} -> a proposal.
        body.type == "respond": {round, from, proposal, outcomes, cash} -> accept / reject."""
        if body.get("type") == "propose":
            return self._propose(body)
        return self._respond(body)

    def _mock_proposal(self, contested: dict[str, list[str]]) -> dict:
        """Claim my most valued contested item (one per person), hand the rest out evenly, at market value."""
        values, items = self.values(), self.items
        mine = sorted((i for i, ps in contested.items() if self.pid in ps), key=lambda i: -values.get(i, 0))
        count: dict[str, int] = {}
        deal = {}
        if mine:
            deal[mine[0]] = self.pid
            count[self.pid] = 1
        for i in sorted(contested, key=lambda i: -(items[i].market_value or 0)):
            if i in deal:
                continue
            others = [p for p in contested[i] if p != self.pid] or contested[i]
            pick = min(others, key=lambda p: (count.get(p, 0), contested[i].index(p)))
            deal[i] = pick
            count[pick] = count.get(pick, 0) + 1
        return {i: {"winner": w, "price": items[i].market_value or 0.0} for i, w in deal.items()}

    def _valid(self, proposal: dict, contested: dict[str, list[str]]) -> bool:
        try:
            return (set(proposal) == set(contested)
                    and all(proposal[i]["winner"] in contested[i] and float(proposal[i]["price"]) > 0 for i in contested))
        except (KeyError, TypeError, ValueError):
            return False

    def _propose(self, body: dict) -> dict:
        contested = body["contested"]
        mock = self._mock_proposal(contested)
        top = next((i for i, d in mock.items() if d["winner"] == self.pid), None)
        reason = (self.prefs.reasons.get(top) if (self.prefs and top) else None) or ""
        mock_msg = (f"A split where everyone leaves with something they love. For {self.name}, the "
                    f"{self.items[top].name.lower()} is the one: \u201c{reason}\u201d" if top and reason
                    else "A split where everyone leaves with something they love, at appraised value.")
        prompt = prompts.NEGOTIATE_PROPOSE.format(
            name=self.name, scenario_title=self.scenario.title, scenario_kind=self.scenario.kind or "a shared-items split",
            round=body.get("round", 1), ratings=json.dumps(self.prefs.ratings if self.prefs else {}),
            reasons=json.dumps(self.prefs.reasons if self.prefs else {}),
            contested=json.dumps({i: {"contestants": ps, "market": self.items[i].market_value} for i, ps in contested.items()}))
        ans, src = llm.ask_json_or(prompt, {"proposal": mock, "message": mock_msg})
        proposal = ans.get("proposal") if self._valid(ans.get("proposal") or {}, contested) else mock
        proposal = {i: {"winner": d["winner"], "price": round(float(d["price"]), 2)} for i, d in proposal.items()}
        msg, blocked = self._filter(lambda a: str(ans.get("message") or mock_msg) if a == 0 else mock_msg,
                                    [d["price"] for d in proposal.values()])
        return {"type": "propose", "from": self.pid, "round": body.get("round", 1), "proposal": proposal,
                "message": msg, "filtered": blocked}

    def _respond(self, body: dict) -> dict:
        proposal = body["proposal"]
        ok = self.attest(body["outcomes"], body["cash"])["proportional_ok"]
        rnd = body.get("round", 1)
        if not ok:   # code rule: a deal below my fair share must be rejected
            return {"type": "reject", "from": self.pid, "round": rnd, "filtered": 0,
                    "message": "That leaves my client short of a fair share. We'll pass."}
        if body.get("from") == self.pid:
            return {"type": "accept", "from": self.pid, "round": rnd, "filtered": 0, "message": ""}
        lost = [i for i, d in proposal.items() if d["winner"] != self.pid and self.rating(i) >= 9]
        if lost:
            mock = {"decision": "reject", "message": f"{self.name} can't give up the {self.items[lost[0]].name.lower()}. "
                                                     "We'd rather let the bidding decide that one."}
        else:
            mock = {"decision": "accept", "message": "That works for my client. Thank you."}
        names = {p.id: p.name for p in self.scenario.participants}
        prompt = prompts.NEGOTIATE_RESPOND.format(
            name=self.name, scenario_title=self.scenario.title, round=rnd,
            ratings=json.dumps(self.prefs.ratings if self.prefs else {}), reasons=json.dumps(self.prefs.reasons if self.prefs else {}),
            proposer=names.get(body.get("from"), body.get("from")),
            proposal=json.dumps({self.items[i].name: {"winner": names.get(d["winner"]), "price": d["price"]} for i, d in proposal.items()}))
        ans, _ = llm.ask_json_or(prompt, mock)
        decision = "accept" if str(ans.get("decision", mock["decision"])).lower().startswith("acc") else "reject"
        msg, blocked = self._filter(lambda a: str(ans.get("message") or mock["message"]) if a == 0 else mock["message"],
                                    [d["price"] for d in proposal.values()])
        return {"type": decision, "from": self.pid, "round": rnd, "message": msg, "filtered": blocked}

    def _filter(self, drafts, extra_public: list[float]) -> tuple[str, int]:
        sent, blocked = filtered_message(drafts, self._secrets(), self._public_numbers(extra_public))
        if blocked:
            self.blocked_drafts.append(drafts(0))
        return sent, blocked

    def auction_tick(self, item_id: str, price: float) -> dict:
        """7.5 step 3: pure code, no LLM."""
        return {"stay": price <= self.drops.get(item_id, 0.0)}

    def attest(self, outcomes: list[dict | Outcome], cash: dict[str, float]) -> dict:
        outs = [Outcome.model_validate(o if isinstance(o, dict) else o.model_dump()) for o in outcomes]
        values = self.values()
        res = attest_fn(self.pid, outs, cash, self.items, values)
        u = sum(values.get(o.item_id, 0.0) for o in outs if o.winner == self.pid) + cash.get(self.pid, 0.0)
        prop = sum(self.items[o.item_id].shares.get(self.pid, 0) * values.get(o.item_id, 0.0) for o in outs)
        self.attest_detail = {"got": round(u, 2), "proportional_share": round(prop, 2)}
        self._persist()
        return res

    def unlock(self) -> dict:
        self.unlocked = True
        self._persist()
        return {"ok": True}

    def reveal(self) -> dict:
        if not self.unlocked:
            raise PermissionError("locked until the verdict is final")
        return {
            "participant": self.pid,
            "ratings": self.prefs.ratings if self.prefs else {},
            "max_prices": self.prefs.max_prices if self.prefs else {},
            "reasons": self.prefs.reasons if self.prefs else {},
            "values": {k: round(v, 2) for k, v in self.values().items()},
            "drop_prices": {k: round(v, 2) for k, v in self.drops.items()},
            "blocked_drafts": self.blocked_drafts,
            "fairness": self.attest_detail,
        }
