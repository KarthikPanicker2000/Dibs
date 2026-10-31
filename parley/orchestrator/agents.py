"""Agent interface with two implementations (PLAN.md section 5).

LocalAgent  -> AgentLogic object in this process (tests, quick demo)
RemoteAgent -> the same logic behind HTTP (agent/service.py, locally or on Maritime)
"""
from __future__ import annotations

import httpx

from agent import logic as agent_logic
from agent.logic import AgentLogic
from core.models import Outcome, Scenario


def _outs(outcomes: list[Outcome]) -> list[dict]:
    return [o.model_dump() for o in outcomes]


class Agent:
    pid: str
    url: str | None = None

    def setup(self, scenario: Scenario, reset: bool = False) -> dict: ...
    def status(self) -> dict: ...
    def demo_fill(self) -> dict: ...
    def interest(self) -> dict[str, str]: ...
    def negotiate(self, body: dict) -> dict: ...
    def auction_start(self, info: dict) -> dict: ...
    def auction_tick(self, item_id: str, price: float) -> bool: ...
    def attest(self, outcomes: list[Outcome], cash: dict[str, float]) -> bool: ...
    def unlock(self) -> None: ...
    def reveal(self) -> dict: ...


class LocalAgent(Agent):
    def __init__(self, pid: str, logic: AgentLogic | None = None):
        self.pid = pid
        # each in-process agent gets its own data dir, like its own VM would
        self.logic = logic or AgentLogic(pid, data_dir=agent_logic.DATA_DIR / "local" / pid)

    def setup(self, scenario, reset=False):
        return self.logic.setup(scenario, self.pid, reset)

    def status(self):
        return self.logic.status()

    def demo_fill(self):
        return self.logic.demo_fill()

    def interest(self):
        return self.logic.interest()

    def negotiate(self, body):
        return self.logic.negotiate(body)

    def auction_start(self, info):
        return self.logic.auction_start(info)

    def auction_tick(self, item_id, price):
        return self.logic.auction_tick(item_id, price)["stay"]

    def attest(self, outcomes, cash):
        return self.logic.attest(_outs(outcomes), cash)["proportional_ok"]

    def unlock(self):
        self.logic.unlock()

    def reveal(self):
        return self.logic.reveal()


class RemoteAgent(Agent):
    def __init__(self, pid: str, url: str, timeout: float = 60.0, orch_url: str | None = None):
        self.pid = pid
        self.orch_url = orch_url      # lets the agent relay public room state to its phone
        self.url = url.rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=timeout)

    def _post(self, path: str, body: dict | None = None) -> dict:
        r = self.http.post(path, json=body or {})
        r.raise_for_status()
        return r.json()

    def _get(self, path: str) -> dict:
        r = self.http.get(path)
        r.raise_for_status()
        return r.json()

    def setup(self, scenario, reset=False):
        return self._post("/setup", {"scenario": scenario.model_dump(), "participant_id": self.pid, "reset": reset,
                                     "orch_url": self.orch_url})

    def status(self):
        return self._get("/status")

    def demo_fill(self):
        return self._post("/demo_fill")

    def interest(self):
        return self._get("/interest")

    def negotiate(self, body):
        return self._post("/negotiate", body)

    def auction_start(self, info):
        return self._post("/auction/start", info)

    def auction_tick(self, item_id, price):
        return self._post("/auction/tick", {"item_id": item_id, "price": price})["stay"]

    def attest(self, outcomes, cash):
        return self._post("/attest", {"outcomes": _outs(outcomes), "cash": cash})["proportional_ok"]

    def unlock(self):
        self._post("/unlock")

    def reveal(self):
        return self._get("/reveal")
