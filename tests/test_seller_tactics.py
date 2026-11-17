"""Satıcının strateji tabanlı mesajları: strateji seçimi, şablon çeşitliliği, prompt içeriği.

Dayanak: Zhou ve ark. (2019) pazarlık stratejileri (DialoGraph, Joshi ve ark., ICLR 2021);
strateji ile metni ayırma: He ve ark. (EMNLP 2018).
"""
import pytest

import core.seller as seller_mod
from core.rules import check, extract_numbers
from core.seller import (SELLER_TACTICS, _build_seller_prompt, choose_seller_tactic,
                         generate_seller_message)
from schemas import Listing, Offer, Scenario


def _item(lid: str, price: float = 1000.0) -> Listing:
    return Listing(listing_id=lid, seller_id="s1", title=f"Marka ürün {lid}",
                   description="Orijinal, kutusunda. Bir kez kullanıldı.", category="ayakkabı",
                   size="38", condition="az kullanılmış", list_price=price,
                   floor_price=0.75 * price, shipping_cost=135.99)


SINGLE = [_item("A")]
BUNDLE = [_item("A"), _item("B", 500.0)]


def _history(buyer_prices: list[float]) -> list[Offer]:
    """Alıcı ve satıcı tekliflerini sırayla dizer (alıcının son teklifi en sonda)."""
    history = []
    for r, p in enumerate(buyer_prices, start=1):
        history.append(Offer(sender="buyer", round=r, action="counter", listing_ids=["A"],
                             price=p, message=f"{p} TL"))
        if r < len(buyer_prices):
            history.append(Offer(sender="seller", round=r, action="counter", listing_ids=["A"],
                                 price=1000.0, message="1000 TL"))
    return history


def test_fixed_tactics_for_first_last_and_accept():
    assert choose_seller_tactic(SINGLE, _history([700]), 1) == "urun_tanit"
    assert choose_seller_tactic(SINGLE, _history([700] * 5), 5) == "son_fiyat"
    assert choose_seller_tactic(SINGLE, _history([700]), 3, action="accept") == "kabul"


def test_tactic_never_repeats_in_consecutive_rounds():
    for bundle in (SINGLE, BUNDLE):
        for prices in ([700, 750, 800, 850, 900], [700, 700, 700, 700, 700]):
            tactics = [choose_seller_tactic(bundle, _history(prices[:r]), r) for r in range(1, 6)]
            assert all(a != b for a, b in zip(tactics, tactics[1:])), tactics


def test_tactic_choice_is_reproducible():
    h = _history([700, 760, 820])
    assert choose_seller_tactic(BUNDLE, h, 3) == choose_seller_tactic(BUNDLE, h, 3)


def test_reciprocity_only_offered_when_buyer_raised():
    flat = {choose_seller_tactic(SINGLE, _history([700] * r), r) for r in range(2, 5)}
    assert "karsilik" not in flat


