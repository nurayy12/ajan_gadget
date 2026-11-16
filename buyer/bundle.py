"""Paket seçimi: hedef ilan + aynı satıcının ihtiyaç listesine uyan diğer ilanları."""
from itertools import combinations

from schemas import Listing, Scenario

from . import config
from ._policy import buyer_shipping, package_shipping
from .matching import _match_per_need

MAX_BASKET_ITEMS = 10  # Dolap sepeti en fazla 10 ürün alır (Dolap yardım sayfaları)


def bundle_shipping(bundle: list[Listing], target_listing_id: str | None = None) -> float:
    """Sepetin kargo ücreti (indirimsiz) = policy.package_shipping = en yüksek kargo ücreti.

    Başka modüllerin çağrıları bozulmasın diye bu ad ve ikinci parametre korunur;
    target_listing_id artık kullanılmaz. Alıcının gerçekten ödediği kargo fiyata bağlıdır
    (policy.buyer_shipping).
    """
    return package_shipping(bundle)


def bundle_feasible(items: list[Listing], budget: float) -> bool:
    """Paket bütçeye sığar mı: alıcının ilk teklifi + o fiyata düşen kargo <= bütçe.

    ilk teklif = config.START_FRACTION x liste toplamı (çağrı anında okunur).
    """
    opening = round(config.START_FRACTION * sum(l.list_price for l in items), 2)
    return opening + buyer_shipping(items, opening) <= budget


def select_bundle(scenario: Scenario, listings: list[Listing], mode: str) -> list[Listing]:
    """mode="single": yalnızca hedef ilan.
    mode="bundle": hedef ilanı içeren, en fazla MAX_BASKET_ITEMS ürünlük, bundle_feasible olan
    (ilk teklif + kargo bütçeyi aşmayan) ve en çok ihtiyaç maddesini karşılayan alt küme.
    Eşitlikte az ürünlü, o da eşitse ucuz olan seçilir.
    Hiçbir paket bütçeye sığmazsa yalnızca hedef ilan döner.
    """
    by_id = {l.listing_id: l for l in listings}
    if scenario.target_listing_id not in by_id:
        raise ValueError(f"Hedef ilan bulunamadı: {scenario.target_listing_id}")
    target = by_id[scenario.target_listing_id]

    if mode == "single":
        return [target]
    if mode != "bundle":
        raise ValueError(f"Bilinmeyen mod: {mode!r} (single ya da bundle olmalı)")

    # Hedefin satıcısındaki ilanlar için: hangi ihtiyaç maddelerini karşılıyor?
    per_need = _match_per_need(scenario.need_list, listings)
    covers: dict[str, set[int]] = {}
    for need_idx, hits in enumerate(per_need):
        for listing, _score in hits:
            if listing.seller_id == target.seller_id:
                covers.setdefault(listing.listing_id, set()).add(need_idx)

    others = [
        l for l in listings
        if l.seller_id == target.seller_id
        and l.listing_id != target.listing_id
        and l.listing_id in covers
    ]

    best: list[Listing] | None = None
    best_key = None
    for size in range(min(len(others), MAX_BASKET_ITEMS - 1) + 1):
        for combo in combinations(others, size):
            items = [target, *combo]
            list_total = sum(l.list_price for l in items)
            if not bundle_feasible(items, scenario.budget):
                continue
            covered: set[int] = set()
            for l in items:
                covered |= covers.get(l.listing_id, set())
            key = (-len(covered), len(items), list_total)
            if best_key is None or key < best_key:
                best, best_key = items, key
    return best if best is not None else [target]
