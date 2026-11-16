import re

import pytest

from schemas import Listing, Offer
from buyer import config, llm
from buyer.agent import buyer_turn
from buyer.tactics import (ACILIS, ALL_TACTICS, DURUM, HIZLI_ODEME, KARSILIK, SON_TEKLIF, TACTIC_GUIDE,
                           TOPLU_ALIM, YUMUSATMA, choose_buyer_tactic, seller_dropped_price)
from buyer.tests.fake_seller import run_fake_negotiation
from buyer.tests.sample_data import LISTINGS, make_scenario
from buyer.text_utils import format_tl
from buyer.bundle import select_bundle

ITEM = Listing(listing_id="X1", seller_id="sx", title="Mavi kot", description="d", category="c",
               size=None, condition="az kullanılmış", list_price=1000, floor_price=800, shipping_cost=50)
ITEM2 = ITEM.model_copy(update={"listing_id": "X2", "title": "Beyaz gömlek"})
HIGH = (1500, 1450, 1400, 1350)   # satıcı hedefin hep üstünde kalır: kabul yok


def seller(round_no, price):
    return Offer(sender="seller", round=round_no, action="counter", listing_ids=["X1"], price=price, message="m")


def buyer_offer(round_no, price):
    return Offer(sender="buyer", round=round_no, action="counter", listing_ids=["X1"], price=price, message="m")


def history_until(round_no, prices=(950, 900, 880, 860)):
    h = []
    for r in range(1, round_no):
        h += [buyer_offer(r, 700), seller(r, prices[r - 1])]
    return h


def run_tactics(is_bundle, sid, prices=(950, 900, 880, 860)):
    bundle = [ITEM, ITEM2] if is_bundle else [ITEM]
    return [choose_buyer_tactic(r, is_bundle, history_until(r, prices), bundle, sid) for r in range(1, 6)]


def test_first_round_is_acilis_and_last_is_son_teklif():
    for sid in ("SC1", "SC2", "SC3"):
        seq = run_tactics(True, sid)
        assert seq[0] == ACILIS and seq[4] == SON_TEKLIF


@pytest.mark.parametrize("is_bundle", [False, True])
def test_no_tactic_repeats_back_to_back(is_bundle):
    for i in range(60):
        seq = run_tactics(is_bundle, f"SC{i}")
        assert all(a != b for a, b in zip(seq, seq[1:])), seq


def test_single_item_never_gets_toplu_alim():
    for i in range(60):
        assert TOPLU_ALIM not in run_tactics(False, f"SC{i}")


def test_bundle_can_get_toplu_alim():
    assert any(TOPLU_ALIM in run_tactics(True, f"SC{i}") for i in range(60))


def test_selection_is_deterministic_and_varies_by_scenario():
    assert run_tactics(True, "SC7") == run_tactics(True, "SC7")
    assert len({tuple(run_tactics(True, f"SC{i}")) for i in range(30)}) > 3


def test_karsilik_only_if_seller_dropped_price():
    bundle = [ITEM]
    dropped = [buyer_offer(1, 700), seller(1, 950), buyer_offer(2, 720), seller(2, 900)]
    flat = [buyer_offer(1, 700), seller(1, 950), buyer_offer(2, 720), seller(2, 950)]
    assert seller_dropped_price(dropped, bundle) is True
    assert seller_dropped_price(flat, bundle) is False
    seen_dropped = {choose_buyer_tactic(3, False, dropped, bundle, f"S{i}") for i in range(80)}
    seen_flat = {choose_buyer_tactic(3, False, flat, bundle, f"S{i}") for i in range(80)}
    assert KARSILIK in seen_dropped and KARSILIK not in seen_flat


def test_first_seller_price_below_list_counts_as_drop():
    h = [buyer_offer(1, 700), seller(1, 900)]
    assert seller_dropped_price(h, [ITEM]) is True           # liste 1000'in altında
    assert seller_dropped_price([buyer_offer(1, 700), seller(1, 1000)], [ITEM]) is False
    assert seller_dropped_price([], [ITEM]) is False


def test_last_round_follows_config_t(monkeypatch):
    monkeypatch.setattr(config, "T", 3)
    assert choose_buyer_tactic(3, False, history_until(3), [ITEM], "S") == SON_TEKLIF


# --- Şablonlar ------------------------------------------------------------------------

