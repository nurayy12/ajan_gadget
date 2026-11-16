from __future__ import annotations

from typing import Callable, Literal
import pytest
from schemas import Listing, Offer, Scenario
from policy import bundle_floor
import core.seller as seller_mod
from core.seller import seller_target_price
from core.engine import approve, run_negotiation


# 3 ilanlık sabit paket (Liste toplamı = 2000 TL, Ham alt sınır = 1500 TL,
# 3 ürün için bundle_floor = 1500 * 0.90 = 1350 TL, Kargo = 50 TL)
FIXED_BUNDLE: list[Listing] = [
    Listing(
        listing_id="B1",
        seller_id="SELLER_1",
        title="Deri Ceket",
        description="Siyah hakiki deri ceket",
        category="Giyim",
        size="L",
        condition="Çok İyi",
        list_price=1000.0,
        floor_price=750.0,
        shipping_cost=50.0,
    ),
    Listing(
        listing_id="B2",
        seller_id="SELLER_1",
        title="Kot Pantolon",
        description="Mavi slim fit kot pantolon",
        category="Giyim",
        size="32",
        condition="İyi",
        list_price=600.0,
        floor_price=450.0,
        shipping_cost=50.0,
    ),
    Listing(
        listing_id="B3",
        seller_id="SELLER_1",
        title="Kemer",
        description="Kahverengi deri kemer",
        category="Aksesuar",
        size=None,
        condition="Yeni Gibi",
        list_price=400.0,
        floor_price=300.0,
        shipping_cost=50.0,
    ),
]


def fake_select_bundle(
    scenario: Scenario,
    listings: list[Listing],
    mode: Literal["single", "bundle"],
) -> list[Listing]:
    """Sabit 3 ilanlık paketi (veya single modda ilk ilanı) döndürür."""
    if mode == "single":
        return [listings[0]]
    return list(listings)


def make_fake_buyer_turn(
    scripted_offers: list[Offer],
) -> Callable[[Scenario, list[Listing], list[Offer], int], Offer]:
    """
    Önceden yazılmış teklifleri sırayla gönderen sahte bir fake_buyer_turn üretir.
    """
    idx = 0

    def fake_buyer_turn(
        scenario: Scenario,
        bundle: list[Listing],
        history: list[Offer],
        round: int,
    ) -> Offer:
        nonlocal idx
        offer = scripted_offers[min(idx, len(scripted_offers) - 1)]
        idx += 1
        return Offer(
            sender="buyer",
            round=round,
            action=offer.action,
            listing_ids=[item.listing_id for item in bundle],
            price=offer.price,
            message=offer.message,
        )

    return fake_buyer_turn


@pytest.fixture(autouse=True)
def set_mock_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tüm testlerde API çağırmadan USE_MOCK_LLM=1 ile çalışmasını garanti eder."""
    monkeypatch.setenv("USE_MOCK_LLM", "1")


def test_seller_beta_and_behavioral_privacy_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    - SELLER_BETA varsayılan olarak 0.2 olmalı ve çağrı anında modülden okunmalı.
    - 5. turdaki satıcı hedef fiyatı bundle_floor * (1 + u), u ~ U(0.01, 0.03) aralığında
      ve aynı (scenario_id, mode) için tekrarlanabilir (deterministik) olmalı.
    """
    assert seller_mod.SELLER_BETA == 0.2
    eff_floor = bundle_floor(FIXED_BUNDLE)  # 1350.0

    p5_a = seller_target_price(FIXED_BUNDLE, 5, scenario_id="SC_SEED_1", mode="bundle")
    p5_b = seller_target_price(FIXED_BUNDLE, 5, scenario_id="SC_SEED_1", mode="bundle")
    assert p5_a == p5_b
    assert eff_floor * 1.01 - 1.0 <= p5_a <= eff_floor * 1.03 + 2.0
    assert p5_a > eff_floor  # Asla bundle_floor'un altına inmez

    # SELLER_BETA çalışma anında değiştirildiğinde (eval/ duyarlılık analizi) anında etkili olmalı
    p3_boulware = seller_target_price(FIXED_BUNDLE, 3, scenario_id="SC_SEED_1", mode="bundle")
    monkeypatch.setattr(seller_mod, "SELLER_BETA", 1.0)
    p3_linear = seller_target_price(FIXED_BUNDLE, 3, scenario_id="SC_SEED_1", mode="bundle")
    assert p3_linear < p3_boulware


