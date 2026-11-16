import pytest

from buyer import config
from buyer._policy import buyer_shipping
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
    assert prices[-1] + buyer_shipping(bundle, prices[-1]) <= 1700  # son fiyat + alıcının kargosu bütçeyi aşmaz


def test_tight_budget_caps_limit():
    l1 = [LISTINGS[0]]  # liste 400; 250-400 TL arası alıcı 29,99 TL kargo öder -> sınır 300 - 29,99 = 270,01
    scenario = make_scenario(300)
    prices = [buyer_target_price(scenario, l1, r) for r in range(1, 6)]
    assert all(p == pytest.approx(270.01) for p in prices)


def test_budget_below_shipping_gives_zero():
    assert buyer_target_price(make_scenario(30), [LISTINGS[0]], 3) == 0.0


# --- Dolap kargo basamakları ve config değerlerinin çağrı anında okunması ----------------

from schemas import Listing  # noqa: E402

DIP_ITEM = Listing(listing_id="D1", seller_id="sd", title="Test", description="d", category="c",
                   size=None, condition="iyi", list_price=500, floor_price=300, shipping_cost=60)


def test_offers_stay_within_budget_when_shipping_steps_down():
    # Bütçe 420: sınır 420 (400 TL üstü kargosuz). Ama 392 TL için kargo 29,99 -> 421,99 > 420.
    # Koruma, o turun teklifini 'bütçe - kargo' = 390,01'e indirir.
    scenario = make_scenario(420, target_listing_id="D1")
    prices = [buyer_target_price(scenario, [DIP_ITEM], r) for r in range(1, 6)]
    assert prices == [pytest.approx(p) for p in (364, 378, 390.01, 406, 420)]
    assert all(p + buyer_shipping([DIP_ITEM], p) <= 420 + 1e-9 for p in prices)
    assert prices == sorted(prices)


@pytest.mark.parametrize("budget", [150, 270, 300, 420, 455, 520, 900])
def test_target_is_always_affordable_and_nondecreasing(budget):
    scenario = make_scenario(budget, target_listing_id="D1")
    prices = [buyer_target_price(scenario, [DIP_ITEM], r) for r in range(1, 6)]
    assert prices == sorted(prices)
    for p in prices:
        assert p == 0 or p + buyer_shipping([DIP_ITEM], p) <= budget + 1e-9


def test_config_values_are_read_at_call_time(monkeypatch):
    scenario = make_scenario(5000, target_listing_id="D1")
    base = [buyer_target_price(scenario, [DIP_ITEM], r) for r in range(1, 6)]
    monkeypatch.setattr(config, "START_FRACTION", 0.5)
    assert buyer_target_price(scenario, [DIP_ITEM], 1) == pytest.approx(0.5 * 500 + 0.5 * 500 * 0.2)
    monkeypatch.setattr(config, "START_FRACTION", 0.70)
    monkeypatch.setattr(config, "BETA", 2.0)
    fast = [buyer_target_price(scenario, [DIP_ITEM], r) for r in range(1, 6)]
    assert fast[1] > base[1] and fast[-1] == pytest.approx(base[-1])
    monkeypatch.setattr(config, "BETA", 1.0)
    monkeypatch.setattr(config, "T", 10)
    assert concession_price(70, 100, 5) == pytest.approx(85)   # T=10: 5. tur yarı yolda


def test_missing_policy_module_gives_clear_error(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "policy", None)   # import policy -> ImportError
    with pytest.raises(ImportError, match="policy.py"):
        buyer_target_price(make_scenario(2000), [LISTINGS[0]], 1)
