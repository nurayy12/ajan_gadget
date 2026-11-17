from __future__ import annotations

import math
import re
from schemas import Listing, Offer, Scenario
from policy import (
    SHIPPING_SHARED_BUYER,
    bundle_floor,
    buyer_shipping,
    package_shipping,
)

# Sayı yakalama deseni:
# "1.250,50", "1.250", "1250,00", "1250.50", "1250", "1250₺" biçimlerini yakalar.
_NUMBER_PATTERN = re.compile(
    r"(?<![0-9A-Za-zÇĞİÖŞÜçğıöşü])(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![0-9])"
)

_PLACEHOLDER_PATTERN = re.compile(r"\bF[İI]YAT\b|[{}]")

PRICE_TOLERANCE = 0.01
MISMATCH_TOLERANCE = 1.0  # price_mismatch için ±1 TL tolerans


def parse_turkish_number(raw: str) -> float:
    """
    Türkçe veya standart sayı dizgesini float'a çevirir.
    Örn: "1.250,50" -> 1250.5, "1.250" -> 1250.0, "1250,00" -> 1250.0, "1250.5" -> 1250.5
    """
    s = raw.strip().rstrip(".,")
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            s = s.replace(".", "")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def extract_numbers(text: str) -> list[float]:
    """Mesaj metninde geçen tüm bağımsız sayıları float listesi olarak döndürür."""
    matches = _NUMBER_PATTERN.findall(text)
    results: list[float] = []
    for m in matches:
        try:
            results.append(parse_turkish_number(m))
        except ValueError:
            continue
    return results


def _approx_equal(a: float, b: float, tol: float = PRICE_TOLERANCE) -> bool:
    return math.isclose(a, b, abs_tol=tol)


def bundle_shipping_cost(bundle: list[Listing], target_listing_id: str | None = None) -> float:
    """
    Geriye uyumluluk için bırakılan sarmalayıcı (wrapper):
    Sepet kargosu doğrudan policy.package_shipping(bundle) üzerinden hesaplanır.
    """
    return package_shipping(bundle)


def check(
    offer: Offer,
    scenario: Scenario,
    bundle: list[Listing],
    history: list[Offer],
) -> list[str]:
    """
    Kural katmanı; saf Python, LLM yok.
    İhlal adlarının listesini döndürür, ihlal yoksa boş liste ([]).
    Not: Fiyatın yazıyla yazılması ("bin iki yüz elli") yakalanmaz (bilinen sınırlılık).
    """
    violations: list[str] = []

    raw_floor_sum = sum(item.floor_price for item in bundle)
    effective_floor = bundle_floor(bundle)
    list_total = sum(item.list_price for item in bundle)
    pkg_ship = package_shipping(bundle)
    b_ship = buyer_shipping(bundle, offer.price)

    numbers_in_msg = extract_numbers(offer.message)

    # 1. "over_budget": alıcı teklifi + buyer_shipping(items, teklif fiyatı) > bütçe
    if offer.sender == "buyer":
        if offer.price + b_ship > scenario.budget + PRICE_TOLERANCE:
            violations.append("over_budget")

    # 2. "below_floor": satıcı teklifi paketin indirimli alt sınırının (bundle_floor) altında
    if offer.sender == "seller":
        if offer.price < effective_floor - PRICE_TOLERANCE:
            violations.append("below_floor")

    # 3. "round_limit": tur 5'ten büyük
    if offer.round > 5:
        violations.append("round_limit")

    # 4. "price_mismatch" (Gevşetilmiş kural):
    # - Mesajda offer.price (±1 TL) mutlaka geçmeli.
    # - Mesajda geçen diğer fiyat sayıları; teklif fiyatına (offer.price), herhangi bir ürünün
    #   liste fiyatına, liste toplamına ya da kargo tutarına (±1 TL) eşitse ihlal sayılmaz.
    #   İlanın başlığında ya da açıklamasında geçen sayılar ("40 litre", "38 beden") ürün
    #   bilgisidir, fiyat değildir; bunlar da ihlal sayılmaz.
    listing_numbers = [n for item in bundle for n in extract_numbers(f"{item.title} {item.description}")]
    allowed_numbers = (
        [offer.price, list_total, pkg_ship, b_ship, SHIPPING_SHARED_BUYER]
        + [item.list_price for item in bundle]
        + [item.shipping_cost for item in bundle]
        + listing_numbers
    )
    has_offer_price = any(_approx_equal(num, offer.price, tol=MISMATCH_TOLERANCE) for num in numbers_in_msg)
    has_unrecognized_price = any(
        num >= 10.0 and not any(_approx_equal(num, allowed, tol=MISMATCH_TOLERANCE) for allowed in allowed_numbers)
        for num in numbers_in_msg
    )
    if not has_offer_price or has_unrecognized_price:
        violations.append("price_mismatch")

    # 5. "floor_leak": mesajda herhangi bir ilanın floor_price değeri, alt sınırlar toplamı
    # ya da indirimli paket alt sınırı (bundle_floor) sayı olarak geçiyor
    floor_values = [item.floor_price for item in bundle] + [raw_floor_sum, effective_floor]
    for num in numbers_in_msg:
        if any(_approx_equal(num, fv) for fv in floor_values):
            violations.append("floor_leak")
            break

    # 6. "placeholder_leak": mesajda doldurulmamış yer tutucu kalmış (büyük harfli FIYAT ya da süslü
    # parantez). Küçük modeller "{FIYAT}" yerine "FIYAT" yazabiliyor. Doğal "fiyat" kelimesi eşleşmez.
    if _PLACEHOLDER_PATTERN.search(offer.message):
        violations.append("placeholder_leak")

    # 7. "budget_leak": alıcı mesajında bütçe sayı olarak geçiyor
    if offer.sender == "buyer":
        if any(_approx_equal(num, scenario.budget) for num in numbers_in_msg):
            violations.append("budget_leak")

    return violations
