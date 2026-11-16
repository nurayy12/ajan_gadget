"""Veri dosyalarını sabit seed ile üretir: listings.json, sample_listings.json, scenarios.json.

Çalıştırma (proje kökünden):  python -m data.generate
Aynı seed her zaman aynı dosyaları üretir; deney tekrarlanabilir kalır.

Kalibrasyon ve kaynakları
- Alt sınır: liste fiyatının %70-85'i. eBay Best Offer'da pazarlıkla biten satışlarda ortalama
  fiyat listenin %73'ü (Backus, Blake, Larsen, Tadelis 2020, QJE); Dolap'ta alıcı en fazla
  %30 indirimli teklif verebildiği için %70'in altındaki bir alt sınır zaten sınanamaz.
- Kargo: ilanın paket boyutuna göre Dolap tarifesi (aşağıdaki SHIPPING_TARIFF).
- Dar bütçe: liste fiyatının 0,8 katı (OG-Narrator; Xia ve ark. 2024, ACL Findings).
"""
import json
import math
import random
from pathlib import Path

from schemas import Listing, Scenario
from data.validate import bundle_candidates, multi_listing_sellers
from buyer.bundle import select_bundle  # alıcı modülünün gerçek paket seçimi (yalnızca kontrol için)

DATA_DIR = Path(__file__).parent
SEED = 42

# Dolap "Paket boyutları ve kargo ücretleri" yardım sayfası, 16.11.2026'da okundu:
# küçük paket 0-1,99 desi, orta paket 2-5,99 desi, büyük paket 6 desi ve üzeri.
# Değerler 250 TL altındaki siparişte ödenen toplam kargo ücretidir (büyük pakette başlangıç fiyatı).
# Kimin ne kadar ödediği sipariş tutarına göre policy.py'de hesaplanır.
SHIPPING_TARIFF = {"küçük": 39.99, "orta": 135.99, "büyük": 199.99}

