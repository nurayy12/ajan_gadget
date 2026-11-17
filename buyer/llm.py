"""Alıcı mesajlarını yazan LLM katmanı.

LLM yalnızca Türkçe mesaj yazar; fiyatı kod hesaplar. LLM fiyatın yerine {FIYAT}
yer tutucusunu yazar, gerçek fiyatı agent.py koyar. Bütçe LLM'e hiç verilmez.

USE_MOCK_LLM=1 ise API çağrılmaz, şablon mesaj döner.
Model adı MODEL_NAME ortam değişkeninden okunur (varsayılan claude-haiku-5-5);
API anahtarı .env dosyasındaki ANTHROPIC_API_KEY'den gelir.
"""
import difflib
import os
import re
import random
import warnings

from schemas import Offer

from .tactics import TACTIC_GUIDE
from .text_utils import format_tl

PLACEHOLDER = "{FIYAT}"
DEFAULT_MODEL = "claude-haiku-5-5"

_SYSTEM = (
    "Sen ikinci el bir pazar yerinde alıcı adına pazarlık yapan bir asistansın. "
    "Satıcıya kısa (en çok 3 cümle), kibar ve doğal bir Türkçe mesaj yaz. "
    "Fiyatı mesajda tam olarak {FIYAT} şeklinde yaz; başka hiçbir fiyat ya da büyük sayı yazma. "
    "Ne kadar ödemeye hazır olduğun ya da bütçen hakkında hiçbir şey söyleme. "
    "Ürünler satıcının: onlardan 'ürününüz', 'ilanınızdaki ürün' ya da ürün adıyla bahset, 'ürünüm' deme. "
    "Başka bir site, uygulama ya da kargo firması adı yazma. Önceki mesajlarını tekrar etme. "
    "Yalnızca mesajın kendisini yaz; başlık, açıklama ya da tırnak ekleme."
)

# Kalite kontrolüne takılıp yeniden üretilen ya da şablona düşen alıcı mesajlarının sayımı (sorun -> adet).
BUYER_QUALITY_FALLBACKS: dict[str, int] = {}
_COMPANY_NAMES = re.compile(
    r"\b(hepsiburada|trendyol|dolap|n11|amazon|sahibinden|letgo|gardrops|yurti[çc]i|aras kargo|mng|ptt|"
    r"s[üu]rat|ups|dhl|getir|instagram|whatsapp)\b", re.IGNORECASE)


def _product_stems(titles: list[str]) -> set[str]:
    """Ürün adlarındaki isim kökleri ("çantası" -> "çanta"); 4 harften kısa olanlar atlanır."""
    stems = set()
    for title in titles:
        for word in re.findall(r"[a-zçğıöşü]+", title.lower()):
            for suffix in ("sı", "si", "su", "sü", "ı", "i", "u", "ü"):
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    word = word[: -len(suffix)]
                    break
            if len(word) >= 4:
                stems.add(word)
    return stems


def buyer_message_problem(message: str, titles: list[str], round_no: int, history: list[Offer],
                          last_round: bool = False) -> str | None:
    """Alıcı mesajında demo kalitesini bozan sorun varsa adını döndürür, yoksa None.

      bos          boş mesaj (ör. düşünme özellikli model metin üretemedi)
      firma        başka site, uygulama ya da kargo firması adı
      butce        bütçeden söz ediyor (bütçe gizli kalmalı)
      bakis_acisi  alıcı satıcının ürününden "çantam", "ürünlerim" diye bahsediyor
      son_teklif   son tur değilken "son teklif"
      tekrar       bir önceki alıcı mesajıyla neredeyse aynı
      meta         prompt'taki bilgi satırlarını tekrar ediyor ("Tek ürün olduğundan…")
    """
    text = message.strip()
    if not text:
        return "bos"
    low = text.lower()
    if _COMPANY_NAMES.search(low):
        return "firma"
    if "bütçe" in low:
        return "butce"
    for stem in _product_stems(titles) | {"ürün", "ürünler"}:
        if re.search(rf"\b{re.escape(stem)}(ler)?[ıiuü]?m(\b|[ıiuüae])", low):
            return "bakis_acisi"
    if not last_round and re.search(r"son teklif", low):
        return "son_teklif"
    if re.search(r"tek ürün olduğu|ürün sayısı|toplu alım:|bu turda kullanacağın|gerekçe:", low):
        return "meta"
    previous = [o.message for o in history if o.sender == "buyer"]
    if previous:
        norm = lambda t: " ".join(re.sub(r"[\d.,]+\s*(tl)?|\{fiyat\}", " ", t).split())
        a, b = norm(previous[-1].lower()), norm(low)
        if difflib.SequenceMatcher(None, a, b).ratio() > 0.7:
            return "tekrar"
    return None


