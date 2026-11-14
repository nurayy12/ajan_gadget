"""Arkadaşların satıcı ajanını beklemeden test etmek için sahte satıcı."""
from schemas import Listing, NegotiationResult, Offer, Scenario

from buyer.agent import buyer_turn


def fake_seller_turn(bundle: list[Listing], history: list[Offer], round: int) -> Offer:
    """İlk turda liste fiyatını söyler, sonraki her turda kendi son fiyatını %5 indirir."""
    list_total = sum(l.list_price for l in bundle)
    last = next((o for o in reversed(history) if o.sender == "seller"), None)
    price = list_total if last is None else last.price * 0.95
    price = float(f"{price:.2f}")
    return Offer(
        sender="seller",
        round=round,
        action="offer" if last is None else "counter",
        listing_ids=[l.listing_id for l in bundle],
        price=price,
        message=f"Fiyatım {price:.2f} TL.",
    )


def run_fake_negotiation(scenario: Scenario, bundle: list[Listing], mode: str = "single") -> NegotiationResult:
    """Alıcı ile sahte satıcıyı en çok 5 tur konuşturur (her turda önce alıcı)."""
    history: list[Offer] = []
    deal, final_price = False, None
    for r in range(1, 6):
        buyer_offer = buyer_turn(scenario, bundle, history, r)
        history.append(buyer_offer)
        if buyer_offer.action == "accept":
            deal, final_price = True, buyer_offer.price
            break
        history.append(fake_seller_turn(bundle, history, r))
    return NegotiationResult(
        scenario_id=scenario.scenario_id,
        mode=mode,
        deal=deal,
        final_price=final_price,
        listing_ids=[l.listing_id for l in bundle],
        rounds=history[-1].round,
        violations=[],
        offers=history,
    )
