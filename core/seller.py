from __future__ import annotations

import os
import random
import re
import time
from dotenv import load_dotenv
from schemas import Listing, Offer
from policy import bundle_floor

load_dotenv()

# Sabitler (Dosya başında)
T_MAX: int = 5
# Genius / NegMAS standart Boulware taviz parametresi (Lin et al., 2014; Baarslag et al., 2014).
# Duyarlılık analizi (eval/) için çağrı anında modül üzerinden (SELLER_BETA) okunur.
SELLER_BETA: float = 0.2
DEFAULT_MODEL_NAME: str = "claude-haiku-5-5"
LLM_TIMEOUT_SECONDS: float = 15.0
LLM_MAX_RETRIES: int = 3
LLM_BACKOFF_BASE: float = 0.5

# Davranışsal sızıntı (Behavioral Privacy Leakage) koruması aralığı: u ~ U(0.01, 0.03)
# Kaynak: "Behavioral Privacy Leakage in Agentic Negotiation" (arXiv 2026).
PRIVACY_BUFFER_MIN: float = 0.01
PRIVACY_BUFFER_MAX: float = 0.03

# Son seller_turn çağrısında LLM 3 denemede de hata verdiyse True olur
_LAST_SELLER_LLM_FAILED: bool = False


def pop_seller_llm_error() -> bool:
    """Son seller_turn çağrısında 3 deneme sonunda LLM hatası olup olmadığını döndürür ve sıfırlar."""
    global _LAST_SELLER_LLM_FAILED
    val = _LAST_SELLER_LLM_FAILED
    _LAST_SELLER_LLM_FAILED = False
    return val


def format_price_tr(price: float) -> str:
    """Fiyatı alıcı tarafıyla aynı Türkçe biçime çevirir (örn. 1250.0 -> '1.250', 1250.5 -> '1.250,50')."""
    if abs(price - round(price)) < 0.005:
        s = f"{int(round(price)):,}"
    else:
        s = f"{price:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def seller_reservation_price(
    bundle: list[Listing],
    scenario_id: str = "",
    mode: str = "single",
) -> float:
    """
    Davranışsal sızıntıyı önlemek için satıcının 5. turdaki son hedef fiyatını
    bundle_floor × (1 + u), u ~ U(0.01, 0.03) olarak hesaplar.
    Rastgelelik scenario_id ve mode'dan türetilen seed ile tekrarlanabilirdir.
    Kaynak: "Behavioral Privacy Leakage in Agentic Negotiation" (arXiv 2026).
    """
    if not bundle:
        return 0.0
    eff_floor = bundle_floor(bundle)
    list_total = sum(item.list_price for item in bundle)
    seed_key = f"{scenario_id}:{mode}:{','.join(item.listing_id for item in bundle)}"
    rng = random.Random(seed_key)
    u = rng.uniform(PRIVACY_BUFFER_MIN, PRIVACY_BUFFER_MAX)
    res_price = eff_floor * (1.0 + u)
    return min(list_total, max(eff_floor, res_price))


def seller_target_price(
    bundle: list[Listing],
    round: int,
    scenario_id: str = "",
    mode: str = "single",
) -> float:
    """
    Zaman-bağımlı taviz fonksiyonu:
    fiyat(t) = başlangıç + (sınır - başlangıç) * (t / T) ** (1 / beta), T = 5
    - başlangıç = liste fiyatları toplamı
    - sınır     = bundle_floor(bundle) × (1 + u), u ~ U(0.01, 0.03) (davranışsal sızıntı korumalı)
    - beta      = SELLER_BETA (çağrı anında modülden okunur)
    Fiyat asla bundle_floor(bundle) altına inmez ve yasaklı floor_leak sayılarına eşitlenmez.
    """
    if not bundle:
        return 0.0

    start_price = sum(item.list_price for item in bundle)
    eff_floor = bundle_floor(bundle)
    raw_floor_sum = sum(item.floor_price for item in bundle)
    limit_price = seller_reservation_price(bundle, scenario_id=scenario_id, mode=mode)

    t = max(1, min(round, T_MAX))
    beta = SELLER_BETA  # Çağrı anında modül globalinden okunur (duyarlılık analizi için)
    raw_price = start_price + (limit_price - start_price) * ((t / T_MAX) ** (1.0 / beta))
    price = float(int(builtins_round(raw_price)))

    if price < eff_floor:
        price = float(int(builtins_round(eff_floor + 1.0)))
        if price < eff_floor:
            price += 1.0

    forbidden_floors = (
        {round_val(item.floor_price) for item in bundle}
        | {round_val(raw_floor_sum), round_val(eff_floor)}
    )
    while any(abs(price - fv) <= 0.02 for fv in forbidden_floors) and price < start_price:
        price += 1.0

    return price