def use_mock() -> bool:
    return os.getenv("USE_MOCK_LLM") == "1"


# Strateji başına birkaç farklı şablon (yedek de çeşitli olsun). Hepsi {FIYAT} içerir;
# 3+ haneli sayı ve "TL" yazmaz (agent.py yabancı fiyat denetimine takılmasın).
_TACTIC_TEMPLATES: dict[tuple[str, bool], list[str]] = {
    ("acilis", True): [
        "Merhaba, ilanlarınızdaki ürünlerin hepsi hoşuma gitti, birlikte almak istiyorum. Tek kargoyla göndermeniz işinizi kolaylaştırır; paket için {FIYAT} teklif ediyorum, uygun olur mu?",
        "Merhaba, ürünlerinizi tek seferde almak istiyorum. Hepsi tek kargo olacağı için sizin için de pratik; {FIYAT} teklif ediyorum, ne dersiniz?",
        "İyi günler, ilanlarınızdaki ürünler tam aradığım gibi. Hepsini birlikte alırsam tek paket olur; {FIYAT} yapabilir miyiz?",
    ],
    ("acilis", False): [
        "Merhaba, ilanınızdaki ürünü çok beğendim, durumu da güzel görünüyor. {FIYAT} teklif ediyorum, uygun olur mu?",
        "İyi günler, ürününüz tam aradığım gibi. Durumunu da göz önüne alarak {FIYAT} teklif etmek istiyorum.",
        "Merhaba, ilanınızla ilgileniyorum. Ürünün durumuna göre {FIYAT} uygun olur mu?",
    ],
    ("durum", True): [
        "Ürünler ikinci el olduğu için kullanım izi olabileceğini düşünüyorum, bu yüzden paket için {FIYAT} öneriyorum.",
        "İkinci el ürünlerde biraz yıpranma olması doğal; bu nedenle {FIYAT} fiyatı bana adil geliyor.",
        "Durumlarını da hesaba katınca {FIYAT} uygun bir seviye gibi duruyor, siz ne dersiniz?",
    ],
    ("durum", False): [
        "Ürün ikinci el olduğu için kullanım izi olabileceğini düşünüyorum, bu yüzden {FIYAT} öneriyorum.",
        "İkinci el üründe biraz yıpranma olması doğal; bu nedenle {FIYAT} bana adil geliyor.",
        "Ürünün durumunu da hesaba katınca {FIYAT} uygun görünüyor, siz ne dersiniz?",
    ],
    ("toplu_alim", True): [
        "Ürünleri birlikte aldığım için tek kargoyla halledebilirsiniz; bu yüzden {FIYAT} yapabilir miyiz?",
        "Hepsini bir arada alıyorum, sizin için tek paket ve tek kargo demek. {FIYAT} olursa çok iyi olur.",
        "Birden fazla ürün aldığım için paketi tek seferde gönderirsiniz; {FIYAT} fiyatına yaklaşabilir miyiz?",
    ],
    ("hizli_odeme", True): [
        "{FIYAT} üzerinden anlaşırsak ödemeyi hemen yapar, paketi satın alırım.",
        "Bugün anlaşabilirsek {FIYAT} fiyatına hemen satın almaya hazırım.",
        "{FIYAT} olursa vakit kaybetmeden alırım, tek seferde halledelim.",
    ],
    ("hizli_odeme", False): [
        "{FIYAT} üzerinden anlaşırsak ödemeyi hemen yapar, satın alırım.",
        "Bugün anlaşabilirsek {FIYAT} fiyatına hemen almaya hazırım.",
        "{FIYAT} olursa vakit kaybetmeden alırım, hemen halledelim.",
    ],
    ("karsilik", True): [
        "Fiyatta esnediğiniz için teşekkürler, ben de teklifimi {FIYAT} seviyesine yükseltiyorum.",
        "Siz fiyattan indirdiniz, ben de karşılık olarak {FIYAT} teklif ediyorum.",
        "Esnekliğiniz için sağ olun; karşılığında teklifimi {FIYAT} yapıyorum.",
    ],
    ("karsilik", False): [
        "Fiyatta esnediğiniz için teşekkürler, ben de teklifimi {FIYAT} seviyesine yükseltiyorum.",
        "Siz fiyattan indirdiniz, ben de karşılık olarak {FIYAT} teklif ediyorum.",
        "Esnekliğiniz için sağ olun; karşılığında teklifimi {FIYAT} yapıyorum.",
    ],
    ("yumusatma", True): [
        "Biraz daha yaklaşabilirsek anlaşmaya hazırım; paket için {FIYAT} olur mu?",
        "Ortada buluşabilirsek çok iyi olur, {FIYAT} fiyatına yaklaşabilir miyiz?",
        "Birbirimize biraz daha yaklaşırsak hemen kapatabiliriz; {FIYAT} nasıl olur?",
    ],
    ("yumusatma", False): [
        "Biraz daha yaklaşabilirsek anlaşmaya hazırım; {FIYAT} olur mu?",
        "Ortada buluşabilirsek çok iyi olur, {FIYAT} fiyatına yaklaşabilir miyiz?",
        "Birbirimize biraz daha yaklaşırsak hemen kapatabiliriz; {FIYAT} nasıl olur?",
    ],
    ("son_teklif", True): [
        "Bu benim son teklifim; paket için {FIYAT} olursa hemen anlaşabiliriz.",
        "Son olarak {FIYAT} önerebiliyorum, uygun görürseniz hemen kapatalım.",
        "Daha fazla yükseltemem; {FIYAT} olursa ürünleri hemen alırım.",
    ],
    ("son_teklif", False): [
        "Bu benim son teklifim; {FIYAT} olursa hemen anlaşabiliriz.",
        "Son olarak {FIYAT} önerebiliyorum, uygun görürseniz hemen kapatalım.",
        "Daha fazla yükseltemem; {FIYAT} olursa hemen alırım.",
    ],
}


