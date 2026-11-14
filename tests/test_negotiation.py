from __future__ import annotations

import os
from typing import Callable, Literal
import pytest
from schemas import Listing, Offer, Scenario
from core.engine import approve, run_negotiation


# 3 ilanlık sabit paket (Liste toplamı = 2000 TL, Alt sınır toplamı = 1500 TL, Kargo = 50 TL)
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
    (Retry durumunda da sıradaki teklifi verir; liste biterse son teklifi tekrarlar.)
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


def test_negotiation_ends_with_deal() -> None:
    """
    Senaryo 1: Anlaşmayla biten pazarlık.
    3 ilanlık paket: Liste = 2000, Alt sınır = 1500.
    Satıcı hedef fiyatları (beta=0.5, T=5):
      Tur 1: 2000 + (1500 - 2000) * (1/5)^2 = 1980 TL
      Tur 2: 2000 + (1500 - 2000) * (2/5)^2 = 1920 TL
      Tur 3: 2000 + (1500 - 2000) * (3/5)^2 = 1820 TL
    Alıcı 3. turda 1850 TL teklif eder (1850 >= 1820 olduğu için satıcı kabul eder).
    """
    scenario = Scenario(
        scenario_id="SC_DEAL",
        need_list=["deri ceket", "kot pantolon", "kemer"],
        budget=1950.0,  # Kargo (50) dahil -> ürünlere en fazla 1900 TL
        target_listing_id="B1",
    )
    scripted = [
        Offer(
            sender="buyer",
            round=1,
            action="offer",
            listing_ids=["B1", "B2", "B3"],
            price=1600.0,
            message="Merhaba, 3 ürün için 1.600 TL teklif ediyorum.",
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
            price=1850.0,
            message="Son olarak 1.850 TL verebilirim.",
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
    assert result.final_price == 1850.0
    assert result.rounds == 3
    assert result.violations == []
    assert result.offers[-1].sender == "seller"
    assert result.offers[-1].action == "accept"


def test_negotiation_no_deal_after_5_rounds() -> None:
    """
    Senaryo 2: 5 turda anlaşmasız biten pazarlık.
    Alıcı 5 tur boyunca satıcının hedef fiyatlarının altında teklif verir ve kabul etmez.
    """
    scenario = Scenario(
        scenario_id="SC_NO_DEAL",
        need_list=["deri ceket", "kot pantolon", "kemer"],
        budget=1600.0,  # Kargo 50 -> en fazla 1550
        target_listing_id="B1",
    )
    scripted = [
        Offer(sender="buyer", round=1, action="offer", listing_ids=[], price=1200.0, message="1200 TL olur mu?"),
        Offer(sender="buyer", round=2, action="counter", listing_ids=[], price=1250.0, message="1250 TL vereyim."),
        Offer(sender="buyer", round=3, action="counter", listing_ids=[], price=1300.0, message="1300 TL teklifimdir."),
        Offer(sender="buyer", round=4, action="counter", listing_ids=[], price=1350.0, message="1350 TL yapalım."),
        Offer(sender="buyer", round=5, action="counter", listing_ids=[], price=1400.0, message="Son 1400 TL çalışır."),
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
    - Tur 1'de alıcı ilk denemede hem bütçeyi aşar (over_budget) hem de mesajda farklı fiyat yazar (price_mismatch).
    - Motor ihlalleri result.violations'a kaydeder ve buyer_turn'ü yeniden çağırır.
    - İkinci denemede de bütçe sızıntısı (budget_leak) yapılınca motor sabit güvenli şablon mesaj kullanır.
    - Tur 2'de alıcı 1920 TL (satıcının Tur 2 hedefi) teklif ederek anlaşma sağlar.
    """
    scenario = Scenario(
        scenario_id="SC_VIOLATION",
        need_list=["deri ceket", "kot pantolon", "kemer"],
        budget=2000.0,  # Kargo 50 -> ürün için üst sınır 1950 TL
        target_listing_id="B1",
    )
    scripted = [
        # Tur 1 - Deneme 1: 1980 + 50 = 2030 > 2000 (over_budget) ve mesajda 1700 yazıyor (price_mismatch)
        Offer(
            sender="buyer",
            round=1,
            action="offer",
            listing_ids=[],
            price=1980.0,
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
        # Tur 2 - Geçerli teklif: 1920 TL (satıcının 2. tur hedefi 1920 TL olduğu için kabul edilir)
        Offer(
            sender="buyer",
            round=2,
            action="counter",
            listing_ids=[],
            price=1920.0,
            message="Peki, paket için 1.920 TL teklif ediyorum.",
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

    # İhlaller yakalanmış olmalı
    assert "over_budget" in result.violations
    assert "price_mismatch" in result.violations
    assert "budget_leak" in result.violations

    # İlk turdaki alıcı mesajı şablon ile temizlenmiş olmalı
    assert result.offers[0].price == 1700.0
    assert "2000" not in result.offers[0].message

    # auto_approve=False olduğu için henüz deal=False ama final_price=1920.0 hazır
    assert result.deal is False
    assert result.final_price == 1920.0

    # İnsan onayı (approve): iki taraf da onayladığında deal=True olur
    approved = approve(result, buyer_ok=True, seller_ok=True)
    assert approved.deal is True
    assert approved.final_price == 1920.0

    # Bir taraf reddederse deal=False ve final_price=None olur
    rejected = approve(result, buyer_ok=True, seller_ok=False)
    assert rejected.deal is False
    assert rejected.final_price is None
