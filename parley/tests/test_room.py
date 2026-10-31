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


def test_manual_bidding_leaves_the_drop_to_the_person(agent):
    agent.claim()
    agent.demo_fill()
    agent.auction_start({"item_id": "ring", "market": 9000, "cap": 11250, "remaining": [], "manual": True})
    assert agent.auction_tick("ring", 11250)["stay"] is True      # stays in until the cap...
    assert agent.auction_tick("ring", 11700)["stay"] is False
    agent.override("ring", "drop")                                  # ...or until the person presses Drop out
    assert agent.auction_tick("ring", 1800)["stay"] is False


def test_unclaimed_seat_still_bids_automatically(agent):
    agent.demo_fill()
    later = [{"item_id": "piano", "market": 6000, "contestants": ["ana", "ben"]}]
    agent.auction_start({"item_id": "ring", "market": 9000, "cap": 11250, "remaining": later, "manual": True})
    assert agent.drops["ring"] < 11250          # agent still saves budget for the piano


def test_photo_upload_and_appraise(tmp_path, monkeypatch):
    import base64
    import io

    import segno

    import orchestrator.app as appmod
    import orchestrator.appraiser as appr
    monkeypatch.setattr(appmod, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(appr, "IMAGE_DIR", tmp_path)
    c = TestClient(appmod.app)
    buf = io.BytesIO()
    segno.make("chair").save(buf, kind="png")
    r = c.post("/admin/upload", json={"data_url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()})
    url = r.json()["url"]
    assert r.status_code == 200 and url.startswith("/images/") and c.get(url).status_code == 200
    assert c.post("/admin/upload", json={"data_url": "data:text/html;base64,PGI+"}).status_code == 400
    # mock mode: value falls back to the depreciation formula (rounded to $10)
    v = c.post("/admin/appraise", json={"name": "Chair", "category": "furniture", "purchase_price": 500,
                                         "age_years": 2, "image": url}).json()
    assert v["market_value"] == 320 and v["value_source"] == "depreciation formula"


def test_self_named_join_renames_seat(monkeypatch):
    import orchestrator.app as appmod
    from orchestrator.agents import LocalAgent

    e = appmod.Engine(agent_urls=[], tick_delay=0, phase_pause=0)
    e.load("roommates")
    for pid, a in e.agents.items():
        a.url = f"http://localhost:800{'123'[list(e.agents).index(pid)]}"
    monkeypatch.setattr(appmod, "engine", e)
    c = TestClient(appmod.app)
    r = c.get("/join/priya", params={"name": "  Karthik "}, follow_redirects=False)
    assert r.status_code == 307
    assert e.name("priya") == "Karthik" and e.agents["priya"].logic.name == "Karthik"
    c.get("/join/sam", params={"name": "karthik"}, follow_redirects=False)
    assert e.name("sam") == "karthik (sam)"                        # names stay distinct
    assert isinstance(e.agents["alex"], LocalAgent)