def template_message(is_bundle: bool, round_no: int, tactic: str | None = None,
                     scenario_id: str = "") -> str:
    """Şablon mesaj (mock modu ve LLM hatasında yedek). Fiyat yerine {FIYAT} içerir.

    tactic verilirse o stratejinin birkaç şablonundan biri seçilir (seçim scenario_id + tur
    tohumuyla belirlenimcidir); verilmezse eski tek kalıplı şablon döner.
    """
    if tactic is not None:
        variants = _TACTIC_TEMPLATES.get((tactic, is_bundle)) or _TACTIC_TEMPLATES[(tactic, not is_bundle)]
        return random.Random(f"{scenario_id}:{round_no}:{tactic}:template").choice(variants)
    if round_no == 1:
        if is_bundle:
            return ("Merhaba, ilanlarınızdaki ürünleri birlikte almak istiyorum. "
                    "Toplu alım yaptığım için paket fiyatı olarak {FIYAT} teklif ediyorum. Uygun olur mu?")
        return "Merhaba, ilanınızdaki ürün için {FIYAT} teklif ediyorum. Uygun olur mu?"
    if is_bundle:
        return ("Teşekkürler. Ürünleri paket olarak aldığım için {FIYAT} fiyatına "
                "yaklaşabilirsek hemen anlaşabiliriz.")
    return "Teşekkürler. {FIYAT} fiyatına yaklaşabilirsek hemen anlaşabiliriz."