def builtins_round(val: float) -> int:
    return int(val + 0.5)


def round_val(val: float) -> float:
    return float(f"{val:.2f}")


# --- Pazarlık stratejileri (satıcı) -------------------------------------------------------
# Fiyatı kod hesaplar; her tur hangi gerekçenin kullanılacağını da kod seçer, LLM yalnızca o
# gerekçeyle mesajı yazar. Strateji listesi Zhou ve ark. (2019) pazarlık stratejilerinden
# uyarlandı (ürünü tanıtma, cazip anlatma, kaygı giderme, yan teklif, yumuşatma; DialoGraph,
# Joshi ve ark., ICLR 2021, Tablo 7). Strateji ile metni ayırma: He ve ark. (EMNLP 2018).
# Her stratejinin şablonları LLM hata verdiğinde ya da mock modda kullanılır; şablonlarda
# fiyattan başka sayı yoktur ve uydurma iddia (ör. "başka alıcılar var") bulunmaz.
SELLER_TACTICS: dict[str, dict] = {
    "urun_tanit": {
        "aciklama": "Ürünü tanıt: markasını ve durumunu ilan açıklamasındaki bilgilerle anlat.",
        "sablonlar": [
            "Merhaba, {urun} {durum} ve tertemiz. Bu hâliyle {fiyat} uygun bir fiyat.",
            "Merhaba! {Urun} {durum}; fotoğraflarda gördüğünüz hâlinde. {fiyat}'ye verebilirim.",
        ],
    },
    "cazip_anlat": {
        "aciklama": "Ürünü daha çekici anlat: az kullanıldığını, temizliğini, yenisine göre avantajını vurgula.",
        "sablonlar": [
            "{Urun} {durum}, yenisine göre gerçekten avantajlı. {fiyat} yapabilirim.",
            "{Urun} hâlâ çok güzel duruyor; {fiyat} hakkını veren bir fiyat.",
        ],
    },
    "kaygi_gider": {
        "aciklama": "Alıcının olası kaygısını gider: orijinal, defosuz olduğunu, istenirse ek fotoğraf atabileceğini söyle.",
        "sablonlar": [
            "İçiniz rahat olsun, {urun} orijinal ve defosuz. {fiyat}'nin altına inmem zor.",
            "Herhangi bir kusuru yok, isterseniz ek fotoğraf da gönderirim. {fiyat} olur.",
        ],
    },
    "yan_teklif": {
        "aciklama": "Fiyat dışında bir kolaylık sun: aynı gün kargo, özenli paketleme; pakette hepsini tek kargoyla göndermek.",
        "sablonlar": [
            "{fiyat}'de anlaşırsak aynı gün özenle paketleyip kargoya veririm.",
            "{fiyat} olursa hemen hazırlarım, özenle paketleyip gönderirim.",
        ],
        "sablonlar_paket": [
            "Hepsini tek kolide, tek kargoyla gönderirim; {fiyat} olur.",
            "Paket olarak alırsanız hepsini özenle tek pakette yollarım. {fiyat} yapabilirim.",
        ],
    },
    "karsilik": {
        "aciklama": "Alıcı teklifini yükseltti; karşılık verdiğini söyle: o yaklaştığı için sen de indiriyorsun.",
        "sablonlar": [
            "Siz yaklaşınca ben de iniyorum: {fiyat}.",
            "Teklifinizi yükselttiğiniz için teşekkürler, ben de {fiyat}'ye iniyorum.",
        ],
    },
    "yumusatma": {
        "aciklama": "Kibarca biraz daha esneyebileceğini söyle.",
        "sablonlar": [
            "Biraz daha esneyebilirim, {fiyat} olur mu?",
            "Sizin için {fiyat}'ye kadar inebilirim.",
        ],
    },
    "son_fiyat": {
        "aciklama": "Bunun son fiyatın olduğunu kibarca ama net söyle.",
        "sablonlar": [
            "Bu benim son fiyatım: {fiyat}. Uygunsa hemen hazırlayayım.",
            "Daha fazla inemiyorum, son fiyatım {fiyat}.",
        ],
    },
    "kabul": {
        "aciklama": "Teklifi kabul et; sıcak bir kapanışla ürünü nasıl göndereceğini söyle.",
        "sablonlar": [
            "Anlaştık, {fiyat}! Özenle paketleyip en kısa sürede kargoya veriyorum.",
            "Harika, {fiyat}'de anlaştık. Siparişinizi hemen hazırlıyorum.",
        ],
    },
}
_MIDDLE_TACTICS = ["cazip_anlat", "kaygi_gider", "yan_teklif", "yumusatma"]


