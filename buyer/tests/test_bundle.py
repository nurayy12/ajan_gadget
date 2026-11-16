import pytest

from buyer._policy import buyer_shipping
from buyer.bundle import MAX_BASKET_ITEMS, bundle_feasible, bundle_shipping, select_bundle
from buyer.tests.sample_data import LISTINGS, make_scenario


def ids(bundle):
    return [l.listing_id for l in bundle]


def test_single_returns_only_target():
    assert ids(select_bundle(make_scenario(5000), LISTINGS, "single")) == ["L1"]


def test_bundle_takes_all_needed_items_when_budget_allows():
    # ilk teklif 0,70 × 1600 = 1120 (>= 400 TL: kargo alıcıya ücretsiz) <= 1800
    bundle = select_bundle(make_scenario(1800), LISTINGS, "bundle")
    assert ids(bundle) == ["L1", "L2", "L3"]


def test_bundle_fits_exactly_at_budget_with_target_shipping():
    # ilk teklif 0,70 × 1600 = 1120, kargo 0: tam bütçeye sığar; bir kuruş eksikse sığmaz
    assert ids(select_bundle(make_scenario(1120), LISTINGS, "bundle")) == ["L1", "L2", "L3"]
    assert ids(select_bundle(make_scenario(1119.99), LISTINGS, "bundle")) == ["L1", "L3"]


def test_bundle_respects_budget():
    # üçü birden 1120 TL ister, bütçe 1000: iki ürünlük en ucuz paket (L1 + L3) seçilir
    scenario = make_scenario(1000)
    bundle = select_bundle(scenario, LISTINGS, "bundle")
    assert ids(bundle) == ["L1", "L3"]
    opening = round(0.70 * sum(l.list_price for l in bundle), 2)
    assert opening + buyer_shipping(bundle, opening) <= scenario.budget


def test_bundle_only_uses_target_sellers_listings():
    bundle = select_bundle(make_scenario(5000), LISTINGS, "bundle")
    assert {l.seller_id for l in bundle} == {"s1"}


def test_bundle_always_contains_target():
    assert ids(select_bundle(make_scenario(450), LISTINGS, "bundle")) == ["L1"]  # L1+L3: ilk teklif 490 (kargo 0) > 450
    assert ids(select_bundle(make_scenario(100), LISTINGS, "bundle")) == ["L1"]  # sığmasa da hedef kalır


def test_bundle_with_other_target():
    bundle = select_bundle(make_scenario(5000, target_listing_id="L2"), LISTINGS, "bundle")
    assert ids(bundle)[0] == "L2"
    assert set(ids(bundle)) == {"L1", "L2", "L3"}


def test_unknown_mode_and_missing_target():
    with pytest.raises(ValueError):
        select_bundle(make_scenario(1000), LISTINGS, "paket")
    with pytest.raises(ValueError):
        select_bundle(make_scenario(1000, target_listing_id="YOK"), LISTINGS, "single")


def test_bundle_shipping_is_highest_shipping_of_basket():
    s1 = [l for l in LISTINGS if l.seller_id == "s1"]  # kargolar: L1=50, L2=60, L3=40
    assert bundle_shipping(s1) == 60
    assert bundle_shipping(s1, "L1") == 60   # eski çağrılar bozulmaz; hedef ilan artık kullanılmaz
    assert bundle_shipping([LISTINGS[2]], "L3") == 40
    assert bundle_shipping([], "L1") == 0.0


def test_bundle_feasible_uses_shipping_at_opening_price():
    l1 = [LISTINGS[0]]  # liste 400 -> ilk teklif 280 (250-400 arası: kargo 29,99)
    assert bundle_feasible(l1, 309.99)
    assert not bundle_feasible(l1, 309.98)
    s1 = [l for l in LISTINGS if l.seller_id == "s1"]  # ilk teklif 1120, kargo 0
    assert bundle_feasible(s1, 1120) and not bundle_feasible(s1, 1119.99)


def test_bundle_has_at_most_ten_items():
    from schemas import Listing
    words = ["kalem", "masal", "nehir", "orman", "sepet", "tabak", "yelek",
             "zeytin", "bahar", "çiçek", "dolap", "eldiven", "fener", "gitar"]
    many = [Listing(listing_id=f"M{i}", seller_id="sm", title=w, description="d",
                    category="c", size=None, condition="iyi", list_price=100, floor_price=60,
                    shipping_cost=30) for i, w in enumerate(words)]
    scenario = make_scenario(100000, target_listing_id="M0", need_list=words)  # her ilan ayrı bir ihtiyaç
    bundle = select_bundle(scenario, many, "bundle")
    assert len(bundle) == MAX_BASKET_ITEMS and bundle[0].listing_id == "M0"