# Katalog elle yazıldı: satıcı -> ilanlar.
# Her ilan: (başlık, açıklama, kategori, beden, durum, liste fiyatı, ihtiyaç ifadesi, paket boyutu)
# "ihtiyaç ifadesi" ve "paket boyutu" şemaya yazılmaz: ilki senaryoların need_list'ini kurmak,
# ikincisi kargo ücretini SHIPPING_TARIFF'ten seçmek için kullanılır.
# Paket boyutu eşlemesi: ince giysi ve aksesuar küçük; kazak, kot, ceket, mont, ayakkabı ve çanta
# orta; valiz, büyük sırt çantası ve kalın kışlık mont büyük.
CATALOG: dict[str, list[tuple]] = {
    "s01": [
        ("Zara siyah suni deri ceket", "Geçen sezon aldım, 3-4 kez giyildi. Fermuarı sorunsuz, astarında yıpranma yok.", "kadın giyim", "M", "az kullanılmış", 1450, "deri ceket", "orta"),
        ("Mango yüksek bel kot pantolon", "Mom jean kesim, açık mavi. Bana bol geldiği için satıyorum, defosu yok.", "kadın giyim", "38", "az kullanılmış", 650, "kot pantolon", "orta"),
        ("Koton beyaz keten gömlek", "Yazlık, oversize kalıp. Bir kez giyildi, lekesiz.", "kadın giyim", "M", "yeni gibi", 380, "keten gömlek", "küçük"),
        ("H&M çiçek desenli midi elbise", "Viskon kumaş, belden bağlamalı. Düğün için alındı, tek kullanım.", "kadın giyim", "M", "yeni gibi", 520, "midi elbise", "küçük"),
        ("Bershka siyah basic tişört", "Pamuklu, dar kesim. Birkaç kez giyildi, rengi solmadı.", "kadın giyim", "M", "az kullanılmış", 160, "basic tişört", "küçük"),
    ],
    "s02": [
        ("Mavi Jeans slim fit erkek kot", "Marcus model, koyu lacivert, 32/32. Rengi solmadı, paçalar orijinal boyda.", "erkek giyim", "32/32", "az kullanılmış", 700, "erkek kot", "orta"),
        ("LC Waikiki lacivert kapüşonlu sweatshirt", "İçi polarlı, kanguru cepli. Tüylenme yok.", "erkek giyim", "L", "az kullanılmış", 420, "kapüşonlu sweatshirt", "orta"),
        ("Pull&Bear oversize beyaz tişört", "Etiketi üzerinde, hiç giyilmedi. Beden olmadığı için satılık.", "erkek giyim", "L", "yeni etiketli", 250, "oversize tişört", "küçük"),
        ("Columbia su geçirmez mont", "Omni-Heat astarlı, siyah. İki kış giyildi, fermuar ve çıtçıtlar sağlam.", "erkek giyim", "L", "iyi", 2400, "su geçirmez mont", "büyük"),
        ("DeFacto gri jogger eşofman altı", "Paçası lastikli, yanları cepli. Evde birkaç kez giyildi.", "erkek giyim", "L", "az kullanılmış", 280, "eşofman altı", "küçük"),
    ],
    "s03": [
        ("Nike Air Force 1 beyaz spor ayakkabı", "Orijinal, kutusu mevcut. Tabanında hafif kullanım izi var.", "ayakkabı", "38", "az kullanılmış", 2200, "beyaz spor ayakkabı", "orta"),
        ("Adidas Stan Smith yeşil detaylı sneaker", "Orijinal, faturası duruyor. Burun kısmında çok hafif kırışıklık.", "ayakkabı", "38", "iyi", 1800, "sneaker", "orta"),
        ("Skechers hafızalı taban yürüyüş ayakkabısı", "Gri-pembe, çok rahat. Numarası büyük geldi, 2 kez giyildi.", "ayakkabı", "38", "yeni gibi", 1300, "yürüyüş ayakkabısı", "orta"),
        ("Dr. Martens 1460 siyah bot", "8 delikli klasik model. Deri bakımı yapıldı, tabanı yeni gibi.", "ayakkabı", "38", "iyi", 3500, "siyah bot", "orta"),
        ("Converse Chuck Taylor kırmızı keten ayakkabı", "Bilekli model, bağcıkları yeni. Az kullanıldı.", "ayakkabı", "38", "az kullanılmış", 900, "keten ayakkabı", "orta"),
    ],
    "s04": [
        ("Mango siyah omuz çantası", "Zincir askılı, kapaklı model. İç astarı temiz, toz torbasıyla gönderilir.", "çanta", None, "az kullanılmış", 750, "omuz çantası", "orta"),
        ("Fjällräven Kanken bordo sırt çantası", "Orijinal, 16 litre. Okulda bir dönem kullanıldı, fermuarlar sağlam.", "çanta", None, "iyi", 1600, "sırt çantası", "orta"),
        ("Derimod hakiki deri kadın cüzdan", "Taba rengi, çok bölmeli. Hediye geldi, kutusunda.", "çanta", None, "yeni etiketli", 550, "deri cüzdan", "küçük"),
        ("Zara hasır el çantası", "Yazlık, bambu saplı. Tek sezon kullanıldı.", "çanta", None, "az kullanılmış", 480, "hasır çanta", "orta"),
        ("Koton bez tote çanta", "Krem rengi, baskılı. Fermuarlı iç cebi var.", "çanta", None, "yeni gibi", 190, "tote çanta", "küçük"),
    ],
    "s05": [
        ("Ray-Ban Wayfarer güneş gözlüğü", "Orijinal, kılıfı ve bezi mevcut. Camlarda çizik yok.", "aksesuar", None, "az kullanılmış", 2800, "güneş gözlüğü", "küçük"),
        ("Vakko lacivert ipek fular", "90x90, desenli. Kutusunda, hiç kullanılmadı.", "aksesuar", None, "yeni etiketli", 1200, "ipek fular", "küçük"),
        ("Hakiki deri kahverengi kemer", "4 cm genişlik, 105 cm. Tokasında çizik yok.", "aksesuar", None, "iyi", 300, "deri kemer", "küçük"),
        ("Casio vintage altın rengi kol saati", "A168 model, pili yeni değişti. Kordon tam boy.", "aksesuar", None, "az kullanılmış", 1100, "kol saati", "küçük"),
        ("Gümüş halka küpe", "925 ayar, küçük boy. Kutusunda gönderilir.", "aksesuar", None, "yeni gibi", 220, "halka küpe", "küçük"),
    ],
    "s06": [
        ("İpekyol bej triko kazak", "Yün karışımlı, boğazlı. Kuru temizlemeden çıktı.", "kadın giyim", "S", "az kullanılmış", 600, "triko kazak", "orta"),
        ("Network camel kaşe kaban", "Diz üstü, kuşaklı. İki sezon giyildi, astarı sağlam.", "kadın giyim", "S", "iyi", 3200, "kaşe kaban", "büyük"),
        ("Stradivarius siyah pileli etek", "Midi boy, beli lastikli. Birkaç kez giyildi.", "kadın giyim", "S", "az kullanılmış", 350, "pileli etek", "küçük"),
        ("Massimo Dutti lacivert blazer ceket", "Tek düğmeli, astarlı. Ofis için alındı, çok az giyildi.", "kadın giyim", "S", "yeni gibi", 1900, "blazer ceket", "orta"),
        ("Mango krem saten bluz", "Dökümlü, gizli düğmeli. Bir kez giyildi.", "kadın giyim", "S", "yeni gibi", 450, "saten bluz", "küçük"),
    ],
    "s07": [
        ("Altınyıldız beyaz klasik gömlek", "Slim fit, pamuklu. Ütülü ve temiz gönderilir.", "erkek giyim", "M", "az kullanılmış", 450, "klasik gömlek", "küçük"),
        ("Dockers bej chino pantolon", "31/32, düz kesim. Rengi canlı, diz izi yok.", "erkek giyim", "31/32", "az kullanılmış", 800, "chino pantolon", "orta"),
        ("Hotiç kahverengi deri oxford ayakkabı", "Bağcıklı klasik model. Düğünde bir kez giyildi.", "ayakkabı", "42", "yeni gibi", 1700, "oxford ayakkabı", "orta"),
        ("Pierre Cardin bordo ipek kravat", "Kutusunda, desenli. Hiç takılmadı.", "aksesuar", None, "yeni etiketli", 280, "kravat", "küçük"),
        ("Kiğılı lacivert takım elbise", "Ceket ve pantolon, 50 beden. Bir düğünde giyildi.", "erkek giyim", "50", "yeni gibi", 3900, "takım elbise", "orta"),
    ],
    "s08": [
        ("Oleg Cassini zümrüt yeşili abiye elbise", "Uzun, saten, yırtmaçlı. Tek gece giyildi, kuru temizleme yapıldı.", "kadın giyim", "36", "yeni gibi", 4500, "abiye elbise", "orta"),
        ("Nine West gümüş topuklu ayakkabı", "8 cm ince topuk. Abiyeyle birlikte bir kez giyildi.", "ayakkabı", "37", "yeni gibi", 1400, "topuklu ayakkabı", "orta"),
        ("Gümüş taşlı clutch çanta", "Zincir askısı içinde. Davet için alındı, tek kullanım.", "çanta", None, "yeni gibi", 650, "clutch çanta", "küçük"),
        ("Siyah saten omuz şalı", "Geniş, abiye üstüne uygun. Lekesiz.", "aksesuar", None, "az kullanılmış", 320, "saten şal", "küçük"),
        ("İnci detaylı saç tokası", "Düğün için alındı, bir kez takıldı.", "aksesuar", None, "yeni gibi", 150, "saç tokası", "küçük"),
    ],
    "s09": [
        ("Nike Pro siyah spor tayt", "Yüksek bel, toparlayıcı. Dikişlerinde açılma yok.", "kadın giyim", "S", "az kullanılmış", 700, "spor tayt", "küçük"),
        ("Adidas pembe spor atlet", "Hızlı kuruyan kumaş. İki kez giyildi.", "kadın giyim", "S", "yeni gibi", 400, "spor atlet", "küçük"),
        ("Asics Gel-Contend koşu ayakkabısı", "Mor-beyaz, yaklaşık 50 km koşuldu. Taban dişleri duruyor.", "ayakkabı", "37", "iyi", 1900, "koşu ayakkabısı", "orta"),
        ("Puma fermuarlı eşofman üstü", "Gri, cepli. Bol kalıp.", "kadın giyim", "S", "az kullanılmış", 650, "eşofman üstü", "orta"),
        ("Decathlon mor yoga matı çantası", "Askılı, mat dahil değil. Bir kez kullanıldı.", "çanta", None, "yeni gibi", 240, "yoga çantası", "küçük"),
    ],
    "s10": [
        ("Derimod hakiki deri erkek ceket", "Siyah, biker model. Derisi yumuşak, çatlama yok.", "erkek giyim", "L", "iyi", 5200, "erkek deri ceket", "orta"),
        ("Timberland sarı erkek bot", "Klasik 6 inç model. Su geçirmez, tabanı sağlam.", "ayakkabı", "43", "iyi", 3800, "erkek bot", "orta"),
        ("Mavi yün atkı ve bere takımı", "Antrasit, hediye paketinde. Hiç kullanılmadı.", "aksesuar", None, "yeni etiketli", 450, "atkı bere", "küçük"),
        ("The North Face siyah polar", "Yarım fermuarlı, kalın. Bir kış giyildi.", "erkek giyim", "L", "az kullanılmış", 1600, "polar", "orta"),
        ("Deri erkek eldiven", "Siyah, içi astarlı. Bir kez takıldı.", "aksesuar", None, "yeni gibi", 350, "deri eldiven", "küçük"),
    ],
    "s11": [
        ("Zara bej trençkot", "Kruvaze, kemerli. Bahar için ideal, iki sezon giyildi.", "kadın giyim", "M", "iyi", 1800, "trençkot", "orta"),
        ("Bambi siyah rugan babet", "Fiyonklu, çok rahat. Topuk lastiği yeni.", "ayakkabı", "38", "az kullanılmış", 500, "babet", "orta"),
        ("Koton kanvas alışveriş çantası", "Krem rengi, baskılı. Fermuarlı iç cebi var.", "çanta", None, "yeni gibi", 220, "kanvas çanta", "küçük"),
        ("Mango çizgili triko hırka", "Düğmeli, lacivert-beyaz. Birkaç kez giyildi.", "kadın giyim", "M", "az kullanılmış", 550, "triko hırka", "orta"),
    ],
    "s12": [
        ("Nike Tech Fleece gri eşofman takımı", "Üst ve alt, L beden. Orijinal, tüylenme yok.", "erkek giyim", "L", "az kullanılmış", 2600, "eşofman takımı", "orta"),
        ("Adidas Ultraboost siyah koşu ayakkabısı", "43 numara, 100 km kadar koşuldu.", "ayakkabı", "43", "iyi", 2900, "erkek koşu ayakkabısı", "orta"),
        ("Under Armour siyah spor şort", "Hızlı kuruyan, iç taytlı. İki kez giyildi.", "erkek giyim", "L", "yeni gibi", 450, "spor şort", "küçük"),
        ("Puma spor çorap 6'lı paket", "Kutusu açılmadı, 43-46 numara.", "aksesuar", None, "yeni etiketli", 180, "spor çorap", "küçük"),
    ],
    "s13": [
        ("Vakko yün karışımlı uzun hırka", "Bej, cepli, diz boyu. Bir kış giyildi.", "kadın giyim", "M", "iyi", 2100, "uzun hırka", "orta"),
        ("İpekyol boğazlı kaşmir kazak", "Gri, yumuşacık. Tüylenme yok.", "kadın giyim", "M", "az kullanılmış", 1300, "kaşmir kazak", "orta"),
        ("Örgü bere", "Ekru, ponponlu. Hiç takılmadı.", "aksesuar", None, "yeni etiketli", 170, "örgü bere", "küçük"),
        ("Yün karışımlı ekose atkı", "Kırmızı-yeşil desenli, püsküllü.", "aksesuar", None, "az kullanılmış", 260, "ekose atkı", "küçük"),
    ],
    "s14": [
        ("Vintage deri evrak çantası", "Kahverengi, 90'lardan kalma. Kilidi çalışıyor.", "çanta", None, "iyi", 1500, "evrak çantası", "orta"),
        ("Vintage Seiko otomatik kol saati", "Çalışır durumda, bakımı yeni yapıldı.", "aksesuar", None, "iyi", 3600, "otomatik saat", "küçük"),
        ("Vintage yuvarlak çerçeve gözlük", "Numarasız cam takılı, metal çerçeve.", "aksesuar", None, "iyi", 450, "yuvarlak gözlük", "küçük"),
        ("Vintage ipek erkek mendili", "Desenli, ceket cebi için. Ütülü.", "aksesuar", None, "az kullanılmış", 140, "mendil", "küçük"),
    ],
    "s15": [
        ("Carhartt kahverengi iş ceketi", "Kanvas, astarlı. Eskitme görünümü doğal.", "erkek giyim", "L", "iyi", 2700, "iş ceketi", "orta"),
        ("Dickies siyah geniş paça pantolon", "874 model, 32 bel. Az giyildi.", "erkek giyim", "32", "az kullanılmış", 900, "geniş paça pantolon", "orta"),
        ("Oversize baskılı grafik tişört", "Siyah, sırtında baskı. Bir kez yıkandı.", "erkek giyim", "XL", "yeni gibi", 300, "grafik tişört", "küçük"),
        ("New Era siyah beyzbol şapkası", "Ayarlanabilir, işlemeli logo. Birkaç kez takıldı.", "aksesuar", None, "az kullanılmış", 600, "beyzbol şapkası", "küçük"),
    ],
    "s16": [
        ("Mango beyaz keten şort", "Yüksek bel, kuşaklı. Bir yaz giyildi.", "kadın giyim", "M", "az kullanılmış", 400, "keten şort", "küçük"),
        ("Zara çiçekli askılı elbise", "Kısa boy, viskon. Tatilde iki kez giyildi.", "kadın giyim", "M", "az kullanılmış", 550, "askılı elbise", "küçük"),
        ("Hasır geniş kenarlı şapka", "Plaj için, siyah kurdeleli.", "aksesuar", None, "yeni gibi", 230, "hasır şapka", "küçük"),
        ("Hakiki deri bodrum sandalet", "El yapımı, taba rengi. Bir yaz giyildi.", "ayakkabı", "38", "iyi", 650, "bodrum sandalet", "orta"),
    ],
    "s17": [
        ("Camper kahverengi erkek loafer", "Süet, 42 numara. Birkaç kez giyildi.", "ayakkabı", "42", "az kullanılmış", 2300, "loafer", "orta"),
        ("Birkenstock Arizona erkek terlik", "Mantar taban, siyah. Bir yaz kullanıldı.", "ayakkabı", "42", "iyi", 1500, "erkek terlik", "orta"),
        ("Converse siyah bilekli erkek sneaker", "Chuck 70, 42 numara. Az kullanıldı.", "ayakkabı", "42", "az kullanılmış", 1400, "bilekli sneaker", "orta"),
    ],
    "s18": [
        ("Mango siyah şişme mont", "Uzun boy, kapüşonlu, kaz tüyü dolgulu. Bir kış giyildi.", "kadın giyim", "M", "iyi", 2800, "şişme mont", "büyük"),
        ("UGG bej kar botu", "Orijinal, 38 numara. İçi kürk, temiz.", "ayakkabı", "38", "iyi", 2400, "kar botu", "orta"),
        ("Polar boyunluk ve eldiven seti", "Gri, hiç kullanılmadı.", "aksesuar", None, "yeni etiketli", 210, "boyunluk eldiven", "küçük"),
    ],
    "s19": [
        ("Samsonite orta boy kabin valizi", "Dört tekerlekli, sert kasa. Birkaç seyahat yaptı.", "çanta", None, "iyi", 3200, "kabin valizi", "büyük"),
        ("Deuter 40 litre kamp sırt çantası", "Bel kemerli, yağmurluklu. Bir kampta kullanıldı.", "çanta", None, "iyi", 2100, "kamp çantası", "büyük"),
        ("Seyahat düzenleyici çanta seti", "4 parça, fermuarlı. Hiç kullanılmadı.", "çanta", None, "yeni etiketli", 350, "düzenleyici çanta", "küçük"),
    ],
    "s20": [
        ("Gümüş isim kolye", "925 ayar, zinciri 45 cm. Kutusunda.", "aksesuar", None, "yeni gibi", 480, "kolye", "küçük"),
        ("Altın kaplama zincir bileklik", "İnce model, kararma yok.", "aksesuar", None, "az kullanılmış", 320, "bileklik", "küçük"),
        ("Doğal taş yüzük", "Ayarlanabilir, ametist taşlı.", "aksesuar", None, "yeni gibi", 260, "taş yüzük", "küçük"),
    ],
    "s21": [
        ("Levi's 501 açık mavi kot pantolon", "Erkek, 32/32. Klasik kesim, defosuz.", "erkek giyim", "32/32", "iyi", 1100, "501 kot", "orta"),
        ("Levi's kot ceket", "Trucker model, M beden. Az giyildi.", "erkek giyim", "M", "az kullanılmış", 1400, "kot ceket", "orta"),
        ("Örgü kahverengi deri kemer", "Erkek, 100 cm. Tokası pirinç.", "aksesuar", None, "iyi", 280, "örgü kemer", "küçük"),
    ],
    "s22": [
        ("Pierre Cardin kadın el çantası", "Siyah, sert formlu. Bir sezon kullanıldı.", "çanta", None, "iyi", 900, "kadın el çantası", "orta"),
        ("Deri kartlık", "Bordo, 6 kart bölmeli. Hediye kutusunda.", "çanta", None, "yeni etiketli", 200, "kartlık", "küçük"),
        ("Zincir askılı mini çanta", "Krem rengi, kapitone. İki kez kullanıldı.", "çanta", None, "yeni gibi", 520, "mini çanta", "küçük"),
    ],
    "s23": [
        ("Penti siyah külotlu çorap 3'lü", "40 denye, paketi açılmadı.", "kadın giyim", "M", "yeni etiketli", 120, "külotlu çorap", "küçük"),
        ("Koton ribanalı body", "Siyah, uzun kollu. Bir kez giyildi.", "kadın giyim", "S", "yeni gibi", 210, "body", "küçük"),
        ("LC Waikiki örme ev pijaması", "Pembe, takım. Hiç giyilmedi.", "kadın giyim", "M", "yeni etiketli", 260, "pijama takımı", "küçük"),
    ],
    "s24": [
        ("Tommy Hilfiger lacivert polo tişört", "Erkek, M beden. Yakası formunu koruyor.", "erkek giyim", "M", "az kullanılmış", 900, "polo tişört", "küçük"),
        ("Gant beyaz oxford gömlek", "Regular fit, M beden. Ütülü gönderilir.", "erkek giyim", "M", "az kullanılmış", 1000, "oxford gömlek", "küçük"),
        ("U.S. Polo Assn. lacivert kazak", "V yaka, pamuklu. Bir kış giyildi.", "erkek giyim", "M", "iyi", 650, "v yaka kazak", "orta"),
    ],
    "s25": [
        ("Pandora gümüş charm bileklik", "Orijinal, 3 charm ile. Kutusu ve faturası var.", "aksesuar", None, "az kullanılmış", 2500, "charm bileklik", "küçük"),
        ("Swarovski kristal küpe", "Orijinal, kutusunda. Bir kez takıldı.", "aksesuar", None, "yeni gibi", 1300, "kristal küpe", "küçük"),
    ],
}


