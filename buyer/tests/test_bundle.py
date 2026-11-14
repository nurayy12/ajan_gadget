import pytest

from buyer.bundle import bundle_shipping, select_bundle
from buyer.tests.sample_data import LISTINGS, make_scenario


def ids(bundle):
    return [l.listing_id for l in bundle]


def test_single_returns_only_target():
    assert ids(select_bundle(make_scenario(5000), LISTINGS, "single")) == ["L1"]


def test_bundle_takes_all_needed_items_when_budget_allows():
    # liste toplamı 1600 + hedef ilanın kargosu 50 = 1650 <= 1800
    bundle = select_bundle(make_scenario(1800), LISTINGS, "bundle")
    assert ids(bundle) == ["L1", "L2", "L3"]


def test_bundle_fits_exactly_at_budget_with_target_shipping():
    # 1600 + 50 = 1650: tam bütçe sığar (en yüksek kargo 60 olsaydı sığmazdı)
    assert ids(select_bundle(make_scenario(1650), LISTINGS, "bundle")) == ["L1", "L2", "L3"]
    assert ids(select_bundle(make_scenario(1649), LISTINGS, "bundle")) == ["L1", "L3"]


def test_bundle_respects_budget():
    # üçü birden 1660 TL, bütçe 1500: iki ürünlük en ucuz paket (L1 + L3) seçilir
    scenario = make_scenario(1500)
    bundle = select_bundle(scenario, LISTINGS, "bundle")
    assert ids(bundle) == ["L1", "L3"]
    assert sum(l.list_price for l in bundle) + bundle_shipping(bundle, "L1") <= scenario.budget


def test_bundle_only_uses_target_sellers_listings():
    bundle = select_bundle(make_scenario(5000), LISTINGS, "bundle")
    assert {l.seller_id for l in bundle} == {"s1"}


def test_bundle_always_contains_target():
    assert ids(select_bundle(make_scenario(450), LISTINGS, "bundle")) == ["L1"]  # 400 + 50
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


def test_bundle_shipping_is_target_listings_shipping():
    s1 = [l for l in LISTINGS if l.seller_id == "s1"]  # kargolar: L1=50, L2=60, L3=40
    assert bundle_shipping(s1, "L1") == 50
    assert bundle_shipping(s1, "L2") == 60
    assert bundle_shipping(s1, "L3") == 40
    assert bundle_shipping([], "L1") == 0.0


def test_bundle_shipping_requires_target_in_bundle():
    with pytest.raises(ValueError):
        bundle_shipping([LISTINGS[1]], "L1")
