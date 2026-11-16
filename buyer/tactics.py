"""Alıcının her tur hangi gerekçeyi kullanacağını KOD seçer; LLM yalnızca o gerekçeyle yazar.

Fiyat yine pricing.py'de hesaplanır. Burası yalnızca mesajın stratejisini (gerekçesini) belirler:
strateji seçimi ile metin üretimi ayrıdır (He ve ark., EMNLP 2018). Pazarlık gerekçeleri
(durum, toplu alım, hızlı ödeme, karşılık verme, yumuşatma) Zhou ve ark. (2019) pazarlık
stratejileri ve DialoGraph'taki (Joshi ve ark., ICLR 2021) strateji etiketlerinden esinlenmiştir.

Seçim belirlenimcidir: tohum scenario_id + tur. Aynı strateji arka arkaya iki tur seçilmez.
Önceki turun stratejisi, o turdaki geçmiş yeniden kurularak hesaplanır (Offer'a alan eklenmez).
"""
import random

from schemas import Listing, Offer

from . import config

ACILIS = "acilis"
DURUM = "durum"
TOPLU_ALIM = "toplu_alim"
HIZLI_ODEME = "hizli_odeme"
KARSILIK = "karsilik"
YUMUSATMA = "yumusatma"
SON_TEKLIF = "son_teklif"

ALL_TACTICS = (ACILIS, DURUM, TOPLU_ALIM, HIZLI_ODEME, KARSILIK, YUMUSATMA, SON_TEKLIF)

# Strateji -> (kısa açıklama, Gemma'nın uyması için örnek cümle). Örneklerde fiyat yer tutucudur.
TACTIC_GUIDE: dict[str, tuple[str, str]] = {
    ACILIS: (
        "İlgini söyle; tek ürünse ürünün durumuna değin, paketse ürünleri birlikte almak istediğini "
        "ve satıcıya tek kargo kolaylığı olacağını belirt; ilk teklifini ver.",
        "Merhaba, ilanlarınızdaki ürünleri birlikte almak istiyorum, tek kargoyla göndermeniz de "
        "işinizi kolaylaştırır. {FIYAT} teklif ediyorum, uygun olur mu?",
    ),
    DURUM: (
        "Ürünün durumunu (ör. az kullanılmış, iyi) ve ikinci el olduğu için kullanım izi olabileceğini "
        "gerekçe göster.",
        "Ürün ikinci el olduğu için kullanım izi olabileceğini düşünüyorum, bu yüzden {FIYAT} öneriyorum.",
    ),
    TOPLU_ALIM: (
        "Birden çok ürünü birlikte alacağını ve satıcıya tek kargo kolaylığı sağlayacağını gerekçe göster.",
        "Ürünleri birlikte aldığım için tek kargoyla halledebilirsiniz; bu yüzden {FIYAT} yapabilir miyiz?",
    ),
    HIZLI_ODEME: (
        "Anlaşırsak hemen satın alacağını söyle.",
        "{FIYAT} üzerinden anlaşırsak ödemeyi hemen yapar, satın alırım.",
    ),
    KARSILIK: (
        "Satıcı fiyatını indirdi; sen de karşılık olarak teklifini yükselttiğini belirt.",
        "Fiyatta esnediğiniz için teşekkürler, ben de teklifimi {FIYAT} seviyesine yükseltiyorum.",
    ),
    YUMUSATMA: (
        "Biraz daha yaklaşabilirlerse anlaşabileceğini yumuşak bir dille söyle.",
        "Biraz daha yaklaşabilirsek anlaşmaya hazırım; {FIYAT} olur mu?",
    ),
    SON_TEKLIF: (
        "Bunun son teklifin olduğunu kibarca söyle.",
        "Bu benim son teklifim; {FIYAT} olursa hemen anlaşabiliriz.",
    ),
}


def seller_dropped_price(history: list[Offer], bundle: list[Listing]) -> bool:
    """Satıcı son turda fiyatını indirdi mi? (Sayı verilmez, yalnızca evet/hayır.)

    İki satıcı fiyatı varsa sonuncuyu bir öncekiyle karşılaştırır; yalnızca bir tane varsa
    liste fiyatı toplamıyla karşılaştırır (ilk karşı teklif listeden aşağıdaysa indirim sayılır).
    """
    prices = [o.price for o in history if o.sender == "seller" and o.action in ("offer", "counter")]
    if not prices:
        return False
    previous = prices[-2] if len(prices) >= 2 else sum(l.list_price for l in bundle)
    return prices[-1] < previous - 1e-9


def choose_buyer_tactic(round_no: int, is_bundle: bool, history: list[Offer],
                        bundle: list[Listing], scenario_id: str) -> str:
    """Bu turun gerekçesini seçer (belirlenimci; arka arkaya aynı strateji yok).

    1. tur "acilis", son tur (config.T) "son_teklif". 2.-4. turlarda uygun olanlar arasından:
    durum (pakette yeni ürün yoksa), toplu_alim (yalnızca pakette), hizli_odeme, karsilik (satıcı indirdiyse), yumusatma;
    bir önceki turun stratejisi hariç. Seçim tohumu scenario_id + tur.
    """
    if round_no <= 1:
        return ACILIS
    if round_no >= config.T:
        return SON_TEKLIF

    eligible = [HIZLI_ODEME, YUMUSATMA]
    # "Kullanım izi olabilir" gerekçesi yeni (yeni etiketli / yeni gibi) ürüne uymaz.
    if not any("yeni" in l.condition.lower() for l in bundle):
        eligible.insert(0, DURUM)
    if is_bundle:
        eligible.append(TOPLU_ALIM)
    if seller_dropped_price(history, bundle):
        eligible.append(KARSILIK)

    if round_no >= 3:
        before = [o for o in history if o.round < round_no - 1]
        previous = choose_buyer_tactic(round_no - 1, is_bundle, before, bundle, scenario_id)
        eligible = [t for t in eligible if t != previous]
    return random.Random(f"{scenario_id}:{round_no}:tactic").choice(eligible)