# İlk turdan sonra mesajın başındaki selamı siler: LLM her çağrıda konuşmaya yeni başlıyormuş gibi
# "Merhaba" yazabiliyor; gerçek bir sohbette selam yalnızca bir kez verilir.
_GREETING = re.compile(r"^\s*(merhaba(lar)?|selam(lar)?|iyi günler|iyi akşamlar)\s*[,!.]*\s*", re.IGNORECASE)


def strip_meta_lines(message: str) -> str:
    """LLM'in talimatı tekrar ettiği başlık satırlarını ve mesajı saran tırnakları siler.

    Örnek: "Anlaşırsak hemen satın alacağını söyleyerek satıcıya yazacağın mesaj:\n<asıl mesaj>"
    -> "<asıl mesaj>". İki noktayla biten ve ardından başka satır gelen satırlar başlık sayılır.
    """
    lines = [l.strip() for l in message.strip().splitlines() if l.strip()]
    while len(lines) > 1 and lines[0].endswith(":"):
        lines.pop(0)
    text = " ".join(lines)
    if len(text) > 1 and text[0] in "\"'“«" and text[-1] in "\"'”»":
        text = text[1:-1].strip()
    return text


_BUYER_GRAMMAR_FIXES = [("bilir mı", "bilir mi"), ("olur mı", "olur mu"), ("eder mısınız", "eder misiniz")]


def polish_buyer_message(message: str) -> str:
    """Küçük modelin sık yaptığı ünlü uyumu hatalarını düzeltir ("kabul edilebilir mı" -> "mi")."""
    for wrong, right in _BUYER_GRAMMAR_FIXES:
        message = message.replace(wrong, right)
    return message


def strip_greeting(message: str, round_no: int) -> str:
    """2. turdan itibaren mesajın başındaki selamı kaldırır ve ilk harfi büyütür."""
    if round_no <= 1:
        return message
    rest = _GREETING.sub("", message, count=1)
    if not rest or rest == message:
        return message
    return rest[0].upper() + rest[1:]


_NUMBER_WORDS = {1: "bir", 2: "iki", 3: "üç", 4: "dört", 5: "beş", 6: "altı", 7: "yedi",
                 8: "sekiz", 9: "dokuz", 10: "on"}