def _seed_key(bundle: list[Listing], round: int) -> str:
    """Strateji ve şablon seçimi için tekrarlanabilir tohum: paketteki ilanlar + tur."""
    return ",".join(sorted(item.listing_id for item in bundle)) + f":{round}"


def _buyer_raised(history: list[Offer]) -> bool:
    """Alıcının son teklifi bir önceki teklifinden yüksek mi (karşılık stratejisi için)."""
    buyer_prices = [o.price for o in history if o.sender == "buyer"]
    return len(buyer_prices) >= 2 and buyer_prices[-1] > buyer_prices[-2]


def choose_seller_tactic(bundle: list[Listing], history: list[Offer], round: int,
                         action: str = "counter") -> str:
    """Satıcının bu turdaki pazarlık stratejisi (belirlenimci; aynı strateji arka arkaya seçilmez).

    - kabul ederken "kabul", 5. turda "son_fiyat", 1. turda "urun_tanit"
    - 2.-4. turda: cazip_anlat, kaygi_gider, yan_teklif, yumusatma ve alıcı teklifini
      yükselttiyse karsilik arasından, bir önceki turun stratejisi hariç, tohumla seçilir.
    """
    if action == "accept":
        return "kabul"
    if round >= T_MAX:
        return "son_fiyat"
    if round <= 1:
        return "urun_tanit"
    previous_history = history[:-1] if history and history[-1].sender == "buyer" else history
    previous = choose_seller_tactic(bundle, previous_history, round - 1)
    candidates = list(_MIDDLE_TACTICS) + (["karsilik"] if _buyer_raised(history) else [])
    candidates = [c for c in candidates if c != previous]
    return random.Random(_seed_key(bundle, round)).choice(candidates)


def _condition_text(bundle: list[Listing]) -> str:
    """Şablon için durum ifadesi: tüm ürünlerin durumu aynıysa o, değilse "iyi durumda"."""
    conditions = {item.condition for item in bundle}
    condition = conditions.pop() if len(conditions) == 1 else "iyi"
    return {"iyi": "iyi durumda"}.get(condition, condition)


def _fill_template(template: str, bundle: list[Listing], price_str: str) -> str:
    """Şablondaki {urun}/{Urun}/{durum}/{fiyat} alanlarını doldurur."""
    plural = len(bundle) > 1
    urun = "ürünler" if plural else "ürün"
    return template.format(urun=urun, Urun=urun.capitalize(), durum=_condition_text(bundle),
                           fiyat=f"{price_str} TL")


def _tactic_templates(tactic: str, bundle: list[Listing]) -> list[str]:
    spec = SELLER_TACTICS[tactic]
    if len(bundle) > 1 and "sablonlar_paket" in spec:
        return spec["sablonlar_paket"]
    return spec["sablonlar"]


