"""Veri dosyalarını sabit seed ile üretir: listings.json, sample_listings.json, scenarios.json.

Çalıştırma (proje kökünden):  python -m data.generate
Aynı seed her zaman aynı dosyaları üretir; deney tekrarlanabilir kalır.
"""
import json
import math
import random
from pathlib import Path

from schemas import Listing, Scenario
from data.validate import bundle_candidates, bundle_feasible, multi_listing_sellers
from buyer.bundle import select_bundle  # alıcı modülünün gerçek paket seçimi (yalnızca kontrol için)

DATA_DIR = Path(__file__).parent
SEED = 42
SHIPPING_OPTIONS = [39.90, 49.90, 59.90, 69.90]

# Katalog elle yazıldı: satıcı -> ilanlar.
# Her ilan: (başlık, açıklama, kategori, beden, durum, liste fiyatı, ihtiyaç ifadesi)
# "ihtiyaç ifadesi" şemaya yazılmaz; yalnızca senaryoların need_list'ini kurmak için kullanılır.
CATALOG: dict[str, list[tuple]] = {
    "s01": [
        ("Zara siyah suni deri ceket", "Geçen sezon aldım, 3-4 kez giyildi. Fermuarı sorunsuz, astarında yıpranma yok.", "kadın giyim", "M", "az kullanılmış", 1450, "deri ceket"),
        ("Mango yüksek bel kot pantolon", "Mom jean kesim, açık mavi. Bana bol geldiği için satıyorum, defosu yok.", "kadın giyim", "38", "az kullanılmış", 650, "yüksek bel kot pantolon"),
        ("Koton beyaz keten gömlek", "Yazlık, oversize kalıp. Bir kez giyildi, lekesiz.", "kadın giyim", "M", "yeni gibi", 380, "keten gömlek"),
        ("H&M çiçek desenli midi elbise", "Viskon kumaş, belden bağlamalı. Düğün için alındı, tek kullanım.", "kadın giyim", "M", "yeni gibi", 520, "midi elbise"),
    ],
    "s02": [
        ("Mavi Jeans slim fit kot pantolon", "Marcus model, koyu lacivert, 32/32. Rengi solmadı, paçalar orijinal boyda.", "erkek giyim", "32/32", "az kullanılmış", 700, "slim fit kot pantolon"),
        ("LC Waikiki lacivert kapüşonlu sweatshirt", "İçi polarlı, kanguru cepli. Tüylenme yok.", "erkek giyim", "L", "az kullanılmış", 420, "kapüşonlu sweatshirt"),
        ("Pull&Bear oversize beyaz tişört", "Etiketi üzerinde, hiç giyilmedi. Beden olmadığı için satılık.", "erkek giyim", "L", "yeni etiketli", 250, "oversize tişört"),
        ("Columbia su geçirmez mont", "Omni-Heat astarlı, siyah. İki kış giyildi, fermuar ve çıtçıtlar sağlam.", "erkek giyim", "L", "iyi", 2400, "su geçirmez mont"),
    ],
    "s03": [
        ("Nike Air Force 1 beyaz spor ayakkabı", "Orijinal, kutusu mevcut. Tabanında hafif kullanım izi var.", "ayakkabı", "38", "az kullanılmış", 2200, "beyaz spor ayakkabı"),
        ("Adidas Stan Smith yeşil detaylı sneaker", "Orijinal, faturası duruyor. Burun kısmında çok hafif kırışıklık.", "ayakkabı", "38", "iyi", 1800, "sneaker"),
        ("Skechers hafızalı taban yürüyüş ayakkabısı", "Gri-pembe, çok rahat. Numarası büyük geldi, 2 kez giyildi.", "ayakkabı", "38", "yeni gibi", 1300, "yürüyüş ayakkabısı"),
        ("Dr. Martens 1460 siyah bot", "8 delikli klasik model. Deri bakımı yapıldı, tabanı yeni gibi.", "ayakkabı", "38", "iyi", 3500, "siyah bot"),
    ],
    "s04": [
        ("Mango siyah omuz çantası", "Zincir askılı, kapaklı model. İç astarı temiz, toz torbasıyla gönderilir.", "çanta", None, "az kullanılmış", 750, "omuz çantası"),
        ("Fjällräven Kanken bordo sırt çantası", "Orijinal, 16 litre. Okulda bir dönem kullanıldı, fermuarlar sağlam.", "çanta", None, "iyi", 1600, "sırt çantası"),
        ("Derimod hakiki deri kadın cüzdan", "Taba rengi, çok bölmeli. Hediye geldi, kutusunda.", "çanta", None, "yeni etiketli", 550, "deri cüzdan"),
        ("Zara hasır el çantası", "Yazlık, bambu saplı. Tek sezon kullanıldı.", "çanta", None, "az kullanılmış", 480, "el çantası"),
    ],
    "s05": [
        ("Ray-Ban Wayfarer güneş gözlüğü", "Orijinal, kılıfı ve bezi mevcut. Camlarda çizik yok.", "aksesuar", None, "az kullanılmış", 2800, "güneş gözlüğü"),
        ("Vakko ipek fular", "90x90, lacivert desenli. Kutusunda, hiç kullanılmadı.", "aksesuar", None, "yeni etiketli", 1200, "ipek fular"),
        ("Hakiki deri kahverengi kemer", "4 cm genişlik, 105 cm. Tokasında çizik yok.", "aksesuar", None, "iyi", 300, "deri kemer"),
        ("Casio vintage altın rengi kol saati", "A168 model, pili yeni değişti. Kordon tam boy.", "aksesuar", None, "az kullanılmış", 1100, "kol saati"),
    ],
    "s06": [
        ("İpekyol bej triko kazak", "Yün karışımlı, boğazlı. Kuru temizlemeden çıktı.", "kadın giyim", "S", "az kullanılmış", 600, "triko kazak"),
        ("Network camel kaşe kaban", "Diz üstü, kuşaklı. İki sezon giyildi, astarı sağlam.", "kadın giyim", "S", "iyi", 3200, "kaşe kaban"),
        ("Stradivarius siyah pileli etek", "Midi boy, beli lastikli. Birkaç kez giyildi.", "kadın giyim", "S", "az kullanılmış", 350, "pileli etek"),
        ("Massimo Dutti lacivert blazer ceket", "Tek düğmeli, astarlı. Ofis için alındı, çok az giyildi.", "kadın giyim", "S", "yeni gibi", 1900, "blazer ceket"),
    ],
    "s07": [
        ("Altınyıldız beyaz klasik gömlek", "Slim fit, pamuklu. Ütülü ve temiz gönderilir.", "erkek giyim", "M", "az kullanılmış", 450, "klasik gömlek"),
        ("Dockers bej chino pantolon", "31/32, düz kesim. Rengi canlı, diz izi yok.", "erkek giyim", "31/32", "az kullanılmış", 800, "chino pantolon"),
        ("Hotiç kahverengi deri klasik ayakkabı", "Bağcıklı oxford model. Düğünde bir kez giyildi.", "ayakkabı", "42", "yeni gibi", 1700, "klasik ayakkabı"),
        ("Pierre Cardin bordo ipek kravat", "Kutusunda, desenli. Hiç takılmadı.", "aksesuar", None, "yeni etiketli", 280, "kravat"),
    ],
    "s08": [
        ("Oleg Cassini zümrüt yeşili abiye elbise", "Uzun, saten, yırtmaçlı. Tek gece giyildi, kuru temizleme yapıldı.", "kadın giyim", "36", "yeni gibi", 4500, "abiye elbise"),
        ("Nine West gümüş topuklu ayakkabı", "8 cm ince topuk. Abiyeyle birlikte bir kez giyildi.", "ayakkabı", "37", "yeni gibi", 1400, "topuklu ayakkabı"),
        ("Gümüş taşlı clutch çanta", "Zincir askısı içinde. Davet için alındı, tek kullanım.", "çanta", None, "yeni gibi", 650, "clutch çanta"),
        ("Siyah saten omuz şalı", "Geniş, abiye üstüne uygun. Lekesiz.", "aksesuar", None, "az kullanılmış", 320, "şal"),
    ],
    "s09": [
        ("Nike Pro siyah spor tayt", "Yüksek bel, toparlayıcı. Dikişlerinde açılma yok.", "kadın giyim", "S", "az kullanılmış", 700, "spor tayt"),
        ("Adidas pembe spor atlet", "Hızlı kuruyan kumaş. İki kez giyildi.", "kadın giyim", "S", "yeni gibi", 400, "spor atlet"),
        ("Asics Gel-Contend koşu ayakkabısı", "Mor-beyaz, yaklaşık 50 km koşuldu. Taban dişleri duruyor.", "ayakkabı", "37", "iyi", 1900, "koşu ayakkabısı"),
        ("Puma fermuarlı eşofman üstü", "Gri, cepli. Bol kalıp.", "kadın giyim", "S", "az kullanılmış", 650, "eşofman üstü"),
    ],
    "s10": [
        ("Derimod hakiki deri erkek ceket", "Siyah, biker model. Derisi yumuşak, çatlama yok.", "erkek giyim", "L", "iyi", 5200, "erkek deri ceket"),
        ("Timberland sarı erkek bot", "Klasik 6 inç model. Su geçirmez, tabanı sağlam.", "ayakkabı", "43", "iyi", 3800, "erkek bot"),
        ("Mavi yün atkı ve bere takımı", "Antrasit, hediye paketinde. Hiç kullanılmadı.", "aksesuar", None, "yeni etiketli", 450, "atkı bere"),
    ],
    "s11": [
        ("Zara bej trençkot", "Kruvaze, kemerli. Bahar için ideal, iki sezon giyildi.", "kadın giyim", "M", "iyi", 1800, "trençkot"),
        ("Bambi siyah rugan babet", "Fiyonklu, çok rahat. Topuk lastiği yeni.", "ayakkabı", "38", "az kullanılmış", 500, "babet"),
        ("Koton bez tote çanta", "Krem rengi, baskılı. Fermuarlı iç cep var.", "çanta", None, "yeni gibi", 220, "tote çanta"),
    ],
    "s12": [
        ("Mango saten yeşil gömlek", "Dökümlü, gizli düğmeli. Bir kez giyildi.", "kadın giyim", "L", "yeni gibi", 550, "saten gömlek"),
        ("Koton kot mini etek", "Önden düğmeli, açık mavi. Defosuz.", "kadın giyim", "L", "az kullanılmış", 300, "mini etek"),
    ],
    "s13": [
        ("Lacoste lacivert polo yaka tişört", "Orijinal, timsah logolu. Yakası formunu koruyor.", "erkek giyim", "XL", "az kullanılmış", 1500, "polo yaka tişört"),
        ("DeFacto haki kargo şort", "Bol cepli, diz üstü. Tatilde bir hafta giyildi.", "erkek giyim", "XL", "az kullanılmış", 350, "kargo şort"),
    ],
    "s14": [
        ("New Balance 574 gri sneaker", "Orijinal, kutulu. Süet kısımları temiz.", "ayakkabı", "41", "az kullanılmış", 2600, "gri sneaker"),
        ("Birkenstock Arizona kahverengi sandalet", "Mantar taban, iki bantlı. Bir yaz giyildi.", "ayakkabı", "41", "iyi", 1500, "sandalet"),
    ],
    "s15": [
        ("Samsonite 15.6 inç laptop çantası", "Omuz askılı, siyah. Fermuar ve askı sağlam.", "çanta", None, "iyi", 1300, "laptop çantası"),
        ("New Era siyah beyzbol şapkası", "Ayarlanabilir, işlemeli logo. Birkaç kez takıldı.", "aksesuar", None, "az kullanılmış", 600, "beyzbol şapkası"),
    ],
}