def test_templates_have_only_the_price_number_and_pass_rules(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    scenario = Scenario(scenario_id="T", need_list=["x"], budget=5000.0, target_listing_id="A")
    for bundle in (SINGLE, BUNDLE):
        for tactic, spec in SELLER_TACTICS.items():
            for template in spec["sablonlar"] + spec.get("sablonlar_paket", []):
                msg = seller_mod._fill_template(template, bundle, "1.234,50")
                assert extract_numbers(msg) == [1234.5], msg
                offer = Offer(sender="seller", round=2, action="counter",
                              listing_ids=[l.listing_id for l in bundle], price=1234.5, message=msg)
                assert check(offer, scenario, bundle, []) == [], msg


def test_mock_messages_vary_across_rounds(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    prices = [700, 760, 820, 880, 940]
    msgs = [generate_seller_message(BUNDLE, _history(prices[:r]), 1000.0, "counter", round=r)
            for r in range(1, 6)]
    assert len(set(msgs)) == 5


def test_prompt_contains_strategy_and_description_but_never_floor():
    prompt = _build_seller_prompt(BUNDLE, [], 1200.0, "counter", "kaygi_gider")
    assert SELLER_TACTICS["kaygi_gider"]["aciklama"] in prompt
    assert "Orijinal, kutusunda" in prompt
    for item in BUNDLE:
        assert f"{item.floor_price:.0f}" not in prompt


def test_placeholder_leak_rule():
    scenario = Scenario(scenario_id="T", need_list=["x"], budget=5000.0, target_listing_id="A")
    leak = Offer(sender="buyer", round=1, action="offer", listing_ids=["A"], price=700.0,
                 message="Fiyatı: FIYAT. Teklifim 700 TL")
    natural = Offer(sender="buyer", round=1, action="offer", listing_ids=["A"], price=700.0,
                    message="Bu fiyat biraz yüksek, 700 TL olur mu?")
    assert "placeholder_leak" in check(leak, scenario, SINGLE, [])
    assert "placeholder_leak" not in check(natural, scenario, SINGLE, [])


def test_seller_does_not_call_own_products_yours():
    from core.seller import _fix_seller_perspective
    msg = "Merhaba, ürünleriniz gerçekten çok güzel. Ürününüzün durumu iyi, 2.472 TL olur."
    fixed = _fix_seller_perspective(msg, "counter")
    assert "ürünleriniz" not in fixed.lower() and "ürününüz" not in fixed.lower()
    assert fixed == "Merhaba, ürünlerim gerçekten çok güzel. Ürünümün durumu iyi, 2.472 TL olur."
    # Kabulde "ürünlerinizi kargoya veririm" doğru kullanım, dokunulmaz.
    ok = "Anlaştık, ürünlerinizi yarın kargoya veririm."
    assert _fix_seller_perspective(ok, "accept") == ok


def test_seller_prompt_tells_perspective():
    from core.seller import _build_seller_prompt
    from schemas import Listing
    item = Listing(listing_id="X", seller_id="s", title="Ceket", description="Temiz.", category="erkek giyim",
                   size="M", condition="iyi", list_price=500.0, floor_price=400.0, shipping_cost=39.99)
    assert "asla 'ürünleriniz'" in _build_seller_prompt([item], [], 480.0, "counter")


def test_greeting_only_in_first_round():
    from core.seller import strip_greeting
    from buyer.llm import strip_greeting as buyer_strip
    for fn in (strip_greeting, buyer_strip):
        assert fn("Merhaba, 2.472 TL olur.", 1) == "Merhaba, 2.472 TL olur."
        assert fn("Merhaba, ürünler çok temiz. 2.472 TL olur.", 3) == "Ürünler çok temiz. 2.472 TL olur."
        assert fn("Merhaba! biraz daha esneyebilirim.", 2) == "Biraz daha esneyebilirim."
        assert fn("Selamlar, {FIYAT} olur mu?", 2) == "{FIYAT} olur mu?"
        assert fn("Merhabalar", 2) == "Merhabalar"          # yalnızca selamsa dokunma
        assert fn("Ürün güzel, merhaba diyeyim.", 2) == "Ürün güzel, merhaba diyeyim."


def test_prompts_say_no_greeting_after_first_round():
    from core.seller import _build_seller_prompt
    from buyer.llm import build_prompt
    from schemas import Listing
    item = Listing(listing_id="X", seller_id="s", title="Ceket", description="Temiz.", category="erkek giyim",
                   size="M", condition="iyi", list_price=500.0, floor_price=400.0, shipping_cost=39.99)
    assert "selamla başlama" in _build_seller_prompt([item], [], 480.0, "counter", None, 3)
    assert "selamla başlayabilirsin" in _build_seller_prompt([item], [], 480.0, "counter", None, 1)
    assert "selamla başlama" in build_prompt(["Ceket"], False, 2, [])
