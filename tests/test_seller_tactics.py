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
    assert "Asla 'ürünleriniz'" in _build_seller_prompt([item], [], 480.0, "counter")


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


def test_buyer_drops_echoed_instruction_lines():
    from buyer.llm import strip_meta_lines
    raw = ("Anlaşırsak hemen satın alacağını söyleyerek satıcıya yazacağın mesaj:\n"
           "{FIYAT} üzerinden anlaşırsak ödemeyi hemen yapar, satın alırım.")
    assert strip_meta_lines(raw) == "{FIYAT} üzerinden anlaşırsak ödemeyi hemen yapar, satın alırım."
    assert strip_meta_lines('"Merhaba, {FIYAT} olur mu?"') == "Merhaba, {FIYAT} olur mu?"
    assert strip_meta_lines("Tek satır: {FIYAT} olur mu?") == "Tek satır: {FIYAT} olur mu?"


def _item(lid="X", title="Vintage deri evrak çantası", condition="iyi", desc="Bir kampta kullanıldı, 40 litre."):
    from schemas import Listing
    return Listing(listing_id=lid, seller_id="s", title=title, description=desc, category="çanta",
                   size=None, condition=condition, list_price=1600.0, floor_price=1200.0, shipping_cost=135.99)


def test_quality_gate_catches_demo_problems():
    from core.seller import seller_message_problem
    from schemas import Offer
    b = [_item()]
    ok = "Çantam iyi durumda, 1.500 TL yapabilirim."
    assert seller_message_problem(ok, b, [], 2, "counter") is None
    assert seller_message_problem("", b, [], 2, "counter") == "bos"
    assert seller_message_problem("Hepsiburada üzerinden takip numarasını iletirim.", b, [], 2, "counter") == "firma"
    assert seller_message_problem("Çanta yeni gibi, 1.500 TL.", b, [], 2, "counter") == "durum"
    assert seller_message_problem("Çanta yeni gibi.", [_item(condition="yeni gibi")], [], 2, "counter") is None
    assert seller_message_problem("Evrak çantanız için 1.500 TL.", b, [], 2, "counter") == "bakis_acisi"
    assert seller_message_problem("Anlaştık, çantanızı yarın kargoya veririm.", b, [], 5, "accept") is None
    assert seller_message_problem("Bu son teklifim: 1.500 TL.", b, [], 3, "counter") == "son_teklif"
    assert seller_message_problem("Bu son teklifim: 1.500 TL.", b, [], 5, "counter") is None
    prev = Offer(sender="seller", round=2, action="counter", listing_ids=["X"], price=1596.0,
                 message="Çantamın durumu gerçekten çok iyi. 1.596 TL'ye düşebilirim, rahat olabilirsiniz.")
    again = "Çantamın durumu gerçekten çok iyi. 1.569 TL'ye düşebilirim, rahat olabilirsiniz."
    assert seller_message_problem(again, b, [prev], 3, "counter") == "tekrar"


def test_polish_fixes_common_mistakes():
    from core.seller import polish_seller_message
    assert polish_seller_message("Siz için ürünlerimizi 1.500 TL'ye veririz, rica ederiz.") == \
        "Sizin için ürünlerimi 1.500 TL'ye veririz, rica ederim."


def test_seller_prompt_has_round_and_rules():
    from core.seller import _build_seller_prompt
    p = _build_seller_prompt([_item()], [], 1500.0, "counter", None, 3)
    assert "Bu 3. tur (toplam 5)" in p and "kullanma, pazarlık sürüyor" in p
    assert "kargo firması adı yazma" in p and "'biz' deme" in p
    assert "1200" not in p and "1.200" not in p   # alt sınır sızmaz


def test_listing_numbers_are_not_price_mismatch():
    from core.rules import check
    from schemas import Offer, Scenario
    b = [_item()]
    sc = Scenario(scenario_id="S", need_list=["çanta"], budget=3000.0, target_listing_id="X")
    offer = Offer(sender="seller", round=2, action="counter", listing_ids=["X"], price=1500.0,
                  message="40 litrelik çantam çok kullanışlı, 1.500 TL yapabilirim.")
    assert "price_mismatch" not in check(offer, sc, b, [])
    wrong = offer.model_copy(update={"message": "1.500 TL yapabilirim, normalde 1.700 TL."})
    assert "price_mismatch" in check(wrong, sc, b, [])


def test_engine_fallback_is_not_paket_for_single_item():
    from core.engine import _sanitize_offer_with_template
    from schemas import Offer, Scenario
    b = [_item()]
    sc = Scenario(scenario_id="S", need_list=["çanta"], budget=3000.0, target_listing_id="X")
    bad = Offer(sender="seller", round=2, action="counter", listing_ids=["X"], price=1500.0, message="x 9999 TL")
    msg = _sanitize_offer_with_template(bad, sc, b, []).message
    assert "paket" not in msg.lower() and not msg.lower().startswith("merhaba") and "1.500" in msg
    buyer = Offer(sender="buyer", round=3, action="counter", listing_ids=["X"], price=1300.0, message="x")
    assert _sanitize_offer_with_template(buyer, sc, b, []).message == "Bu ürün için teklifim 1.300 TL."


def test_buyer_quality_gate():
    from buyer.llm import buyer_message_problem
    from schemas import Offer
    t = ["Vintage deri evrak çantası"]
    assert buyer_message_problem("Çantanızı çok beğendim, {FIYAT} olur mu?", t, 2, []) is None
    assert buyer_message_problem("", t, 2, []) == "bos"
    assert buyer_message_problem("Trendyol'da daha ucuz, {FIYAT} olur mu?", t, 2, []) == "firma"
    assert buyer_message_problem("Bütçem kısıtlı, {FIYAT} olur mu?", t, 2, []) == "butce"
    assert buyer_message_problem("Çantamı hemen almak istiyorum, {FIYAT}.", t, 2, []) == "bakis_acisi"
    assert buyer_message_problem("Ürünlerim için {FIYAT} veririm.", t, 2, []) == "bakis_acisi"
    assert buyer_message_problem("Ürününüz için {FIYAT} veririm.", t, 2, []) is None
    assert buyer_message_problem("Bu son teklifim: {FIYAT}.", t, 3, []) == "son_teklif"
    assert buyer_message_problem("Bu son teklifim: {FIYAT}.", t, 5, [], last_round=True) is None
    prev = Offer(sender="buyer", round=2, action="counter", listing_ids=["X"], price=1200.0,
                 message="Biraz daha yaklaşabilirsek anlaşmaya hazırım; 1.200,00 TL olur mu?")
    assert buyer_message_problem("Biraz daha yaklaşabilirsek anlaşmaya hazırım; {FIYAT} olur mu?",
                                 t, 3, [prev]) == "tekrar"


def test_buyer_falls_back_to_template_after_two_bad_messages(monkeypatch):
    import sys, types
    import buyer.llm as bl
    replies = iter(["Trendyol'da gördüm, {FIYAT}.", "Bütçem az, {FIYAT}."])

    class Msgs:
        def create(self, **k):
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=next(replies))])

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda *a, **k: types.SimpleNamespace(messages=Msgs())))
    monkeypatch.delenv("USE_MOCK_LLM", raising=False)
    msg = bl.write_message(["Vintage deri evrak çantası"], False, 3, [], tactic="yumusatma", scenario_id="S")
    assert msg in bl._TACTIC_TEMPLATES[("yumusatma", False)]
