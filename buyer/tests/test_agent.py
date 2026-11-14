import pytest

from schemas import Listing, Offer
from buyer import llm
from buyer.agent import _finalize_message, buyer_turn
from buyer.bundle import bundle_shipping, select_bundle
from buyer.tests.fake_seller import fake_seller_turn, run_fake_negotiation
from buyer.tests.sample_data import LISTINGS, make_scenario
from buyer.text_utils import format_tl

ITEM = Listing(listing_id="X1", seller_id="sx", title="Test ürünü", description="d", category="c",
               size=None, condition="iyi", list_price=1000, floor_price=800, shipping_cost=50)


def test_first_turn_is_offer_with_code_price():
    scenario = make_scenario(2000, target_listing_id="X1", need_list=["test ürünü"])
    offer = buyer_turn(scenario, [ITEM], [], 1)
    assert offer.sender == "buyer" and offer.round == 1
    assert offer.action == "offer"
    assert offer.price == pytest.approx(760)
    assert offer.listing_ids == ["X1"]
    assert format_tl(760) in offer.message and "{FIYAT}" not in offer.message


def test_fake_seller_drops_five_percent_each_round():
    s1 = fake_seller_turn([ITEM], [], 1)
    s2 = fake_seller_turn([ITEM], [s1], 2)
    assert s1.price == 1000 and s2.price == pytest.approx(950)


def test_negotiation_ends_with_accept_and_respects_budget():
    scenario = make_scenario(2000, target_listing_id="X1", need_list=["test ürünü"])
    result = run_fake_negotiation(scenario, [ITEM])
    last = result.offers[-1]
    assert result.deal and last.action == "accept" and last.round == 4
    assert result.final_price == pytest.approx(902.5)
    assert result.final_price + bundle_shipping([ITEM], "X1") <= scenario.budget


def test_buyer_never_offers_above_seller_last_price():
    scenario = make_scenario(2000, target_listing_id="X1", need_list=["test ürünü"])
    result = run_fake_negotiation(scenario, [ITEM])
    last_seller_price = None
    for o in result.offers:
        if o.sender == "seller":
            last_seller_price = o.price
        elif last_seller_price is not None:
            assert o.price <= last_seller_price


def test_no_deal_when_seller_stays_above_limit():
    scenario = make_scenario(700, target_listing_id="X1", need_list=["test ürünü"])  # sınır 650
    result = run_fake_negotiation(scenario, [ITEM])
    assert result.deal is False and result.final_price is None
    assert result.rounds == 5
    assert all(o.price <= 650 for o in result.offers if o.sender == "buyer")


def test_bundle_message_mentions_bulk_purchase():
    scenario = make_scenario(1800)
    bundle = select_bundle(scenario, LISTINGS, "bundle")
    offer = buyer_turn(scenario, bundle, [], 1)
    assert len(offer.listing_ids) == 3
    assert "toplu" in offer.message.lower() or "paket" in offer.message.lower()


def test_accept_uses_sellers_price():
    seller = Offer(sender="seller", round=1, action="offer", listing_ids=["X1"], price=100.0, message="m")
    scenario = make_scenario(2000, target_listing_id="X1", need_list=["test ürünü"])
    offer = buyer_turn(scenario, [ITEM], [seller], 2)
    assert offer.action == "accept" and offer.price == 100.0


def test_finalize_message_fills_placeholder():
    assert _finalize_message("Merhaba, {FIYAT} olur mu?", 760, False, 1) == "Merhaba, 760 TL olur mu?"


def test_finalize_message_appends_price_if_placeholder_missing():
    msg = _finalize_message("Merhaba, indirim yapar mısınız?", 760, False, 1)
    assert msg.endswith("Teklifim: 760 TL.")


def test_finalize_message_rejects_foreign_price():
    msg = _finalize_message("Merhaba, 500 TL olur mu? {FIYAT}", 760, False, 1)
    assert "500" not in msg and "760 TL" in msg


def test_finalize_message_allows_small_numbers():
    msg = _finalize_message("2 ürününüzü birlikte alıyorum, {FIYAT} olur mu?", 760, True, 1)
    assert msg.startswith("2 ürününüzü")


def test_mock_mode_never_calls_api(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("API çağrıldı!")
    monkeypatch.setattr(llm, "_real_message", boom)
    assert "{FIYAT}" in llm.write_message(["x"], False, 1, [])
