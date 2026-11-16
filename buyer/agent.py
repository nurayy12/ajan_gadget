"""Alıcı ajanı: bir tur için karar verir ve teklif üretir."""
import re

from schemas import Listing, Offer, Scenario

from .llm import PLACEHOLDER, template_message, write_message
from .pricing import buyer_target_price
from .tactics import choose_buyer_tactic, seller_dropped_price
from .text_utils import format_tl

# Fiyat sayılabilecek sayılar: 3+ haneli sayı ya da yanında TL/lira/₺ olan sayı.
_PRICE_LIKE = re.compile(r"\d{3,}|\d+\s*(?:tl|lira|₺)", re.IGNORECASE)

# Değiştirmeden sonra mesajda kalan yer tutucu izi: çıplak BÜYÜK HARFLİ "FIYAT" ya da süslü
# parantez. IGNORECASE yok: "fiyat", "Fiyat", "fiyatı" gibi doğal Türkçe sözcükler yakalanmaz.
# Gemma bazen yer tutucuyu "{FIYAT}" yerine "FIYAT" diye yazıyor; hiçbir kural bunu yakalamıyordu.
_PLACEHOLDER_LEFTOVER = re.compile(r"\bF[İI]YAT\b|[{}]")


def _finalize_message(raw: str, price: float, is_bundle: bool, round_no: int,
                      fallback: str | None = None) -> str:
    """LLM mesajına kodun hesapladığı fiyatı koyar.

    LLM kendi fiyatını yazdıysa ya da değiştirmeden sonra mesajda çıplak FIYAT / süslü parantez
    kaldıysa şablon mesaja döner (fallback verilmişse o şablon, yoksa tur şablonu).
    """
    price_text = format_tl(price)
    if PLACEHOLDER in raw:
        message = raw.replace(PLACEHOLDER, price_text)
    else:
        message = raw.rstrip() + f" Teklifim: {price_text}."
    leftover = _PLACEHOLDER_LEFTOVER.search(message)
    if leftover or _PRICE_LIKE.search(message.replace(price_text, "")):
        message = (fallback or template_message(is_bundle, round_no)).replace(PLACEHOLDER, price_text)
    return message


def buyer_turn(scenario: Scenario, bundle: list[Listing], history: list[Offer], round: int) -> Offer:
    """Alıcının bu turdaki hamlesi.

    Satıcının son teklifi (offer/counter), bu turdaki hedef fiyatıma eşit ya da altındaysa kabul eder.
    Değilse hedef fiyatla karşı teklif verir (1. turda action="offer", sonrasında "counter").
    """
    listing_ids = [l.listing_id for l in bundle]
    target = buyer_target_price(scenario, bundle, round)
    last_seller = next((o for o in reversed(history) if o.sender == "seller"), None)

    if last_seller is not None and last_seller.action in ("offer", "counter") and last_seller.price <= target:
        return Offer(
            sender="buyer",
            round=round,
            action="accept",
            listing_ids=listing_ids,
            price=last_seller.price,
            message=f"Teklifiniz uygun, {format_tl(last_seller.price)} fiyatına anlaşabiliriz. Teşekkürler!",
        )

    is_bundle = len(bundle) > 1
    tactic = choose_buyer_tactic(round, is_bundle, history, bundle, scenario.scenario_id)
    raw = write_message(
        [l.title for l in bundle], is_bundle, round, history,
        tactic=tactic, conditions=[l.condition for l in bundle],
        seller_dropped=seller_dropped_price(history, bundle), scenario_id=scenario.scenario_id,
    )
    fallback = template_message(is_bundle, round, tactic, scenario.scenario_id)
    return Offer(
        sender="buyer",
        round=round,
        action="offer" if round == 1 else "counter",
        listing_ids=listing_ids,
        price=target,
        message=_finalize_message(raw, target, is_bundle, round, fallback=fallback),
    )
