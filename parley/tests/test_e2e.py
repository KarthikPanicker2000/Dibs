"""Whole inheritance flow in-process with LocalAgents in mock mode: the demo story must hold."""
import pytest

from orchestrator.app import Engine


def run(scenario_id):
    e = Engine(agent_urls=[], tick_delay=0, phase_pause=0)
    e.load(scenario_id)
    while e.next_phase():
        e.step()
    return e


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.logic.DATA_DIR", tmp_path)


@pytest.fixture
def engine():
    return run("inheritance")


def test_inheritance_story(engine):
    wins = {r["item_id"]: (r["winner"], r["price"]) for r in engine.auction_results}
    assert wins == {"ring": ("cara", 6750), "coins": ("ben", 5600), "piano": ("ana", 4200)}
    assert all(r["tiebreak"] is None for r in engine.auction_results)
    v = engine.verdict
    assert v["attestations"] == {"ana": True, "ben": True, "cara": True}
    assert [(t["payer"], t["payee"], t["amount"]) for t in v["transfers"]] == [("ben", "ana", 5516.67), ("ben", "cara", 5450.0)]
    assert any(e.kind == "filtered" for e in engine.events)


def test_reveal_only_after_unlock_and_comments_clean(engine):
    assert set(engine.reveal) == {"ana", "ben", "cara"}
    secrets = [d for r in engine.reveal.values() for d in r["drop_prices"].values()]
    for e in engine.events:
        if e.kind == "message" and e.actor in engine.agents:
            assert "up to" not in e.text and not any(f"{s:,.0f}" in e.text for s in secrets)


def test_roommates_story_negotiated():
    e = run("roommates")
    items = {i.id: i for i in e.scenario.items}
    assert items["couch"].market_value == 600 and items["espresso"].market_value == 350
    assert items["couch"].value_source == "depreciation formula"
    assert e.verdict["chosen"] == "negotiated" and e.auction_results == []
    by = {o.item_id: o for o in e.outcomes}
    assert {i: by[i].winner for i in ("couch", "espresso", "table")} == {"couch": "alex", "espresso": "sam", "table": "priya"}
    assert all(e.verdict["attestations"].values())
    assert by["tv"].winner == "alex" and by["mixer"].winner == "priya" and by["cookware"].winner == "alex"
    assert by["airfryer"].winner == "sam" and by["rug"].winner is None and by["vacuum"].winner is None


def test_roommates_story_auction_when_negotiation_off(monkeypatch):
    monkeypatch.setenv("NEGOTIATE", "0")
    e = run("roommates")
    wins = {r["item_id"]: (r["winner"], r["price"]) for r in e.auction_results}
    assert wins == {"couch": ("priya", 450), "espresso": ("alex", 280), "table": ("sam", 240)}
    assert all(e.verdict["attestations"].values())


def test_inheritance_negotiation_deadlocks(engine):
    assert engine.negotiation["rounds"] == 4 and engine.negotiation["deal"] is False
    assert engine.verdict["chosen"] == "auction"


def test_spending_cap_edge_case_is_reported():
    e = run("inheritance-edge")
    assert e.verdict["attestations"] == {"ana": True, "ben": False, "cara": True}
    assert "spending-cap" in e.verdict["summary"]


def test_claude_backend_runs_standalone_cli(monkeypatch):
    """LLM_MODE=claude shells out to `claude -p` with no tools, no API keys and no parent-session vars."""
    import subprocess

    from agent import llm
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, env=kw["env"], input=kw["input"])
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-pass")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    monkeypatch.setattr(llm, "MODE", "claude")
    monkeypatch.setattr(llm, "CLAUDE_BIN", "claude")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert llm.ask_json_or("hi", {"ok": False}) == ({"ok": True}, "claude")
    assert seen["cmd"][:2] == ["claude", "-p"] and seen["cmd"][seen["cmd"].index("--tools") + 1] == ""
    assert not any(k.startswith(("CLAUDE", "ANTHROPIC_")) for k in seen["env"])
    assert seen["input"] == "hi"


def test_fatal_llm_error_switches_to_mock(monkeypatch):
    from agent import llm

    def boom(prompt):
        raise RuntimeError("Failed to authenticate: OAuth session expired")

    monkeypatch.setattr(llm, "MODE", "claude")
    monkeypatch.setattr(llm, "disabled_reason", None)
    monkeypatch.setattr(llm, "ask_text", boom)
    assert llm.ask_json_or("x", {"a": 1}) == ({"a": 1}, "fallback")
    assert "authenticate" in llm.disabled_reason
    monkeypatch.setattr(llm, "ask_text", lambda p: '{"a": 2}')
    assert llm.ask_json_or("x", {"a": 1}) == ({"a": 1}, "fallback")   # stays on mock, no more slow calls
    monkeypatch.setattr(llm, "_disabled_at", 0.0)                     # a minute later it tries again
    assert llm.ask_json_or("x", {"a": 1}) == ({"a": 2}, "claude") and llm.disabled_reason is None


def test_gemma_code_path_with_fake_model(monkeypatch):
    """Exercise the non-mock path: JSON parsing, clamping, leak-filter retries, fallbacks."""
    from agent import llm

    def fake(prompt):
        if "estimate used resale value" in prompt:
            return 'Sure! {"value": 123, "confidence": "medium", "reasoning": "Typical listing."}'
        if '"drop_price"' in prompt:
            return '```json\n{"drop_price": 999999, "comment": "My max is $13,500, just saying."}\n```'
        if "previous public line was blocked" in prompt:
            return '{"comment": "We would love to keep it in the family."}'
        if '"proposal"' in prompt:
            return "not json at all"            # invalid -> agent falls back to its mock proposal
        if '"decision"' in prompt:
            return '{"decision": "reject", "message": "We will let the bidding decide."}'
        return '{"explanation": "You got a fair split."}'

    monkeypatch.setattr(llm, "MODE", "gemma")
    monkeypatch.setattr(llm, "ask_text", fake)
    e = run("inheritance")
    assert e.verdict["explanations"]["ana"] == "You got a fair split."
    assert any(ev.kind == "filtered" for ev in e.events)
    assert not any("13,500" in ev.text for ev in e.events)
    # LLM asked for 999999 but code clamps to min(private value, remaining cap)
    for pid, r in e.reveal.items():
        for item_id, drop in r["drop_prices"].items():
            assert drop <= r["values"][item_id] + 0.01 and drop <= e.caps[pid] + 0.01
    assert e.negotiation["deal"] is False
