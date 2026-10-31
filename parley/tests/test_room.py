"""Phone seats: claiming, locking, human bidding overrides, custom rooms."""
import pytest
from fastapi.testclient import TestClient

from agent.logic import AgentLogic
from core.models import load_scenario


@pytest.fixture
def agent(tmp_path):
    a = AgentLogic("ana", data_dir=tmp_path)
    a.setup(load_scenario("inheritance"), "ana", reset=True)
    return a


def test_seat_claim_is_exclusive(agent):
    tok = agent.claim()["token"]
    assert agent.claim(tok)["token"] == tok           # same phone can come back
    with pytest.raises(PermissionError):
        agent.claim("someone-else")
    with pytest.raises(PermissionError):
        agent.check_owner(None)


def test_ratings_lock_after_interest_and_override_clamps(agent):
    agent.demo_fill()
    agent.interest()
    with pytest.raises(ValueError):
        agent.set_prefs({"ratings": {"ring": 1}})
    agent.auction_start({"item_id": "ring", "market": 9000, "cap": 11250, "remaining": []})
    assert agent.override("ring", "stay", 50000)["drop"] == 11250   # clamped to the spend cap
    assert agent.auction_tick("ring", 11000)["stay"] is True
    agent.override("ring", "drop")
    assert agent.auction_tick("ring", 1800)["stay"] is False


def test_admin_room_roundtrip(tmp_path, monkeypatch):
    import orchestrator.app as appmod
    monkeypatch.setattr(appmod, "SCENARIO_DIR", tmp_path)
    monkeypatch.setattr("core.models.SCENARIO_DIR", tmp_path)
    monkeypatch.setattr(appmod, "engine", appmod.Engine(agent_urls=[], tick_delay=0, phase_pause=0))
    c = TestClient(appmod.app)
    room = {"title": "Lab move", "will": "Split fairly.", "participants": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
            "items": [{"id": "chair", "name": "Chair", "category": "furniture", "market_value": 100,
                       "shares": {"a": 0.5, "b": 0.5}}]}
    r = c.post("/admin/room", json=room)
    assert r.status_code == 200 and r.json()["id"] == "room-lab-move"
    assert (tmp_path / "room-lab-move.json").exists()
    assert c.get("/state").json()["scenario"]["title"] == "Lab move"
    assert c.get("/qr.svg", params={"data": "http://x/join"}).text.count("<svg") == 1