def build_listings(seed: int = SEED) -> list[Listing]:
    """Katalogdan 50 ilanı üretir.

    Kargo ücreti satıcı başına bir kez seçilir (sabit); alt sınır her ilan için
    liste fiyatının %70-85'i arasında rastgele belirlenir.
    """
    rng = random.Random(seed)
    listings: list[Listing] = []
    for seller_id, items in CATALOG.items():
        shipping = rng.choice(SHIPPING_OPTIONS)
        for title, description, category, size, condition, list_price, _need in items:
            listings.append(Listing(
                listing_id=f"L{len(listings) + 1:03d}",
                seller_id=seller_id,
                title=title,
                description=description,
                category=category,
                size=size,
                condition=condition,
                list_price=float(list_price),
                floor_price=round(list_price * rng.uniform(0.70, 0.85), 2),
                shipping_cost=shipping,
            ))
    return listings


def build_sample(listings: list[Listing]) -> list[Listing]:
    """10 ilanlık alt küme: s01'in 4 ilanı, s02'nin 3 ilanı, sonraki üç satıcıdan birer ilan.

    ID'ler listings.json ile aynıdır; küçük dosyayla yazılan kod büyük dosyada da çalışır.
    """
    by_seller: dict[str, list[Listing]] = {}
    for l in listings:
        by_seller.setdefault(l.seller_id, []).append(l)
    return (by_seller["s01"] + by_seller["s02"][:3]
            + [by_seller[s][0] for s in ("s03", "s04", "s05")])


