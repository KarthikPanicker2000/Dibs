import pytest

from core.models import Item, Outcome, load_scenario
from core.settlement import minimal_transfers, settle


def _item(iid, market, shares):
    return Item(id=iid, name=iid, category="other", market_value=market, shares=shares)


def test_sanity_ana_pays_cara_2750():
    """PLAN.md 7.6 sanity check: equal 50/50 shares, Ana pays Cara $2.75k net."""
    half = {"ana": 0.5, "cara": 0.5}
    items = {i.id: i for i in [_item("ring", 9000, half), _item("coins", 7000, half), _item("piano", 6000, half)]}
    contestants = {k: ["ana", "cara"] for k in items}
    outcomes = [
        Outcome(item_id="ring", winner="ana", price=7500, method="auction"),
        Outcome(item_id="coins", winner="cara", price=5000, method="auction"),
        Outcome(item_id="piano", winner="ana", price=3000, method="auction"),
    ]
    cash = settle(outcomes, items, contestants)
    assert cash["ana"] == pytest.approx(-2750)
    assert cash["cara"] == pytest.approx(2750)
    t = minimal_transfers(cash)
    assert len(t) == 1
    assert (t[0].payer, t[0].payee, t[0].amount) == ("ana", "cara", 2750.0)


def test_non_bidding_owner_paid_at_least_market():
    third = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    items = {"ring": _item("ring", 9000, third)}
    out = [Outcome(item_id="ring", winner="c", price=6000, method="auction")]
    cash = settle(out, items, {"ring": ["a", "c"]})
    assert cash["a"] == pytest.approx(2000)       # contestant: clearing price
    assert cash["b"] == pytest.approx(3000)       # not bidding: protected at market value
    assert cash["c"] == pytest.approx(-5000)


def test_sold_proceeds_split_by_share_and_unwanted_skipped():
    items = {"rug": _item("rug", 120, {"a": 0.5, "b": 0.5})}
    out = [Outcome(item_id="rug", winner=None, price=0, method="unwanted")]
    cash = settle(out, items, {}, sold={"rug": 50})
    assert cash == {"a": 25, "b": 25}


def test_sole_owner_and_locked_bequest_move_no_cash():
    sc = load_scenario("inheritance")
    items = {i.id: i for i in sc.items}
    out = [Outcome(item_id="painting", winner="cara", price=4000, method="locked")]
    assert settle(out, items) == {}


def test_easy_buyout_car():
    sc = load_scenario("inheritance")
    items = {i.id: i for i in sc.items}
    out = [Outcome(item_id="car", winner="ben", price=18000, method="easy")]
    cash = settle(out, items, {"car": ["ben"]})
    assert cash["ana"] == pytest.approx(6000, abs=0.01)
    assert cash["cara"] == pytest.approx(6000, abs=0.01)
    assert cash["ben"] == pytest.approx(-12000, abs=0.01)


def test_minimal_transfers_three_way():
    t = minimal_transfers({"a": 100, "b": -150, "c": 50})
    assert [(x.payer, x.payee, x.amount) for x in t] == [("b", "a", 100), ("b", "c", 50)]
    assert minimal_transfers({"a": 0.001, "b": -0.001}) == []
