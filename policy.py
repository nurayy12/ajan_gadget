"""Ortak pazar yeri kuralları: kargo eşikleri, sepet kargosu ve paket indirimi politikası.

Kaynaklar:
- Kargo eşikleri (250 TL / 400 TL), paylaşımlı alıcı kargosu (29,99 TL) ve
  aynı satıcıdan sepette tek kargo (en büyük paketin ücreti): Dolap Yardım Sayfaları
  (https://destek.dolap.com/).
- Çoklu ürün paket indirimi kademeleri (2 ürün %5, 3+ ürün %10): Vinted satıcı paket
  indirimi (bundle discount) yapısı (Vinted'da satıcılar 2/3/5 ürün için kademeli
  indirim tanımlar).
"""
from __future__ import annotations

from schemas import Listing

# Paket indirimi oranları (Kaynak: Vinted'da satıcılar 2/3/5 ürün için kademeli paket indirimi tanımlar)
BUNDLE_DISCOUNT: dict[int, float] = {2: 0.05, 3: 0.10}

# Kargo eşikleri ve paylaşımlı kargo ücreti (Kaynak: Dolap yardım sayfaları - sepet tutarına göre kargo)
SHIPPING_SHARED_THRESHOLD: float = 250.0
SHIPPING_FREE_THRESHOLD: float = 400.0
SHIPPING_SHARED_BUYER: float = 29.99


def bundle_discount_rate(n_items: int) -> float:
    """Ürün sayısına göre paket indirim oranını (δ) döndürür.

    Tek ürün (<=1): 0.0, 2 ürün: 0.05 (%5), 3 ve üzeri ürün: 0.10 (%10).
    """
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
    """Sepet kargosu = en büyük paketin ücreti = max(shipping_cost) (Kaynak: Dolap yardım sayfaları)."""
    if not items:
        return 0.0
    return max(item.shipping_cost for item in items)


def buyer_shipping(items: list[Listing], price: float) -> float:
    """Fiyata göre alıcının ödeyeceği kargo ücreti (Kaynak: Dolap yardım sayfaları).

    - price < 250       -> package_shipping(items)
    - 250 <= price < 400 -> 29.99 (SHIPPING_SHARED_BUYER)
    - price >= 400      -> 0.0 (ücretsiz kargo)
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

    Parçalı fonksiyon: üç fiyat bölgesinin ([0, 250), [250, 400), [400, ∞)) her birinde
    en yüksek adayı dener ve koşulu sağlayan en büyük p değerini döndürür.
    Hiçbiri bütçeye sığmıyorsa 0.0 döner.
    """
    if not items or budget <= 0.0:
        return 0.0

    list_total = sum(item.list_price for item in items)
    pkg_ship = package_shipping(items)

    candidates: list[float] = []

    # Bölge 3: p >= 400.0 (alıcı kargosu = 0.0) -> p <= min(list_total, budget)
    cand_free = min(list_total, budget)
    if cand_free >= SHIPPING_FREE_THRESHOLD:
        candidates.append(cand_free)

    # Bölge 2: 250.0 <= p < 400.0 (alıcı kargosu = 29.99) -> p <= budget - 29.99
    # Üst sınır < 400.0 (kuruş hassasiyetinde 399.99) ve liste toplamını aşamaz.
    upper_shared = min(list_total, SHIPPING_FREE_THRESHOLD - 0.01, budget - SHIPPING_SHARED_BUYER)
    if upper_shared >= SHIPPING_SHARED_THRESHOLD:
        candidates.append(upper_shared)

    # Bölge 1: 0.0 <= p < 250.0 (alıcı kargosu = pkg_ship) -> p <= budget - pkg_ship
    upper_full = min(list_total, SHIPPING_SHARED_THRESHOLD - 0.01, budget - pkg_ship)
    if upper_full >= 0.0:
        candidates.append(upper_full)

    valid = [
        round(p, 2)
        for p in candidates
        if round(p, 2) + buyer_shipping(items, round(p, 2)) <= budget + 1e-9
    ]
    return max(valid) if valid else 0.0