@pytest.mark.parametrize("tactic", ALL_TACTICS)
@pytest.mark.parametrize("is_bundle", [False, True])
def test_every_tactic_has_several_clean_templates(tactic, is_bundle):
    if tactic == TOPLU_ALIM and not is_bundle:
        return
    variants = llm._TACTIC_TEMPLATES[(tactic, is_bundle)]
    assert len(variants) >= 2
    for t in variants:
        assert llm.PLACEHOLDER in t
        assert not re.search(r"\d", t)                    # sayı yok; fiyatı kod koyar
        assert "TL" not in t and "bütçe" not in t.lower()


def test_templates_vary_across_scenarios_and_are_deterministic():
    msgs = {llm.template_message(True, 2, DURUM, f"SC{i}") for i in range(30)}
    assert len(msgs) >= 2
    assert llm.template_message(True, 2, DURUM, "SC1") == llm.template_message(True, 2, DURUM, "SC1")


def test_old_template_still_available_without_tactic():
    assert "{FIYAT}" in llm.template_message(False, 1)


def test_mock_messages_are_diverse_over_negotiations():
    scenario_msgs = set()
    for i in range(10):
        sc = make_scenario(1800)
        sc = sc.model_copy(update={"scenario_id": f"SC{i}"})
        bundle = select_bundle(sc, LISTINGS, "bundle")
        res = run_fake_negotiation(sc, bundle, "bundle")
        scenario_msgs |= {o.message for o in res.offers if o.sender == "buyer"}
    assert len(scenario_msgs) >= 12


def _son_teklif_messages(price):
    return {t.replace("{FIYAT}", format_tl(price)) for t in llm._TACTIC_TEMPLATES[(SON_TEKLIF, False)]}


def test_buyer_turn_uses_tactic_template_and_price_from_code():
    sc = make_scenario(2000, target_listing_id="X1", need_list=["test"])
    first = buyer_turn(sc, [ITEM], [], 1)
    assert format_tl(first.price) in first.message and "{FIYAT}" not in first.message
    last = buyer_turn(sc, [ITEM], history_until(5, HIGH), 5)      # mock: 5. tur = son_teklif şablonu
    assert last.message in _son_teklif_messages(last.price)


# --- LLM istemi -----------------------------------------------------------------------

def test_prompt_contains_tactic_example_and_no_budget_or_foreign_numbers():
    sc = make_scenario(2000)
    p = llm.build_prompt(["Mavi kot", "Beyaz gömlek"], True, 3, history_until(3), tactic=TOPLU_ALIM,
                         conditions=["az kullanılmış", "iyi"], seller_dropped=True)
    assert TACTIC_GUIDE[TOPLU_ALIM][0] in p and TACTIC_GUIDE[TOPLU_ALIM][1] in p
    assert "az kullanılmış" in p and "Ürün sayısı: iki" in p
    assert "Satıcı son turda fiyatını düşürdü." in p
    assert "bütçe" not in p.lower().replace("başka sayı ya da bütçe yazma", "")
    assert "2000" not in p


def test_prompt_says_seller_did_not_drop_when_flat():
    p = llm.build_prompt(["x"], False, 2, [], tactic=YUMUSATMA, seller_dropped=False)
    assert "Satıcı son turda fiyatını düşürmedi." in p and "(henüz konuşma yok)" in p


def test_prompt_marks_last_round():
    assert "(son tur)" in llm.build_prompt(["x"], False, 5, [], tactic=SON_TEKLIF, last_round=True)


def test_bad_llm_message_falls_back_to_that_tactics_template(monkeypatch):
    monkeypatch.delenv("USE_MOCK_LLM", raising=False)
    monkeypatch.setattr(llm, "_real_message", lambda *a, **k: "Merhaba, 500 TL olur mu? {FIYAT}")
    sc = make_scenario(2000, target_listing_id="X1", need_list=["test"])
    offer = buyer_turn(sc, [ITEM], history_until(5, HIGH), 5)
    assert "500" not in offer.message
    assert offer.message in _son_teklif_messages(offer.price)


@pytest.mark.parametrize("condition", ["yeni etiketli", "yeni gibi"])
def test_new_items_never_get_durum(condition):
    new_item = ITEM.model_copy(update={"condition": condition})
    for bundle in ([new_item], [ITEM, new_item]):
        for i in range(30):
            seq = [choose_buyer_tactic(r, len(bundle) > 1, history_until(r), bundle, f"SC{i}")
                   for r in range(1, 6)]
            assert DURUM not in seq


def test_used_items_can_get_durum():
    seqs = [run_tactics(False, f"SC{i}") for i in range(30)]
    assert any(DURUM in s for s in seqs)