def test_negotiation_ends_with_deal() -> None:
    """
    Senaryo 1: Anlaşmayla biten pazarlık.
    Alıcı 3. turda satıcının 3. tur hedef fiyatının üzerinde (1950 TL) teklif verir ve anlaşma sağlanır.
    """
    scenario = Scenario(
        scenario_id="SC_DEAL",
        need_list=["deri ceket", "kot pantolon", "kemer"],
        budget=1980.0,  # p >= 400 için alıcı kargosu 0 TL
        target_listing_id="B1",
    )
    scripted = [
        Offer(
            sender="buyer",
            round=1,
            action="offer",
            listing_ids=["B1", "B2", "B3"],
            price=1550.0,
            message="Merhaba, 3 ürün için 1.550 TL teklif ediyorum.",
        ),
        Offer(
            sender="buyer",
            round=2,
            action="counter",
            listing_ids=["B1", "B2", "B3"],
            price=1700.0,
            message="Fiyatı biraz artırıp 1700 TL yapabilirim.",
        ),
        Offer(
            sender="buyer",
            round=3,
            action="counter",
            listing_ids=["B1", "B2", "B3"],
            price=1955.0,
            message="Son olarak 1.955 TL verebilirim.",
        ),
    ]

    result = run_negotiation(
        scenario=scenario,
        listings=FIXED_BUNDLE,
        mode="bundle",
        auto_approve=True,
        select_bundle_fn=fake_select_bundle,
        buyer_turn_fn=make_fake_buyer_turn(scripted),
    )

    assert result.deal is True
    assert result.final_price == 1955.0
    assert result.rounds == 3
    assert result.violations == []
    assert result.offers[-1].sender == "seller"
    assert result.offers[-1].action == "accept"


def test_negotiation_no_deal_after_5_rounds() -> None:
    """
    Senaryo 2: 5 turda anlaşmasız biten pazarlık.
    Alıcı 5 tur boyunca satıcının indirimli alt sınırının (bundle_floor = 1350 TL) altında teklif verir.
    """
    scenario = Scenario(
        scenario_id="SC_NO_DEAL",
        need_list=["deri ceket", "kot pantolon", "kemer"],
        budget=1450.0,
        target_listing_id="B1",
    )
    scripted = [
        Offer(sender="buyer", round=1, action="offer", listing_ids=[], price=1100.0, message="1100 TL olur mu?"),
        Offer(sender="buyer", round=2, action="counter", listing_ids=[], price=1150.0, message="1150 TL vereyim."),
        Offer(sender="buyer", round=3, action="counter", listing_ids=[], price=1200.0, message="1200 TL teklifimdir."),
        Offer(sender="buyer", round=4, action="counter", listing_ids=[], price=1250.0, message="1250 TL yapalım."),
        Offer(sender="buyer", round=5, action="counter", listing_ids=[], price=1300.0, message="Son 1300 TL çalışır."),
    ]

    result = run_negotiation(
        scenario=scenario,
        listings=FIXED_BUNDLE,
        mode="bundle",
        auto_approve=True,
        select_bundle_fn=fake_select_bundle,
        buyer_turn_fn=make_fake_buyer_turn(scripted),
    )

    assert result.deal is False
    assert result.final_price is None
    assert result.rounds == 5
    assert len(result.offers) == 10  # 5 tur x 2 (alıcı + satıcı)


