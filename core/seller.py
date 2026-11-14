from __future__ import annotations

import os
import time
from dotenv import load_dotenv
from schemas import Listing, Offer

load_dotenv()

# Sabitler (Dosya başında)
T_MAX: int = 5
SELLER_BETA: float = 0.5  # Yavaş taviz (Boulware)
DEFAULT_MODEL_NAME: str = "claude-haiku-5-5"
LLM_TIMEOUT_SECONDS: float = 15.0
LLM_MAX_RETRIES: int = 3
LLM_BACKOFF_BASE: float = 0.5

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


def seller_target_price(bundle: list[Listing], round: int) -> float:
    """
    Zaman-bağımlı taviz fonksiyonu:
    fiyat(t) = başlangıç + (sınır - başlangıç) * (t / T) ** (1 / beta), T = 5
    başlangıç = liste fiyatları toplamı
    sınır     = alt sınırların toplamı
    """
    start_price = sum(item.list_price for item in bundle)
    limit_price = sum(item.floor_price for item in bundle)

    t = max(1, min(round, T_MAX))
    raw_price = start_price + (limit_price - start_price) * ((t / T_MAX) ** (1.0 / SELLER_BETA))
    price = float(int(builtins_round(raw_price)))

    forbidden_floors = {round_val(item.floor_price) for item in bundle} | {round_val(limit_price)}
    while round_val(price) in forbidden_floors and price < start_price:
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
    DİKKAT: Satıcının gizli alt sınırı (floor_price) ASLA bu metne eklenmez!
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
) -> Offer:
    """
    Satıcı ajanının tur hamlesini üretir:
    1. Hedef fiyatı taviz fonksiyonuyla hesaplar.
    2. Alıcının son teklifi bu turdaki hedef fiyata eşit veya üstündeyse action='accept' döndürür.
    3. Değilse action='counter' (veya geçmişte teklif yoksa 'offer') ve Türkçe mesaj ile Offer döndürür.
    """
    target = seller_target_price(bundle, round)
    listing_ids = [item.listing_id for item in bundle]

    last_buyer_offer: Offer | None = None
    for off in reversed(history):
        if off.sender == "buyer":
            last_buyer_offer = off
            break

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