def _needs_by_listing(listings: list[Listing]) -> dict[str, str]:
    """listing_id -> katalogdaki ihtiyaç ifadesi (ilanlar katalog sırasıyla üretildiği için sıra eşleşir)."""
    needs = [item[6] for items in CATALOG.values() for item in items]
    return {l.listing_id: need for l, need in zip(listings, needs)}


def build_scenarios(listings: list[Listing], seed: int = SEED,
                    n: int = 15, n_tight: int = 3) -> list[Scenario]:
    """15 senaryo üretir: 12'sinde bütçe pakete yeter, 3'ünde yalnızca hedef ürüne yeter.

    need_list = hedefin ifadesi + aynı satıcıdan 1-2 ürün + (bazen) başka satıcıdan
    bir çeldirici. Paketli senaryoda bütçe, (paketin liste toplamı + kargo)'nun
    %100-110'udur. Dar senaryoda bütçe = hedefin liste fiyatı + kargo ve hedef, ikinci
    bir ürünle pazarlığa başlamaya bu bütçe yetmeyecek şekilde seçilir (alıcı modülü
    paketi, ilk teklif = liste toplamının %70'i + kargo bütçeye sığıyorsa kurar).
    Her senaryo alıcı modülünün select_bundle
    fonksiyonuyla da denenir: paketli senaryoda birden fazla ürün, dar senaryoda yalnızca
    hedef seçilmiyorsa o hedef atlanıp başkası denenir.
    """
    rng = random.Random(seed)
    need_of = _needs_by_listing(listings)
    multi = sorted(multi_listing_sellers(listings))
    by_seller = {s: [l for l in listings if l.seller_id == s] for s in multi}
    tight_indexes = {4, 9, 13}
    assert len(tight_indexes) == n_tight

    scenarios: list[Scenario] = []
    used_targets: set[str] = set()
    for i in range(n):
        seller = multi[i % len(multi)]
        own = by_seller[seller]
        # Aynı ilan iki senaryoda hedef olmasın; dar senaryoda koşulu sağlayan hedef aranır.
        for target in rng.sample(own, len(own)):
            if target.listing_id in used_targets:
                continue
            others = [l for l in own if l.listing_id != target.listing_id]
            same_seller = rng.sample(others, rng.choice([1, 2]))
            need_list = [need_of[target.listing_id]] + [need_of[l.listing_id] for l in same_seller]
            if rng.random() < 0.5:
                distractor = rng.choice([l for l in listings if l.seller_id != seller])
                need_list.append(need_of[distractor.listing_id])

            scenario = Scenario(scenario_id=f"SC{i + 1:02d}", need_list=need_list,
                                budget=0.0, target_listing_id=target.listing_id)
            candidates = bundle_candidates(scenario, listings)
            if i in tight_indexes:
                scenario.budget = round(target.list_price + target.shipping_cost, 2)
                ok = (not bundle_feasible(scenario, listings)
                      and len(select_bundle(scenario, listings, "bundle")) == 1)
            else:
                bundle_list_total = target.list_price + sum(c.list_price for c in candidates)
                scenario.budget = float(math.ceil(
                    (bundle_list_total + target.shipping_cost) * rng.uniform(1.00, 1.10)))
                # Alıcı modülü de gerçekten paket kurmalı; yoksa bu senaryoda paket koşulu ölçülemez.
                ok = (bundle_feasible(scenario, listings)
                      and len(select_bundle(scenario, listings, "bundle")) > 1)
            if ok:
                scenarios.append(scenario)
                used_targets.add(target.listing_id)
                break
        else:
            raise RuntimeError(f"SC{i + 1:02d} için uygun hedef bulunamadı")
    return scenarios


def _write(path: Path, items: list) -> None:
    """Pydantic nesne listesini okunaklı (girintili, Türkçe karakterli) JSON olarak yazar."""
    path.write_text(json.dumps([x.model_dump() for x in items], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def main() -> None:
    """Üç veri dosyasını data/ klasörüne yazar."""
    listings = build_listings()
    scenarios = build_scenarios(listings)
    _write(DATA_DIR / "listings.json", listings)
    _write(DATA_DIR / "sample_listings.json", build_sample(listings))
    _write(DATA_DIR / "scenarios.json", scenarios)
    print(f"{len(listings)} ilan, {len(scenarios)} senaryo yazıldı.")


if __name__ == "__main__":
    main()
