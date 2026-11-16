"""Ortak pazar yeri kuralları: kargo eşikleri, sepet kargosu ve paket indirimi politikası.

Kaynaklar ve Varsayımlar:
- Kargo eşikleri (250 TL / 400 TL), paylaşımlı alıcı kargosu (29,99 TL) ve
  sepette tek kargo (en büyük paketin ücreti): Dolap yardım sayfaları.
- Paket indirimi: Vinted'da satıcılar 2/3/5 ürün için kademeli indirim tanımlıyor;
  yaygın değerler %5/%10 (üçüncü taraf rehberler). Dolap'ta sepetin tamamına tek teklif veriliyor.
- Varsayım: satıcının ödediği kargo alt sınırının içinde sayılır.
"""
from __future__ import annotations

from schemas import Listing

# Paket indirimi: Vinted'da satıcılar 2/3/5 ürün için kademeli indirim tanımlıyor;
# yaygın değerler %5/%10 (üçüncü taraf rehberler). Dolap'ta sepetin tamamına tek teklif veriliyor.
# (3 ve üzeri ürün: 0.10, 2 ürün: 0.05, tek ürün: 0.0)
BUNDLE_DISCOUNT: dict[int, float] = {2: 0.05, 3: 0.10}

# Kargo eşikleri ve sepette tek kargo: Dolap yardım sayfaları.
# Varsayım: satıcının ödediği kargo alt sınırının içinde sayılır.
SHIPPING_SHARED_THRESHOLD: float = 250.0
SHIPPING_FREE_THRESHOLD: float = 400.0
SHIPPING_SHARED_BUYER: float = 29.99


def bundle_discount_rate(n_items: int) -> float:
    """Ürün sayısına göre paket indirim oranını (δ) döndürür (tek ürün: 0, 2 ürün: 0.05, 3+ ürün: 0.10)."""
    if n_items <= 1:
        return 0.0
    if n_items == 2:
        return BUNDLE_DISCOUNT[2]
    return BUNDLE_DISCOUNT[3]


def bundle_floor(items: list[Listing]) -> float:
    """Paketin indirimli toplam alt sınırı: alt sınırlar toplamı × (1 - δ)."""
    if not items:
        return 0.0
    total_floor = sum(item.floor_price for item in items)
    delta = bundle_discount_rate(len(items))
    return round(total_floor * (1.0 - delta), 2)


def package_shipping(items: list[Listing]) -> float:
    """Sepet kargosu = en büyük paketin ücreti = max(shipping_cost) (Dolap yardım sayfaları)."""
    if not items:
        return 0.0
    return max(item.shipping_cost for item in items)


def buyer_shipping(items: list[Listing], price: float) -> float:
    """Fiyata göre alıcının ödeyeceği kargo ücreti (Dolap yardım sayfaları).

    - price < 250        -> package_shipping(items)
    - 250 <= price < 400 -> 29.99 (SHIPPING_SHARED_BUYER)
    - price >= 400       -> 0.0
    """
    if not items:
        return 0.0
    if price >= SHIPPING_FREE_THRESHOLD:
        return 0.0
    if price >= SHIPPING_SHARED_THRESHOLD:
        return SHIPPING_SHARED_BUYER
    return package_shipping(items)


def max_affordable_price(items: list[Listing], budget: float) -> float:
    """Liste toplamını aşmayan, p + buyer_shipping(items, p) <= budget olan en yüksek p.

    Parçalı fonksiyon: üç bölgenin ([0, 250), [250, 400), [400, ∞)) her birinde
    en yüksek adayı dener ve koşulu sağlayan en büyük p değerini döndürür.
    """
    if not items or budget <= 0.0:
        return 0.0

    list_total = sum(item.list_price for item in items)
    pkg_ship = package_shipping(items)

    candidates: list[float] = []

    # Bölge 3: p >= 400.0 (alıcı kargosu = 0.0) -> en yüksek aday min(list_total, budget)
    cand_free = min(list_total, budget)
    if cand_free >= SHIPPING_FREE_THRESHOLD:
        candidates.append(cand_free)

    # Bölge 2: 250.0 <= p < 400.0 (alıcı kargosu = 29.99) -> en yüksek aday min(list_total, 399.99, budget - 29.99)
    cand_shared = min(list_total, SHIPPING_FREE_THRESHOLD - 0.01, budget - SHIPPING_SHARED_BUYER)
    if cand_shared >= SHIPPING_SHARED_THRESHOLD:
        candidates.append(cand_shared)

    # Bölge 1: 0.0 <= p < 250.0 (alıcı kargosu = pkg_ship) -> en yüksek aday min(list_total, 249.99, budget - pkg_ship)
    cand_full = min(list_total, SHIPPING_SHARED_THRESHOLD - 0.01, budget - pkg_ship)
    if cand_full >= 0.0:
        candidates.append(cand_full)

    valid = [
        round(p, 2)
        for p in candidates
        if round(p, 2) + buyer_shipping(items, round(p, 2)) <= budget + 1e-9
    ]
    return max(valid) if valid else 0.0