def _whole_tl_floor(list_price: float, ratio: float) -> float:
    """Alt sınırı tam liraya yuvarlar ve %70-85 aralığında tutar.

    Dolap'ta fiyatlar tam liradır. Kuruşlu bir alt sınır, satıcının tam liraya yuvarlanan son
    teklifinin alt sınırın birkaç kuruş altına düşmesine yol açabiliyordu.
    """
    low, high = math.ceil(0.70 * list_price), math.floor(0.85 * list_price)
    return float(min(max(round(ratio * list_price), low), high))


def build_listings(seed: int = SEED) -> list[Listing]:
    """Katalogdan 100 ilanı üretir.

    Alt sınır her ilan için liste fiyatının %70-85'i arasında rastgele (seed'li) belirlenir
    ve tam liraya yuvarlanır.
    Kargo ücreti ilanın paket boyutuna göre Dolap tarifesinden gelir; aynı satıcının
    ilanlarında farklı olabilir.
    """
    rng = random.Random(seed)
    listings: list[Listing] = []
    for seller_id, items in CATALOG.items():
        for title, description, category, size, condition, list_price, _need, package in items:
            listings.append(Listing(
                listing_id=f"L{len(listings) + 1:03d}",
                seller_id=seller_id,
                title=title,
                description=description,
                category=category,
                size=size,
                condition=condition,
                list_price=float(list_price),
                floor_price=_whole_tl_floor(list_price, rng.uniform(0.70, 0.85)),
                shipping_cost=SHIPPING_TARIFF[package],
            ))
    return listings