def _build_seller_prompt(
    bundle: list[Listing],
    history: list[Offer],
    target_price: float,
    action: str,
    tactic: str | None = None,
    round: int | None = None,
) -> str:
    """
    LLM için satıcı istemini (prompt) oluşturur.
    DİKKAT: Satıcının gizli alt sınırı (floor_price / bundle_floor) ASLA bu metne eklenmez!
    """
    items_desc = "; ".join(
        f"{item.title} ({item.condition}, Liste: {format_price_tr(item.list_price)} TL). "
        f"İlan açıklaması: {item.description}"
        for item in bundle
    )
    history_lines = []
    for h in history:
        who = "Alıcı" if h.sender == "buyer" else "Satıcı"
        history_lines.append(f"- Tur {h.round} ({who}): {h.message} [{format_price_tr(h.price)} TL]")
    history_text = "\n".join(history_lines) if history_lines else "Henüz mesaj yok."

    price_str = format_price_tr(target_price)
    if action == "accept":
        instruction = (
            f"Alıcının son teklifini ({price_str} TL) kabul ettiğini belirten "
            f"kısa, doğal bir Türkçe mesaj yaz. Mesajda yalnızca {price_str} TL fiyatını geçir, başka hiçbir sayı yazma."
        )
    else:
        instruction = (
            f"Bu turdaki karşı teklif fiyatın kesin olarak {price_str} TL'dir. "
            f"Kısa, kibar bir Türkçe pazarlık mesajı yaz. Mesajda yalnızca {price_str} TL fiyatını kullan, "
            f"başka hiçbir sayı veya fiyat yazma."
        )

    strategy_text = ""
    if tactic in SELLER_TACTICS:
        example = _fill_template(_tactic_templates(tactic, bundle)[0], bundle, price_str)
        strategy_text = (
            f"\nBu turdaki stratejin: {SELLER_TACTICS[tactic]['aciklama']}\n"
            f"Örnek (aynısını yazma, kendi cümlelerinle yaz): {example}\n"
            "Uydurma bilgi verme; yalnızca ilandaki bilgileri kullan. En çok 2 kısa cümle yaz."
        )
    return (
        f"Sen Dolap tarzı ikinci el bir pazar yerinde satıcısın.\n"
        f"Ürünler senin; onlardan 'ürünlerim', 'ürün' ya da 'ürünler' diye bahset, asla 'ürünleriniz' ya da "
        f"'ürününüz' deme. Alıcıya 'siz' diye hitap et.\n"
        + ("" if round is None else
           "Bu senin ilk mesajın; kısa bir selamla başlayabilirsin.\n" if round <= 1 else
           "Selamlaşma ilk mesajda yapıldı; 'Merhaba' gibi bir selamla başlama, doğrudan konuya gir.\n")
        + f"Satılan ürün(ler): {items_desc}\n"
        f"Geçmiş konuşma:\n{history_text}\n\n"
        f"Görev: {instruction}{strategy_text}"
    )


# İlk turdan sonra mesajın başındaki selamı siler: LLM her çağrıda konuşmaya yeni başlıyormuş gibi
# "Merhaba" yazabiliyor; gerçek bir sohbette selam yalnızca bir kez verilir.
_GREETING = re.compile(r"^\s*(merhaba(lar)?|selam(lar)?|iyi günler|iyi akşamlar)\s*[,!.]*\s*", re.IGNORECASE)


def strip_greeting(message: str, round_no: int) -> str:
    """2. turdan itibaren mesajın başındaki selamı kaldırır ve ilk harfi büyütür."""
    if round_no <= 1:
        return message
    rest = _GREETING.sub("", message, count=1)
    if not rest or rest == message:
        return message
    return rest[0].upper() + rest[1:]


# Satıcı kendi ürününden ikinci çoğul iyelikle ("ürünleriniz") söz ederse birinci tekile çevrilir.
# Kabul mesajında "ürünlerinizi kargoya veririm" doğru kullanım olduğu için orada uygulanmaz.
_SELLER_PERSPECTIVE_FIXES = [
    ("ürünlerinizin", "ürünlerimin"), ("ürünlerinizi", "ürünlerimi"), ("ürünleriniz", "ürünlerim"),
    ("ürününüzün", "ürünümün"), ("ürününüzü", "ürünümü"), ("ürününüz", "ürünüm"),
]


def _fix_seller_perspective(message: str, action: str) -> str:
    """Pazarlık mesajında satıcının kendi ürününe "ürünleriniz" demesini düzeltir (ilk harf korunur)."""
    if action == "accept":
        return message
    for wrong, right in _SELLER_PERSPECTIVE_FIXES:
        for w, r in ((wrong, right), (wrong.capitalize(), right.capitalize()),
                     ("Ü" + wrong[1:], "Ü" + right[1:])):
            message = message.replace(w, r)
    return message


def _template_seller_message(price_str: str, action: str, tactic: str | None = None,
                             bundle: list[Listing] | None = None, round: int = 1) -> str:
    """Stratejiye göre şablon mesaj (mock modda ve LLM hata verdiğinde).

    Aynı stratejinin birkaç şablonundan biri tohumla seçilir; böylece yedek mesajlar da tekrar etmez.
    Strateji ya da paket verilmezse eski davranış korunur.
    """
    if tactic is None or not bundle:
        if action == "accept":
            return f"Teklifiniz uygun, {price_str} TL üzerinden anlaşalım."
        return f"Ürünler çok temiz durumda, bu paket için {price_str} TL yapabilirim."
    options = _tactic_templates(tactic, bundle)
    template = random.Random(_seed_key(bundle, round) + tactic).choice(options)
    return _fill_template(template, bundle, price_str)


