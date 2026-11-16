from __future__ import annotations

import pytest
from schemas import Listing, Offer, Scenario
from policy import bundle_floor
from core.rules import bundle_shipping_cost, check, extract_numbers


@pytest.fixture
def sample_bundle() -> list[Listing]:
    return [
        Listing(
            listing_id="L1",
            seller_id="S1",
            title="Kot Ceket",
            description="Az kullanılmış mavi kot ceket",
            category="Giyim",
            size="M",
            condition="İyi",
            list_price=800.0,
            floor_price=600.0,
            shipping_cost=50.0,
        ),
        Listing(
            listing_id="L2",
            seller_id="S1",
            title="Beyaz Sneaker",
            description="Temiz spor ayakkabı",
            category="Ayakkabı",
            size="40",
            condition="Çok İyi",
            list_price=700.0,
            floor_price=500.0,
            shipping_cost=65.0,
        ),
    ]
    # Toplam liste = 1500.0, Ham alt sınır toplamı = 1100.0
    # 2 ürün için indirimli paket alt sınırı: bundle_floor = 1100 * (1 - 0.05) = 1045.0
    # Sepet kargosu (package_shipping) = max(50, 65) = 65.0


@pytest.fixture
def sample_scenario() -> Scenario:
    return Scenario(
        scenario_id="SC_TEST_1",
        need_list=["kot ceket", "spor ayakkabı"],
        budget=1350.0,  # p >= 400 için alıcı kargosu 0 TL -> en fazla 1350.0 TL
        target_listing_id="L1",
    )


def test_extract_numbers_turkish_formats() -> None:
    text = "Fiyat 1.250 TL, alternatif 1250 veya 1250,00 ya da 1.250,50 TL olabilir."
    nums = extract_numbers(text)
    assert nums == [1250.0, 1250.0, 1250.0, 1250.5]


def test_bundle_shipping_cost_wrapper_delegates_to_package_shipping(sample_bundle: list[Listing]) -> None:
    assert bundle_shipping_cost(sample_bundle) == 65.0