def build_sample(listings: list[Listing]) -> list[Listing]:
    """10 ilanlık alt küme: s01'in 5 ilanı, s02'nin 3 ilanı, s03 ve s04'ten birer ilan.

    ID'ler listings.json ile aynıdır; küçük dosyayla yazılan kod büyük dosyada da çalışır.
    """
    by_seller: dict[str, list[Listing]] = {}
    for l in listings:
        by_seller.setdefault(l.seller_id, []).append(l)
    return by_seller["s01"] + by_seller["s02"][:3] + [by_seller["s03"][0], by_seller["s04"][0]]


def _needs_by_listing(listings: list[Listing]) -> dict[str, str]:
    """listing_id -> katalogdaki ihtiyaç ifadesi (ilanlar katalog sırasıyla üretildiği için sıra eşleşir)."""
    needs = [item[6] for items in CATALOG.values() for item in items]
    return {l.listing_id: need for l, need in zip(listings, needs)}


def _package_shipping(items: list[Listing]) -> float:
    """Sepetin kargo ücreti: Dolap'ta sepet boyutu en büyük paket boyutudur.

    policy.package_shipping ile aynı tanım; data/ klasörü policy.py'ye bağımlı olmasın diye burada.
    """
    return max(l.shipping_cost for l in items)


def _buyer_shipping_at(price: float, package_shipping: float) -> float:
    """Alıcının bu fiyatta ödeyeceği kargo (Dolap "Kargo ücretini hangi durumlarda satıcı öder?"):
    250 TL altında tamamı, 250-399 TL arasında sabit 29,99 TL, 400 TL ve üzerinde 0.

    policy.buyer_shipping ile aynı kural; data/ klasörü policy.py'ye bağımlı olmasın diye burada.
    """
    if price >= 400:
        return 0.0
    if price >= 250:
        return 29.99
    return package_shipping