def generate_seller_message(
    bundle: list[Listing],
    history: list[Offer],
    target_price: float,
    action: str,
    round: int | None = None,
) -> str:
    """
    USE_MOCK_LLM=1 ise şablon mesaj döndürür.
    Aksi halde Anthropic SDK ile MODEL_NAME (varsayılan 'claude-haiku-5-5') modelini
    zaman aşımı (timeout) ve en fazla 3 denemeli, artan beklemeli (exponential backoff)
    yeniden deneme ile çağırır. Üçü de başarısızsa şablona düşer ve _LAST_SELLER_LLM_FAILED=True işaretler.
    """
    global _LAST_SELLER_LLM_FAILED
    _LAST_SELLER_LLM_FAILED = False

    price_str = format_price_tr(target_price)
    use_mock = os.getenv("USE_MOCK_LLM", "0") == "1"
    if round is None:  # verilmezse geçmişten çıkar: satıcının kaçıncı mesajı
        round = sum(1 for o in history if o.sender == "seller") + 1
    tactic = choose_seller_tactic(bundle, history, round, action)

    if use_mock:
        return _template_seller_message(price_str, action, tactic, bundle, round)

    prompt = _build_seller_prompt(bundle, history, target_price, action, tactic, round)
    model_name = os.getenv("MODEL_NAME", DEFAULT_MODEL_NAME)
    api_key = os.getenv("ANTHROPIC_API_KEY")

    for attempt in range(LLM_MAX_RETRIES):
        try:
            import anthropic  # type: ignore

            client = anthropic.Anthropic(api_key=api_key, timeout=LLM_TIMEOUT_SECONDS)
            response = client.messages.create(
                model=model_name,
                max_tokens=150,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            # Düşünme (thinking) özellikli modeller (ör. gemma4) önce bir düşünme bloğu döndürebilir;
            # yalnızca metin bloklarını birleştir.
            text = "".join(getattr(b, "text", "") for b in response.content
                           if getattr(b, "type", "text") == "text").strip()
            return strip_greeting(_fix_seller_perspective(text, action), round)
        except Exception:
            if attempt < LLM_MAX_RETRIES - 1:
                time.sleep(LLM_BACKOFF_BASE * (2 ** attempt))

    _LAST_SELLER_LLM_FAILED = True
    return _template_seller_message(price_str, action, tactic, bundle, round)


def seller_turn(
    bundle: list[Listing],
    history: list[Offer],
    round: int,
    scenario_id: str = "",
    mode: str = "single",
) -> Offer:
    """
    Satıcı ajanının tur hamlesini üretir:
    1. Hedef fiyatı taviz fonksiyonuyla hesaplar.
    2. Kabul kuralı (Baarslag ve ark., 2014 - "AC_next" kabul koşulu):
       Alıcının son teklifi, satıcının bu turda sunacağı hedef fiyata eşit veya üstündeyse
       (last_buyer_offer.price >= target) action='accept' döndürür.
    3. Değilse action='counter' (veya geçmişte teklif yoksa 'offer') ve Türkçe mesaj ile Offer döndürür.
    """
    target = seller_target_price(bundle, round, scenario_id=scenario_id, mode=mode)
    listing_ids = [item.listing_id for item in bundle]

    last_buyer_offer: Offer | None = None
    for off in reversed(history):
        if off.sender == "buyer":
            last_buyer_offer = off
            break

    # Baarslag ve ark. (2014) "AC_next" kabul stratejisi: karşı teklif >= bu turun hedef fiyatı ise kabul et
    if last_buyer_offer is not None and last_buyer_offer.price >= target:
        deal_price = last_buyer_offer.price
        msg = generate_seller_message(bundle, history, deal_price, action="accept", round=round)
        return Offer(
            sender="seller",
            round=round,
            action="accept",
            listing_ids=listing_ids,
            price=deal_price,
            message=msg,
        )

    action_type = "counter" if last_buyer_offer is not None else "offer"
    msg = generate_seller_message(bundle, history, target, action=action_type, round=round)
    return Offer(
        sender="seller",
        round=round,
        action=action_type,
        listing_ids=listing_ids,
        price=target,
        message=msg,
    )