# --- 1. KURAL: over_budget (buyer_shipping ile) ---
def test_rule_over_budget_pass(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    # 1250 >= 400 olduğu için buyer_shipping = 0 TL; 1250 + 0 <= 1350 -> İhlal yok
    offer = Offer(
        sender="buyer",
        round=1,
        action="offer",
        listing_ids=["L1", "L2"],
        price=1250.0,
        message="Merhaba, iki ürün için 1.250 TL teklif ediyorum.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "over_budget" not in violations
    assert violations == []


def test_rule_over_budget_fail_with_tiered_shipping(sample_bundle: list[Listing]) -> None:
    # Bütçe 360 TL, alıcı 340 TL teklif ediyor (250 <= 340 < 400 -> buyer_shipping = 29.99 TL)
    # 340 + 29.99 = 369.99 > 360 -> over_budget!
    scenario = Scenario(
        scenario_id="SC_SHIP_TIER",
        need_list=["kot ceket"],
        budget=360.0,
        target_listing_id="L1",
    )
    offer = Offer(
        sender="buyer",
        round=1,
        action="offer",
        listing_ids=["L1"],
        price=340.0,
        message="Bu ürün için 340 TL verebilirim.",
    )
    violations = check(offer, scenario, sample_bundle[:1], [])
    assert "over_budget" in violations


# --- 2. KURAL: below_floor (bundle_floor ile) ---
def test_rule_below_floor_pass_with_bundle_discount(
    sample_bundle: list[Listing], sample_scenario: Scenario
) -> None:
    # Ham alt sınır toplamı 1100 ama 2 ürünlü bundle_floor = 1045.0 TL.
    # Satıcı 1060 TL teklif ettiğinde (1045 <= 1060 < 1100) yeni kurala göre İHLAL YOK!
    assert bundle_floor(sample_bundle) == 1045.0
    offer = Offer(
        sender="seller",
        round=4,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1060.0,
        message="İki ürün paket olarak 1.060,00 TL yapabilirim.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "below_floor" not in violations
    assert violations == []


def test_rule_below_floor_fail(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    # Satıcı teklifi 1030 < 1045 (bundle_floor) -> below_floor
    offer = Offer(
        sender="seller",
        round=4,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1030.0,
        message="Sizin için 1030 TL olur.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "below_floor" in violations


# --- 3. KURAL: round_limit ---
def test_rule_round_limit_pass(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    offer = Offer(
        sender="buyer",
        round=5,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1200.0,
        message="Son turda 1200 TL teklif ediyorum.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "round_limit" not in violations
    assert violations == []


def test_rule_round_limit_fail(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    offer = Offer(
        sender="buyer",
        round=6,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1200.0,
        message="Altıncı turda 1200 TL teklif ediyorum.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "round_limit" in violations


# --- 4. KURAL: price_mismatch (ve gevşetilmiş liste/kargo sayıları) ---
def test_rule_price_mismatch_pass(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    offer = Offer(
        sender="seller",
        round=1,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1400.0,
        message="Paket olarak 1.400 TL olur.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "price_mismatch" not in violations
    assert violations == []


def test_rule_price_mismatch_relaxed_allows_list_and_shipping_prices(
    sample_bundle: list[Listing], sample_scenario: Scenario
) -> None:
    """Mesajda teklif fiyatının yanında liste toplamı (1500), tekil liste fiyatı (800, 700)
    veya kargo (65 / 29,99) geçmesi (±1 TL) price_mismatch sayılmamalı."""
    offer = Offer(
        sender="seller",
        round=1,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1380.0,
        message="Ceket 800 TL, ayakkabı 700 TL (toplam 1.500 TL) ve kargo 65 TL ama size 1.380 TL olur.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "price_mismatch" not in violations
    assert violations == []


def test_rule_price_mismatch_fail(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    offer = Offer(
        sender="seller",
        round=1,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1400.0,
        message="Paket olarak 1.300 TL olur.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "price_mismatch" in violations


# --- 5. KURAL: floor_leak (tekil floor, toplam floor ve bundle_floor) ---
def test_rule_floor_leak_pass(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    offer = Offer(
        sender="seller",
        round=2,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1300.0,
        message="Bu iki temiz ürün için 1300 TL son teklifimdir.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "floor_leak" not in violations
    assert violations == []


def test_rule_floor_leak_fail_total_single_and_bundle_floor(
    sample_bundle: list[Listing], sample_scenario: Scenario
) -> None:
    # 1) Ham toplam alt sınır (1100 TL)
    offer_total = Offer(
        sender="seller",
        round=2,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1300.0,
        message="Normalde alt sınırımız 1.100 TL ama size 1300 TL yaparım.",
    )
    assert "floor_leak" in check(offer_total, sample_scenario, sample_bundle, [])

    # 2) Tekil alt sınır (600 TL)
    offer_single = Offer(
        sender="seller",
        round=2,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1300.0,
        message="Ceketin en alt fiyatı 600,00 TL, paket olarak 1300 TL olur.",
    )
    assert "floor_leak" in check(offer_single, sample_scenario, sample_bundle, [])

    # 3) İndirimli paket alt sınırı (bundle_floor = 1045 TL)
    offer_bundle_floor = Offer(
        sender="seller",
        round=2,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1300.0,
        message="Paket indirimli tabanım 1.045 TL, size 1300 TL olur.",
    )
    assert "floor_leak" in check(offer_bundle_floor, sample_scenario, sample_bundle, [])


# --- 6. KURAL: budget_leak ---
def test_rule_budget_leak_pass(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    offer = Offer(
        sender="buyer",
        round=1,
        action="offer",
        listing_ids=["L1", "L2"],
        price=1200.0,
        message="Merhaba, ikisini 1.200 TL'ye alabilirim.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "budget_leak" not in violations
    assert violations == []


def test_rule_budget_leak_fail(sample_bundle: list[Listing], sample_scenario: Scenario) -> None:
    offer = Offer(
        sender="buyer",
        round=1,
        action="offer",
        listing_ids=["L1", "L2"],
        price=1200.0,
        message="Toplam bütçem 1.350 TL ama kargo hariç 1200 TL teklif ediyorum.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "budget_leak" in violations


# --- ZOR DURUM TESTLERİ (EDGE CASES) ---

@pytest.mark.parametrize(
    "formatted_text",
    [
        "Bu paket için teklifim 1.250 TL.",
        "Bu paket için teklifim 1250₺.",
        "Bu paket için teklifim 1250,00 lira.",
    ],
)
def test_edge_price_currency_formats(
    formatted_text: str, sample_bundle: list[Listing], sample_scenario: Scenario
) -> None:
    """Fiyatın '1.250 TL', '1250₺', '1250,00 lira' biçimlerinde yazılması ihlalsiz geçmeli."""
    offer = Offer(
        sender="buyer",
        round=1,
        action="offer",
        listing_ids=["L1", "L2"],
        price=1250.0,
        message=formatted_text,
    )
    assert check(offer, sample_scenario, sample_bundle, []) == []


def test_edge_two_different_prices_in_message(
    sample_bundle: list[Listing], sample_scenario: Scenario
) -> None:
    """Mesajda liste/kargo dışı iki farklı fiyat geçmesi (örn. 1400 ve 1250) price_mismatch olarak yakalanmalı."""
    offer = Offer(
        sender="buyer",
        round=2,
        action="counter",
        listing_ids=["L1", "L2"],
        price=1250.0,
        message="Önce 1400 TL düşünmüştüm ama şimdi 1.250 TL teklif ediyorum.",
    )
    violations = check(offer, sample_scenario, sample_bundle, [])
    assert "price_mismatch" in violations


def test_edge_floor_as_substring_of_larger_number_not_a_leak() -> None:
    """Alt sınır 250 iken mesajda 1250 yazması floor_leak sayılmamalı."""
    bundle = [
        Listing(
            listing_id="L_SUB",
            seller_id="S1",
            title="Ceket",
            description="Temiz ceket",
            category="Giyim",
            size="M",
            condition="İyi",
            list_price=1500.0,
            floor_price=250.0,
            shipping_cost=40.0,
        )
    ]
    scenario = Scenario(
        scenario_id="SC_SUB",
        need_list=["ceket"],
        budget=1600.0,
        target_listing_id="L_SUB",
    )
    offer = Offer(
        sender="seller",
        round=1,
        action="counter",
        listing_ids=["L_SUB"],
        price=1250.0,
        message="Bu ürün için 1250 TL yapabilirim.",
    )
    violations = check(offer, scenario, bundle, [])
    assert "floor_leak" not in violations
    assert violations == []
