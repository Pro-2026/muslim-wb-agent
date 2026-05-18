from src.rules.bidding import BidAction, calculate_bid_action


def test_too_little_data():
    r = calculate_bid_action(200, views=50, clicks=2, orders=0, spend=0)
    assert r.action == BidAction.keep


def test_high_cpo_decreases():
    r = calculate_bid_action(300, views=500, clicks=50, orders=1, spend=1000.0)
    assert r.action == BidAction.decrease
    assert r.new_bid < 300


def test_low_ctr_decreases():
    r = calculate_bid_action(300, views=1000, clicks=5, orders=1, spend=100.0)
    assert r.action == BidAction.decrease


def test_good_metrics_increase():
    r = calculate_bid_action(200, views=500, clicks=20, orders=5, spend=400.0)
    assert r.action == BidAction.increase
    assert r.new_bid > 200


def test_respects_max_bid():
    r = calculate_bid_action(1000, views=500, clicks=20, orders=5, spend=400.0)
    assert r.new_bid <= 1000


def test_respects_min_bid():
    r = calculate_bid_action(50, views=500, clicks=5, orders=0, spend=500.0)
    assert r.new_bid >= 50
