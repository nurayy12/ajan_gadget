import pytest

from buyer.pricing import buyer_target_price, concession_price
from buyer.tests.sample_data import LISTINGS, make_scenario


def test_concession_reaches_limit_at_last_round():
    assert concession_price(70, 100, 5) == pytest.approx(100)


def test_concession_linear_for_beta_one():
    assert concession_price(70, 100, 1) == pytest.approx(76)
    assert concession_price(70, 100, 3) == pytest.approx(88)


def test_concession_beta_changes_speed():
    early = concession_price(70, 100, 2, beta=2.0)   # beta büyük: erken taviz
    late = concession_price(70, 100, 2, beta=0.5)    # beta küçük: geç taviz
    assert early > concession_price(70, 100, 2) > late


def test_round_is_clamped():
    assert concession_price(70, 100, 9) == pytest.approx(100)
    assert concession_price(70, 100, 0) == pytest.approx(70)


def test_target_price_for_single_listing():
    l1 = [LISTINGS[0]]  # 400 TL, kargo 50
    scenario = make_scenario(2000)
    assert buyer_target_price(scenario, l1, 1) == pytest.approx(0.7 * 400 + 0.3 * 400 * 0.2)  # 304
    assert buyer_target_price(scenario, l1, 5) == pytest.approx(400)


def test_target_price_never_decreases_and_stays_in_budget():
    bundle = LISTINGS[:3]
    scenario = make_scenario(1700)
    prices = [buyer_target_price(scenario, bundle, r) for r in range(1, 6)]
    assert prices == sorted(prices)
    assert prices[-1] + 50 <= 1700  # son fiyat + hedef ilanın kargosu (L1 = 50) bütçeyi aşmaz


def test_tight_budget_caps_limit():
    l1 = [LISTINGS[0]]  # liste 400, kargo 50, bütçe 300 -> sınır 250
    scenario = make_scenario(300)
    prices = [buyer_target_price(scenario, l1, r) for r in range(1, 6)]
    assert all(p == pytest.approx(250) for p in prices)


def test_budget_below_shipping_gives_zero():
    assert buyer_target_price(make_scenario(30), [LISTINGS[0]], 3) == 0.0
