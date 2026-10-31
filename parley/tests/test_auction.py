from core.allocation import auction_order, classify, classify_all, compute_credits, interest_bucket, spend_caps
from core.auction import run_clock_auction, start_price, tick_step
from core.fairness import attest, private_value
from core.models import Item, Outcome, load_scenario


def bidder(drop):
    return lambda price: price <= drop


def test_clock_highest_drop_wins_near_second_price():
    r = run_clock_auction("ring", 9000, {"ana": bidder(6500), "cara": bidder(7200)})
    assert r.winner == "cara"
    # clock: 1800 + 450k; ana drops at 6750 (> 6500), cara still in
    assert r.price == 6750
    assert r.drops == [("ana", 6750)]
    assert r.tiebreak is None


def test_clock_three_bidders():
    r = run_clock_auction("x", 1000, {"a": bidder(300), "b": bidder(700), "c": bidder(500)})
    assert r.winner == "b"
    assert r.price == 550           # c dropped at 550; b wins there
    assert [p for p, _ in r.drops] == ["a", "c"]


def test_tie_fewer_wins_then_coin_flip():
    r = run_clock_auction("coins", 7000, {"ben": bidder(5300), "cara": bidder(5300)}, {"cara": 1})
    assert r.winner == "ben"
    assert r.price == 5250           # last price both accepted
    assert "fewer contested items" in r.tiebreak and r.tied == ["ben", "cara"]
    r1 = run_clock_auction("coins", 7000, {"ben": bidder(5300), "cara": bidder(5300)}, {}, seed="s")
    r2 = run_clock_auction("coins", 7000, {"ben": bidder(5300), "cara": bidder(5300)}, {}, seed="s")
    assert r1.winner == r2.winner and "coin flip" in r1.tiebreak


def test_clock_parameters():
    assert start_price(9000) == 1800
    assert tick_step(9000) == 450
    assert tick_step(60) == 5


def test_buckets_and_classify():
    assert [interest_bucket(r) for r in (0, 4, 5, 6, 7, 10)] == ["NONE", "NONE", "WANT", "WANT", "STRONG", "STRONG"]
    it = Item(id="x", name="x", category="other", market_value=100, shares={"a": 1})
    assert classify(it, {"a": "STRONG", "b": "STRONG", "c": "WANT"}) == ("contested", ["a", "b"])
    assert classify(it, {"a": "STRONG", "b": "WANT"}) == ("easy", ["a"])
    assert classify(it, {"a": "WANT", "b": "NONE"}) == ("easy", ["a"])
    assert classify(it, {"a": "WANT", "b": "WANT"}) == ("contested", ["a", "b"])
    assert classify(it, {"a": "NONE"}) == ("unwanted", [])
    locked = it.model_copy(update={"locked_to": "c"})
    assert classify(locked, {"a": "STRONG", "b": "STRONG"}) == ("locked", ["c"])


def test_inheritance_credits_match_plan():
    sc = load_scenario("inheritance")
    items = {i.id: i for i in sc.items}
    contestants = {"ring": ["ana", "cara"], "coins": ["ben", "cara"], "piano": ["ana", "ben"]}
    credits = compute_credits(items, contestants)
    assert credits == {"ana": 7500, "ben": 6500, "cara": 8000}
    assert spend_caps(credits, 0.5) == {"ana": 11250, "ben": 9750, "cara": 12000}
    assert auction_order(items, contestants) == ["ring", "coins", "piano"]


def test_classify_all_inheritance_demo_buckets():
    sc = load_scenario("inheritance")
    interest = {
        "ana": {"ring": "STRONG", "coins": "NONE", "piano": "STRONG", "painting": "WANT", "car": "NONE", "dining": "WANT", "clock": "NONE", "china": "NONE"},
        "ben": {"ring": "NONE", "coins": "STRONG", "piano": "STRONG", "painting": "NONE", "car": "STRONG", "dining": "NONE", "clock": "NONE", "china": "NONE"},
        "cara": {"ring": "STRONG", "coins": "STRONG", "piano": "NONE", "painting": "STRONG", "car": "NONE", "dining": "NONE", "clock": "NONE", "china": "NONE"},
    }
    classes, contestants, outcomes = classify_all(sc, interest)
    assert contestants == {"ring": ["ana", "cara"], "coins": ["ben", "cara"], "piano": ["ana", "ben"]}
    assert classes["painting"] == "locked" and classes["car"] == "easy" and classes["clock"] == "unwanted"
    by = {o.item_id: o for o in outcomes}
    assert by["car"].winner == "ben" and by["dining"].winner == "ana" and by["painting"].winner == "cara"


def test_private_value_and_attest():
    assert private_value(9000, 0, None) == 0
    assert private_value(9000, 10, None) == 13500
    assert private_value(9000, 7, 5000) == 5000
    items = {"x": Item(id="x", name="x", category="o", market_value=100, shares={"a": 0.5, "b": 0.5})}
    out = [Outcome(item_id="x", winner="a", price=100, method="auction")]
    assert attest("b", out, {"a": -50, "b": 50}, items, {"x": 90})["proportional_ok"] is True
    assert attest("b", out, {"a": -40, "b": 40}, items, {"x": 90})["proportional_ok"] is False