def build_prompt(titles: list[str], is_bundle: bool, round_no: int, history: list[Offer],
                 tactic: str | None = None, conditions: list[str] | None = None,
                 seller_dropped: bool = False, last_round: bool = False) -> str:
    """LLM'e giden kullanıcı mesajı. Fiyat dışında sayı ve bütçe içermez (sayılar kelimeyle)."""
    lines = [
        f"{'Alıcı' if o.sender == 'buyer' else 'Satıcı'} (tur {o.round}): "
        f"{o.message} [fiyat: {format_tl(o.price)}]"
        for o in history
    ]
    if conditions and len(conditions) == len(titles):
        items = "; ".join(f"{t} (durumu: {c})" for t, c in zip(titles, conditions))
    else:
        items = ", ".join(titles)
    count = _NUMBER_WORDS.get(len(titles), "birkaç")
    parts = [f"Ürünler: {items}"]
    if is_bundle:  # tek üründe bu satır yok: model "Tek ürün olduğundan…" diye prompt'u tekrar ediyordu
        parts.append(f"Ürün sayısı: {count}. Toplu alım: birden çok ürün birlikte alınıyor.")
    parts += [
        f"Tur: {round_no}" + (" (son tur)" if last_round else ""),
        ("Bu ilk mesajın; kısa bir selamla başlayabilirsin." if round_no <= 1 else
         "Selamlaşma ilk mesajda yapıldı; 'Merhaba' gibi bir selamla başlama, doğrudan konuya gir."),
    ]
    if tactic in TACTIC_GUIDE:
        desc, example = TACTIC_GUIDE[tactic]
        if tactic == "acilis" and not is_bundle:  # tek üründe paket/tek kargo anlatımı yok
            desc = "İlgini söyle, ürünün durumuna değin ve ilk teklifini ver."
            example = "Merhaba, ilanınızdaki ürünü beğendim, durumu da güzel görünüyor. {FIYAT} teklif ediyorum, uygun olur mu?"
        parts.append(f"Bu turda kullanacağın gerekçe: {desc}")
        parts.append(f"Örnek cümle (aynen kopyalama, kendi sözcüklerinle yaz): {example}")
    parts.append("Satıcı son turda fiyatını düşürdü." if seller_dropped
                 else "Satıcı son turda fiyatını düşürmedi.")
    parts.append(f"Şimdiye kadarki konuşma:\n{chr(10).join(lines) if lines else '(henüz konuşma yok)'}")
    parts.append("Yalnızca belirtilen gerekçeyle, bu tur için satıcıya yazacağın mesajı yaz. "
                 "Fiyatı {FIYAT} olarak yaz, başka sayı ya da bütçe yazma.")
    return "\n".join(parts)


def _real_message(titles: list[str], is_bundle: bool, round_no: int, history: list[Offer],
                  tactic: str | None = None, conditions: list[str] | None = None,
                  seller_dropped: bool = False, last_round: bool = False) -> str:
    from dotenv import load_dotenv
    import anthropic

    load_dotenv()
    client = anthropic.Anthropic()
    model = os.getenv("MODEL_NAME", DEFAULT_MODEL)
    prompt = build_prompt(titles, is_bundle, round_no, history, tactic, conditions,
                          seller_dropped, last_round)
    for _attempt in range(2):  # sorunlu mesajda bir kez daha üret, yine sorunluysa şablon (None)
        response = client.messages.create(
            model=model,
            max_tokens=250,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        # Düşünme (thinking) özellikli modeller (ör. gemma4) önce bir düşünme bloğu döndürebilir;
        # yalnızca metin bloklarını birleştir.
        text = "".join(getattr(b, "text", "") for b in response.content
                       if getattr(b, "type", "text") == "text").strip()
        text = polish_buyer_message(strip_greeting(strip_meta_lines(text), round_no))
        problem = buyer_message_problem(text, titles, round_no, history, last_round)
        if problem is None:
            return text
        BUYER_QUALITY_FALLBACKS[problem] = BUYER_QUALITY_FALLBACKS.get(problem, 0) + 1
    return None


def write_message(titles: list[str], is_bundle: bool, round_no: int, history: list[Offer],
                  tactic: str | None = None, conditions: list[str] | None = None,
                  seller_dropped: bool = False, scenario_id: str = "") -> str:
    """Fiyat yerine {FIYAT} içeren Türkçe mesaj döndürür (strateji kod tarafından verilir)."""
    if use_mock():
        return template_message(is_bundle, round_no, tactic, scenario_id)
    try:
        text = _real_message(titles, is_bundle, round_no, history, tactic, conditions,
                             seller_dropped, last_round=(tactic == "son_teklif"))
        return text if text is not None else template_message(is_bundle, round_no, tactic, scenario_id)
    except Exception as exc:  # ağ, anahtar, kota vb.: pazarlık durmasın
        warnings.warn(f"LLM çağrısı başarısız, şablon mesaj kullanıldı: {exc}")
        return template_message(is_bundle, round_no, tactic, scenario_id)
