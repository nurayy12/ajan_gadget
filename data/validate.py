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
    cheapest = min(candidates, key=lambda c: c.list_price)
    first_offer = BUYER_START_FRACTION * (target.list_price + cheapest.list_price)
    # Dolap'ta sepet kargosu en büyük paketin ücretidir.
    shipping = max(target.shipping_cost, cheapest.shipping_cost)
    return first_offer + shipping <= scenario.budget


def check_listings(listings: list[Listing]) -> list[str]:
    """İlanlardaki veri hatalarını metin listesi olarak döndürür (boş liste = sorun yok)."""
    errors = []
    ids = [l.listing_id for l in listings]
    if len(ids) != len(set(ids)):
        errors.append("Tekrarlanan listing_id var")
    from data.generate import SHIPPING_TARIFF  # döngüsel import olmasın diye burada
    for l in listings:
        ratio = l.floor_price / l.list_price
        if not 0.70 <= ratio <= 0.85:
            errors.append(f"{l.listing_id}: alt sınır oranı {ratio:.2f} (%70-85 dışında)")
        # Kargo artık satıcı başına sabit değil; ilanın paket boyutuna göre Dolap tarifesinden gelir.
        if l.shipping_cost not in SHIPPING_TARIFF.values():
            errors.append(f"{l.listing_id}: kargo ücreti {l.shipping_cost} Dolap tarifesinde yok")
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
        # Bütçenin alt sınıra yetmemesi artık hata değil: dar senaryolarda bilerek anlaşma alanı
        # kalmayabilir. Bunu main() içindeki ZOPA raporu gösterir.
    return errors


def zopa(items: list[Listing], budget: float) -> bool | None:
    """Anlaşma alanı (ZOPA) var mı: max_affordable_price(items, bütçe) >= bundle_floor(items).

    Alıcının ödeyebileceği en yüksek fiyat, satıcının paket indirimli alt sınırına yetiyorsa True.
    policy.py henüz yoksa None döner (rapor bu sütunu boş bırakır).
    """
    try:
        from policy import bundle_floor, max_affordable_price
    except ImportError:
        return None
    return max_affordable_price(items, budget) >= bundle_floor(items)


def scenario_report(scenario: Scenario, listings: list[Listing]) -> dict:
    """Bir senaryo için rapor satırı: aday sayısı, paket mümkün mü, alıcı modülünün paketi, iki modda ZOPA."""
    from buyer.bundle import select_bundle
    by_id = {l.listing_id: l for l in listings}
    target = by_id[scenario.target_listing_id]
    bundle = select_bundle(scenario, listings, "bundle")
    return {
        "candidates": len(bundle_candidates(scenario, listings)),
        "feasible": bundle_feasible(scenario, listings),
        "bundle_size": len(bundle),
        "zopa_single": zopa([target], scenario.budget),
        "zopa_bundle": zopa(bundle, scenario.budget),
    }


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

    print(f"\nscenarios.json: {len(scenarios)} senaryo")
    rows = [scenario_report(s, listings) for s in scenarios]
    def yn(v):
        return "?" if v is None else ("var" if v else "YOK")
    for s, r in zip(scenarios, rows):
        print(f"  {s.scenario_id}: hedef={s.target_listing_id}  aday={r['candidates']}  "
              f"paket {'MÜMKÜN' if r['feasible'] else 'mümkün değil'}  | alıcı modülü: "
              f"{r['bundle_size']} ürün  | ZOPA tek ürün: {yn(r['zopa_single'])}, paket: {yn(r['zopa_bundle'])}")
    print(f"Paket mümkün: {sum(r['feasible'] for r in rows)}/{len(scenarios)}")
    print(f"Alıcı modülünün paket kurduğu senaryo: {sum(r['bundle_size'] > 1 for r in rows)}/{len(scenarios)}")
    if rows and rows[0]["zopa_single"] is None:
        print("ZOPA hesaplanmadı: kökte policy.py henüz yok.")
    else:
        no_zopa = [(s.scenario_id, m) for s, r in zip(scenarios, rows)
                   for m in ("single", "bundle") if not r[f"zopa_{m}"]]
        print(f"Anlaşma alanı olmayan senaryo-mod çifti: {len(no_zopa)} "
              f"(hata değil; bu çalıştırmalarda doğru davranış anlaşmamaktır) {no_zopa}")

    errors = check_listings(listings) + check_listings(sample) + check_scenarios(scenarios, listings)
    if errors:
        print("\nHATALAR:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("\nTüm kontroller geçti.")


if __name__ == "__main__":
    main()
