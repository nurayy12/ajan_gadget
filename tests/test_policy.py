"""policy.py birim ve sınır değeri testleri."""
from __future__ import annotations

import pytest
from schemas import Listing
from policy import (
    BUNDLE_DISCOUNT,
    SHIPPING_FREE_THRESHOLD,
    SHIPPING_SHARED_BUYER,
    SHIPPING_SHARED_THRESHOLD,
    bundle_discount_rate,
    bundle_floor,
    buyer_shipping,
    max_affordable_price,
    package_shipping,
)


def _make_item(lid: str, list_p: float, floor_p: float, ship: float) -> Listing:
    return Listing(
        listing_id=lid,
        seller_id="S1",
        title=f"Ürün {lid}",
        description="Açıklama",
        category="Giyim",
        size="M",
        condition="iyi",
        list_price=list_p,
        floor_price=floor_p,
        shipping_cost=ship,
    )


def test_bundle_discount_rate_and_floor() -> None:
    i1 = _make_item("1", 300.0, 200.0, 45.0)
    i2 = _make_item("2", 300.0, 200.0, 65.0)
    i3 = _make_item("3", 300.0, 200.0, 50.0)
    i4 = _make_item("4", 300.0, 200.0, 40.0)

    assert bundle_discount_rate(0) == 0.0
    assert bundle_discount_rate(1) == 0.0
    assert bundle_discount_rate(2) == BUNDLE_DISCOUNT[2] == 0.05
    assert bundle_discount_rate(3) == BUNDLE_DISCOUNT[3] == 0.10
    assert bundle_discount_rate(4) == 0.10

    assert bundle_floor([i1]) == 200.0
    assert bundle_floor([i1, i2]) == round(400.0 * 0.95, 2)  # 380.0
    assert bundle_floor([i1, i2, i3]) == round(600.0 * 0.90, 2)  # 540.0
    assert bundle_floor([i1, i2, i3, i4]) == round(800.0 * 0.90, 2)  # 720.0


def test_package_and_buyer_shipping_boundaries() -> None:
    """Sınır değerleri testi: 249,99 / 250 / 399,99 / 400 TL."""
    items = [
        _make_item("1", 300.0, 200.0, 39.90),
        _make_item("2", 300.0, 200.0, 69.90),
    ]
    assert package_shipping(items) == 69.90
    assert SHIPPING_SHARED_THRESHOLD == 250.0
    assert SHIPPING_FREE_THRESHOLD == 400.0

    # 249.99 -> tam paket kargosu (69.90)
    assert buyer_shipping(items, 249.99) == 69.90
    # 250.00 -> paylaşımlı kargo (29.99)
    assert buyer_shipping(items, 250.00) == SHIPPING_SHARED_BUYER
    # 399.99 -> paylaşımlı kargo (29.99)
    assert buyer_shipping(items, 399.99) == SHIPPING_SHARED_BUYER
    # 400.00 -> ücretsiz kargo (0.0)
    assert buyer_shipping(items, 400.00) == 0.0


def test_max_affordable_price_three_regions() -> None:
    """max_affordable_price için üç fiyat bölgesinin ([0, 250), [250, 400), [400, ∞)) testi."""
    items = [_make_item("1", 600.0, 420.0, 60.0)]  # liste = 600, kargo = 60

    # Bölge 1 (p < 250, kargo = 60): Bütçe = 260 -> p=250 olsa 250+29.99=279.99 > 260 (yetmez)
    # Dolayısıyla Bölge 1'de p = 260 - 60 = 200.0 olmalı (200 + 60 = 260 <= 260)
    p1 = max_affordable_price(items, 260.0)
    assert p1 == 200.0
    assert p1 + buyer_shipping(items, p1) <= 260.0

    # Bölge 2 (250 <= p < 400, kargo = 29.99): Bütçe = 350 -> p = 350 - 29.99 = 320.01
    p2 = max_affordable_price(items, 350.0)
    assert p2 == 320.01
    assert p2 + buyer_shipping(items, p2) == pytest.approx(350.0)

    # Bölge 2 ile Bölge 3 eşiği: Bütçe = 410 -> p=410 için kargo=0 (410 + 0 <= 410), Bölge 3 kazanır!
    p3 = max_affordable_price(items, 410.0)
    assert p3 == 410.0
    assert buyer_shipping(items, p3) == 0.0

    # Liste toplamı üst sınırı: Bütçe = 1000 -> liste toplamı 600.0 olduğu için 600.0 döner
    p_cap = max_affordable_price(items, 1000.0)
    assert p_cap == 600.0
