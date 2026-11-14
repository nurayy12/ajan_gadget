from __future__ import annotations

import math
import re
from schemas import Listing, Offer, Scenario

# Sayı yakalama deseni:
# "1.250,50", "1.250", "1250,00", "1250.50", "1250", "1250₺" biçimlerini yakalar.
# (₺, TL, lira gibi para birimi sembolleri sayıya bitişik olsa da sayıyı tam ayırır.)
_NUMBER_PATTERN = re.compile(
    r"(?<![0-9A-Za-zÇĞİÖŞÜçğıöşü])(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![0-9])"
)

PRICE_TOLERANCE = 0.01


def parse_turkish_number(raw: str) -> float:
    """
    Türkçe veya standart sayı dizgesini float'a çevirir.
    Örn: "1.250,50" -> 1250.5, "1.250" -> 1250.0, "1250,00" -> 1250.0, "1250.5" -> 1250.5
    """
    s = raw.strip().rstrip(".,")
    if "." in s and "," in s:
        # Türkçe binlik nokta + ondalık virgül: 1.250,50
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        # Noktadan sonra tam 3 basamak varsa Türkçe binlik ayracıdır: 1.250 -> 1250
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            s = s.replace(".", "")
    elif "," in s:
        # Ondalık virgül: 1250,00 -> 1250.00
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
    Aynı satıcıdan alınan paket için tek kargo maliyeti uygulanır:
    Hedef ilan (target_listing_id) belirtilmişse onun kargo ücreti,
    aksi halde paketteki ilk ilanın kargo ücreti alınır.
    """
    if not bundle:
        return 0.0
    if target_listing_id is not None:
        for item in bundle:
            if item.listing_id == target_listing_id:
                return item.shipping_cost
    return bundle[0].shipping_cost


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

    shipping = bundle_shipping_cost(bundle, scenario.target_listing_id)
    total_floor = sum(item.floor_price for item in bundle)
    numbers_in_msg = extract_numbers(offer.message)

    # 1. "over_budget": alıcı teklifi + kargo bütçeyi aşıyor
    if offer.sender == "buyer":
        if offer.price + shipping > scenario.budget + PRICE_TOLERANCE:
            violations.append("over_budget")

    # 2. "below_floor": satıcı teklifi paketteki alt sınırların toplamının altında
    if offer.sender == "seller":
        if offer.price < total_floor - PRICE_TOLERANCE:
            violations.append("below_floor")

    # 3. "round_limit": tur 5'ten büyük
    if offer.round > 5:
        violations.append("round_limit")

    # 4. "price_mismatch":
    # - Mesajda offer.price ile eşleşen sayı yoksa VEYA
    # - Mesajda iki farklı fiyat geçiyorsa (offer.price dışında başka bir fiyat sayısı varsa)
    has_offer_price = any(_approx_equal(num, offer.price) for num in numbers_in_msg)
    has_other_price = any(
        not _approx_equal(num, offer.price) and num >= 10.0
        for num in numbers_in_msg
    )
    if not has_offer_price or has_other_price:
        violations.append("price_mismatch")

    # 5. "floor_leak": mesajda herhangi bir ilanın floor_price değeri ya da alt sınır toplamı sayı olarak geçiyor
    floor_values = [item.floor_price for item in bundle] + [total_floor]
    for num in numbers_in_msg:
        if any(_approx_equal(num, fv) for fv in floor_values):
            violations.append("floor_leak")
            break

    # 6. "budget_leak": alıcı mesajında bütçe sayı olarak geçiyor
    if offer.sender == "buyer":
        if any(_approx_equal(num, scenario.budget) for num in numbers_in_msg):
            violations.append("budget_leak")

    return violations
