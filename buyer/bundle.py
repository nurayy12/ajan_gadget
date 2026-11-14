"""Paket seçimi: hedef ilan + aynı satıcının ihtiyaç listesine uyan diğer ilanları."""
from itertools import combinations

from schemas import Listing, Scenario

from .matching import _match_per_need


def bundle_shipping(bundle: list[Listing], target_listing_id: str) -> float:
    """Paketin tek kargo ücreti = asıl istenen (hedef) ilanın kargo ücreti.

    Paket, hedef ilanı tek başına almışız gibi aynı kargoyu öder; böylece tek ürün ve
    paket karşılaştırmasına kargo farkı karışmaz. Kural katmanı da aynı kuralı kullanmalı.
    """
    if not bundle:
        return 0.0
    for listing in bundle:
        if listing.listing_id == target_listing_id:
            return listing.shipping_cost
    raise ValueError(f"Hedef ilan pakette yok: {target_listing_id}")


def select_bundle(scenario: Scenario, listings: list[Listing], mode: str) -> list[Listing]:
    """mode="single": yalnızca hedef ilan.
    mode="bundle": hedef ilanı içeren, liste toplamı + tek kargo bütçeyi aşmayan ve en çok
    ihtiyaç maddesini karşılayan alt küme. Eşitlikte az ürünlü, o da eşitse ucuz olan seçilir.
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
    for size in range(len(others) + 1):
        for combo in combinations(others, size):
            items = [target, *combo]
            list_total = sum(l.list_price for l in items)
            if list_total + target.shipping_cost > scenario.budget:
                continue
            covered: set[int] = set()
            for l in items:
                covered |= covers.get(l.listing_id, set())
            key = (-len(covered), len(items), list_total)
            if best_key is None or key < best_key:
                best, best_key = items, key
    return best if best is not None else [target]