def test_negotiation_with_violations_and_approval_flow() -> None:
    """
    Senaryo 3: İhlal içeren pazarlık (ve auto_approve=False ile approve() kontrolü).
    """
    scenario = Scenario(
        scenario_id="SC_VIOLATION",
        need_list=["deri ceket", "kot pantolon", "kemer"],
        budget=2000.0,
        target_listing_id="B1",
    )
    scripted = [
        # Tur 1 - Deneme 1: 2050 > 2000 (over_budget) ve mesajda yabancı fiyat 1700 yazıyor (price_mismatch)
        Offer(
            sender="buyer",
            round=1,
            action="offer",
            listing_ids=[],
            price=2050.0,
            message="Bu paket için 1700 TL veririm.",
        ),
        # Tur 1 - Deneme 2 (Retry): Bütçe olan 2000 sayısını mesajda sızdırıyor (budget_leak)
        Offer(
            sender="buyer",
            round=1,
            action="offer",
            listing_ids=[],
            price=1700.0,
            message="Toplam bütçem 2000 TL, ürünlere 1700 TL teklif ediyorum.",
        ),
        # Tur 2 - Geçerli teklif: 1995 TL (satıcının 2. tur hedefi >= olduğu için kabul edilir)
        Offer(
            sender="buyer",
            round=2,
            action="counter",
            listing_ids=[],
            price=1995.0,
            message="Peki, paket için 1.995 TL teklif ediyorum.",
        ),
    ]

    result = run_negotiation(
        scenario=scenario,
        listings=FIXED_BUNDLE,
        mode="bundle",
        auto_approve=False,  # Demo modu: insan onayı bekler
        select_bundle_fn=fake_select_bundle,
        buyer_turn_fn=make_fake_buyer_turn(scripted),
    )

    assert "over_budget" in result.violations
    assert "price_mismatch" in result.violations
    assert "budget_leak" in result.violations

    assert result.offers[0].price == 1700.0
    assert "2000" not in result.offers[0].message

    assert result.deal is False
    assert result.final_price == 1995.0

    approved = approve(result, buyer_ok=True, seller_ok=True)
    assert approved.deal is True
    assert approved.final_price == 1995.0

    rejected = approve(result, buyer_ok=True, seller_ok=False)
    assert rejected.deal is False
    assert rejected.final_price is None


def test_trace_path_writes_jsonl(tmp_path: pytest.TempPathFactory) -> None:
    """trace_path verildiğinde her tur JSONL olarak dosyaya yazılmalı."""
    import json

    trace_file = tmp_path / "trace.jsonl"
    scenario = Scenario(
        scenario_id="SC_TRACE",
        need_list=["deri ceket"],
        budget=2000.0,
        target_listing_id="B1",
    )
    scripted = [
        Offer(
            sender="buyer",
            round=1,
            action="offer",
            listing_ids=["B1"],
            price=1000.0,
            message="Merhaba, ceket için 1000 TL teklif ediyorum.",
        ),
    ]
    result = run_negotiation(
        scenario=scenario,
        listings=FIXED_BUNDLE,
        mode="single",
        auto_approve=True,
        select_bundle_fn=fake_select_bundle,
        buyer_turn_fn=make_fake_buyer_turn(scripted),
        trace_path=trace_file,
    )
    assert result.deal is True
    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first_rec = json.loads(lines[0])
    assert set(first_rec.keys()) == {"round", "sender", "price", "message", "violations"}
    assert first_rec["sender"] == "buyer"


def test_llm_retry_and_fallback_records_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 3 denemede de hata verdiğinde şablona düşmeli ve violations'a 'llm_error' yazılmalı."""
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    monkeypatch.setattr(seller_mod, "LLM_BACKOFF_BASE", 0.0)

    call_count = 0

    class FailingMessages:
        def create(self, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Simüle edilmiş API zaman aşımı / bağlantı hatası")

    class FailingClient:
        def __init__(self, **kwargs):
            self.messages = FailingMessages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", FailingClient)

    scenario = Scenario(
        scenario_id="SC_LLM_ERR",
        need_list=["deri ceket"],
        budget=2000.0,
        target_listing_id="B1",
    )
    scripted = [
        Offer(
            sender="buyer",
            round=1,
            action="offer",
            listing_ids=["B1"],
            price=1000.0,
            message="Ceket için 1000 TL veririm.",
        ),
    ]
    result = run_negotiation(
        scenario=scenario,
        listings=FIXED_BUNDLE,
        mode="single",
        auto_approve=True,
        select_bundle_fn=fake_select_bundle,
        buyer_turn_fn=make_fake_buyer_turn(scripted),
    )

    assert call_count == 3  # Tam 3 kez yeniden denemiş olmalı
    assert "llm_error" in result.violations
    assert result.deal is True
    assert "1000" in result.offers[-1].message
