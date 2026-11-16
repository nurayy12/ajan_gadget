from __future__ import annotations

import os
import random
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
    """Fiyatı temiz bir Türkçe metin biçimine çevirir (örn. 1250.0 -> '1250', 1250.5 -> '1250,50')."""
    if abs(price - round(price)) < 0.005:
        return str(int(round(price)))
    return f"{price:.2f}".replace(".", ",")


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


def _build_seller_prompt(
    bundle: list[Listing],
    history: list[Offer],
    target_price: float,
    action: str,
) -> str:
    """
    LLM için satıcı istemini (prompt) oluşturur.
    DİKKAT: Satıcının gizli alt sınırı (floor_price / bundle_floor) ASLA bu metne eklenmez!
    """
    items_desc = ", ".join(
        f"{item.title} ({item.condition}, Liste: {format_price_tr(item.list_price)} TL)"
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

    return (
        f"Sen Dolap tarzı ikinci el bir pazar yerinde satıcısın.\n"
        f"Satılan ürün(ler): {items_desc}\n"
        f"Geçmiş konuşma:\n{history_text}\n\n"
        f"Görev: {instruction}"
    )


def _template_seller_message(price_str: str, action: str) -> str:
    if action == "accept":
        return f"Teklifiniz uygun, {price_str} TL üzerinden anlaşalım."
    return f"Ürünler çok temiz durumda, bu paket için {price_str} TL yapabilirim."


def generate_seller_message(
    bundle: list[Listing],
    history: list[Offer],
    target_price: float,
    action: str,
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

    if use_mock:
        return _template_seller_message(price_str, action)

    prompt = _build_seller_prompt(bundle, history, target_price, action)
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
            return response.content[0].text.strip()
        except Exception:
            if attempt < LLM_MAX_RETRIES - 1:
                time.sleep(LLM_BACKOFF_BASE * (2 ** attempt))

    _LAST_SELLER_LLM_FAILED = True
    return _template_seller_message(price_str, action)


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
        msg = generate_seller_message(bundle, history, deal_price, action="accept")
        return Offer(
            sender="seller",
            round=round,
            action="accept",
            listing_ids=listing_ids,
            price=deal_price,
            message=msg,
        )

    action_type = "counter" if last_buyer_offer is not None else "offer"
    msg = generate_seller_message(bundle, history, target, action=action_type)
    return Offer(
        sender="seller",
        round=round,
        action=action_type,
        listing_ids=listing_ids,
        price=target,
        message=msg,
    )