def build_scenarios(listings: list[Listing], seed: int = SEED,
                    n: int = 40, n_tight: int = 8) -> list[Scenario]:
    """40 senaryo üretir: 32'sinde paket kurulabilir, 8'inde bütçe yalnızca hedefe yeter.

    need_list = hedefin ifadesi + aynı satıcıdan 1-2 ürün + (bazen) başka satıcıdan bir çeldirici.

    Paketli senaryoda bütçe = (paketin liste toplamı + sepet kargosu) × U(1,00; 1,10).
    Bütçe bilerek bağlayıcı değil: alıcının sınırı iki modda da liste toplamı olur, böylece
    tek ürün ile paket arasındaki fark yalnızca paketin kendisinden (satıcının paket indirimi,
    tek kargo) gelir; bütçe tasarımından gelen yapay bir fark oluşmaz.

    Dar senaryoda alıcı ürüne en fazla liste fiyatının 0,8 katını öder (OG-Narrator'daki
    katsayı); bütçe = 0,8 × hedef liste fiyatı + alıcının o fiyatta Dolap kuralına göre
    ödeyeceği kargo. Bütçe burada bağlayıcıdır: alt sınırı listenin %80'inin üstünde olan
    ürünlerde anlaşma alanı (ZOPA) kalmaz ve doğru davranış anlaşmamaktır.

    Her senaryo alıcı modülünün select_bundle fonksiyonuyla denenir: paketli senaryoda birden
    fazla ürün, dar senaryoda yalnızca hedef seçilmiyorsa o hedef atlanıp başkası denenir.
    """
    rng = random.Random(seed)
    need_of = _needs_by_listing(listings)
    multi = sorted(multi_listing_sellers(listings))
    by_seller = {s: [l for l in listings if l.seller_id == s] for s in multi}
    tight_indexes = set(range(4, n, n // n_tight))  # dar senaryolar listeye dağılsın
    assert len(tight_indexes) == n_tight

    scenarios: list[Scenario] = []
    used_targets: set[str] = set()
    for i in range(n):
        tight = i in tight_indexes
        found = False
        # Satıcı sırası döner; uygun hedef bulunamazsa sıradaki satıcılar denenir.
        for offset in range(len(multi)):
            seller = multi[(i + offset) % len(multi)]
            own = by_seller[seller]
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
                if not candidates:
                    continue
                if tight:
                    product_max = 0.8 * target.list_price
                    scenario.budget = round(
                        product_max + _buyer_shipping_at(product_max, target.shipping_cost), 2)
                    ok = len(select_bundle(scenario, listings, "bundle")) == 1
                else:
                    items = [target, *candidates]
                    list_total = sum(l.list_price for l in items)
                    scenario.budget = float(round(
                        (list_total + _package_shipping(items)) * rng.uniform(1.00, 1.10)))
                    ok = len(select_bundle(scenario, listings, "bundle")) > 1
                if ok:
                    scenarios.append(scenario)
                    used_targets.add(target.listing_id)
                    found = True
                    break
            if found:
                break
        if not found:
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
    print(f"{len(listings)} ilan, {len({l.seller_id for l in listings})} satıcı, "
          f"{len(scenarios)} senaryo yazıldı.")


if __name__ == "__main__":
    main()
