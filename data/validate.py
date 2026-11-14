"""Veri dosyalarını doğrular ve paket pazarlığının mümkün olup olmadığını raporlar.

Çalıştırma (proje kökünden):  python -m data.validate
"""
import json
import sys
from collections import Counter
from pathlib import Path

from schemas import Listing, Scenario

DATA_DIR = Path(__file__).parent
# Alıcının ilk teklifi liste toplamının bu oranıdır (buyer/config.py içindeki START_FRACTION ile aynı olmalı).
BUYER_START_FRACTION = 0.70


def load_listings(path: str | Path) -> list[Listing]:
    """JSON dosyasını okur; her kaydı Listing şemasıyla doğrular (hatalıysa Pydantic hata fırlatır)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Listing.model_validate(item) for item in raw]


def load_scenarios(path: str | Path) -> list[Scenario]:
    """JSON dosyasını okur; her kaydı Scenario şemasıyla doğrular."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Scenario.model_validate(item) for item in raw]


def multi_listing_sellers(listings: list[Listing], min_count: int = 3) -> dict[str, int]:
    """En az min_count ilanı olan satıcıları {satıcı: ilan sayısı} olarak döndürür."""
    counts = Counter(l.seller_id for l in listings)
    return {seller: n for seller, n in counts.items() if n >= min_count}


def _lower_tr(text: str) -> str:
    """Türkçe'ye uygun küçük harfe çevirir (İ -> i, I -> ı)."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def match_need(need: str, listing: Listing) -> bool:
    """İhtiyaç maddesindeki her kelime ilanın başlığında veya kategorisinde geçiyorsa True.

    Bu yalnızca veri doğrulaması için basit bir kuraldır; alıcı modülünün
    kendi eşleştiricisi farklı çalışabilir.
    """
    haystack = _lower_tr(f"{listing.title} {listing.category}")
    return all(word in haystack for word in _lower_tr(need).split())


def bundle_candidates(scenario: Scenario, listings: list[Listing]) -> list[Listing]:
    """Hedef ilanın satıcısının, need_list'teki bir maddeyle eşleşen DİĞER ilanları."""
    by_id = {l.listing_id: l for l in listings}
    target = by_id[scenario.target_listing_id]
    return [
        l for l in listings
        if l.seller_id == target.seller_id
        and l.listing_id != target.listing_id
        and any(match_need(need, l) for need in scenario.need_list)
    ]


def bundle_feasible(scenario: Scenario, listings: list[Listing]) -> bool:
    """Bütçe en küçük paketle (hedef + en ucuz aday) pazarlığa başlamaya yetiyor mu?

    Koşul: 0.70 * (hedef + en ucuz adayın liste fiyatı) + tek kargo <= bütçe.
    Alıcı modülünün select_bundle fonksiyonu da paketi aynı kuralla kurar: alıcının
    ilk teklifi (liste toplamının %70'i) + tek kargo bütçeyi aşmamalıdır.
    """
    by_id = {l.listing_id: l for l in listings}
    target = by_id[scenario.target_listing_id]
    candidates = bundle_candidates(scenario, listings)
    if not candidates:
        return False
    cheapest = min(c.list_price for c in candidates)
    first_offer = BUYER_START_FRACTION * (target.list_price + cheapest)
    return first_offer + target.shipping_cost <= scenario.budget


def check_listings(listings: list[Listing]) -> list[str]:
    """İlanlardaki veri hatalarını metin listesi olarak döndürür (boş liste = sorun yok)."""
    errors = []
    ids = [l.listing_id for l in listings]
    if len(ids) != len(set(ids)):
        errors.append("Tekrarlanan listing_id var")
    shipping: dict[str, float] = {}
    for l in listings:
        ratio = l.floor_price / l.list_price
        if not 0.70 <= ratio <= 0.85:
            errors.append(f"{l.listing_id}: alt sınır oranı {ratio:.2f} (%70-85 dışında)")
        if shipping.setdefault(l.seller_id, l.shipping_cost) != l.shipping_cost:
            errors.append(f"{l.seller_id}: kargo ücreti ilanlar arasında farklı")
    return errors


def check_scenarios(scenarios: list[Scenario], listings: list[Listing]) -> list[str]:
    """Senaryolardaki veri hatalarını metin listesi olarak döndürür."""
    errors = []
    by_id = {l.listing_id: l for l in listings}
    multi = multi_listing_sellers(listings)
    for s in scenarios:
        target = by_id.get(s.target_listing_id)
        if target is None:
            errors.append(f"{s.scenario_id}: hedef ilan bulunamadı")
            continue
        if target.seller_id not in multi:
            errors.append(f"{s.scenario_id}: hedefin satıcısı çok ilanlı değil")
        if not 2 <= len(s.need_list) <= 4:
            errors.append(f"{s.scenario_id}: need_list 2-4 madde olmalı")
        if not bundle_candidates(s, listings):
            errors.append(f"{s.scenario_id}: aynı satıcıda eşleşen başka ilan yok")
        if target.floor_price + target.shipping_cost > s.budget:
            errors.append(f"{s.scenario_id}: bütçe hedef ürüne bile yetmiyor")
    return errors


def main() -> None:
    """Dosyaları doğrular, özet raporu yazdırır; hata varsa çıkış kodu 1 olur."""
    listings = load_listings(DATA_DIR / "listings.json")
    sample = load_listings(DATA_DIR / "sample_listings.json")
    scenarios = load_scenarios(DATA_DIR / "scenarios.json")

    multi = multi_listing_sellers(listings)
    print(f"listings.json: {len(listings)} ilan, {len({l.seller_id for l in listings})} satıcı")
    print(f"3+ ilanlı satıcı sayısı: {len(multi)}  {dict(sorted(multi.items()))}")
    print(f"sample_listings.json: {len(sample)} ilan, "
          f"3+ ilanlı satıcı: {len(multi_listing_sellers(sample))}")

    try:  # alıcı modülü varsa onun gerçek paket seçimini de göster
        from buyer.bundle import select_bundle
    except ImportError:
        select_bundle = None

    print(f"\nscenarios.json: {len(scenarios)} senaryo")
    feasible_count = real_count = 0
    for s in scenarios:
        candidates = bundle_candidates(s, listings)
        feasible = bundle_feasible(s, listings)
        feasible_count += feasible
        line = (f"  {s.scenario_id}: hedef={s.target_listing_id}  aday={len(candidates)}  "
                f"paket {'MÜMKÜN' if feasible else 'mümkün değil'}")
        if select_bundle is not None:
            size = len(select_bundle(s, listings, "bundle"))
            real_count += size > 1
            line += f"  | alıcı modülü: {size} ürün"
        print(line)
    print(f"Paket mümkün: {feasible_count}/{len(scenarios)}")
    if select_bundle is not None:
        print(f"Alıcı modülünün paket kurduğu senaryo: {real_count}/{len(scenarios)}")

    errors = check_listings(listings) + check_listings(sample) + check_scenarios(scenarios, listings)
    if errors:
        print("\nHATALAR:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("\nTüm kontroller geçti.")


if __name__ == "__main__":
    main()
