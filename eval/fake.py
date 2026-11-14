"""Gerçek pazarlık çekirdeği gelene kadar kullanılan sahte fonksiyonlar.

Üçü de gerçek fonksiyonlarla aynı imzaya sahiptir; run_experiments.py ve app.py
bunları parametre olarak alır, gerçekleri gelince yalnızca import satırı değişir.
LLM çağrısı yoktur; mesajlar şablondur.
"""
import random

from schemas import Listing, NegotiationResult, Offer, Scenario
from data.validate import bundle_candidates

T = 5  # en fazla tur sayısı
# İhlal kodları tahmindir; çekirdeği yazan arkadaşın kodlarıyla değiştir.
VIOLATION_BELOW_FLOOR = "below_floor"
VIOLATION_OVER_BUDGET = "over_budget"


def _concession(start: float, limit: float, t: int, total: int, beta: float) -> float:
    """Projedeki taviz formülü: fiyat(t) = başlangıç + (sınır - başlangıç) * (t/T)^(1/beta)."""
    return start + (limit - start) * (t / total) ** (1 / beta)


def fake_run_negotiation(scenario: Scenario, listings: list[Listing], mode: str,
                         auto_approve: bool = True) -> NegotiationResult:
    """Şemaya uygun, rastgele ama makul bir pazarlık sonucu üretir.

    - Seed senaryo ve moddan türetilir: aynı girdi her zaman aynı sonucu verir.
    - Paket modunda indirim biraz daha yüksektir (%12-24, tek üründe %8-18).
    - Yaklaşık %15 anlaşmasız biter, yaklaşık %12'sine bir ihlal eklenir.
    - auto_approve=False ise son teklif "accept" olsa bile deal=False döner;
      anlaşma fake_approve ile kesinleşir.
    """
    rng = random.Random(f"{scenario.scenario_id}-{mode}")
    by_id = {l.listing_id: l for l in listings}
    target = by_id[scenario.target_listing_id]

    # Paket modunda bütçe yetiyorsa aynı satıcının eşleşen ilanları eklenir.
    items = [target]
    if mode == "bundle":
        for cand in sorted(bundle_candidates(scenario, listings), key=lambda l: l.floor_price):
            floor_sum = sum(l.floor_price for l in items) + cand.floor_price
            if floor_sum + target.shipping_cost <= scenario.budget:
                items.append(cand)
    ids = [l.listing_id for l in items]
    list_total = sum(l.list_price for l in items)
    floor_total = sum(l.floor_price for l in items)
    p_max = min(scenario.budget - target.shipping_cost, list_total)

    # Bütçe alt sınırların toplamına yetmiyorsa anlaşma bölgesi yoktur.
    reaches_deal = rng.random() < 0.85 and p_max >= floor_total
    discount = rng.uniform(0.12, 0.24) if len(items) > 1 else rng.uniform(0.08, 0.18)
    final = min(max(list_total * (1 - discount), floor_total), p_max)

    violations: list[str] = []
    if reaches_deal and rng.random() < 0.12:
        over_budget_price = scenario.budget - target.shipping_cost + 50
        if rng.random() < 0.6 or over_budget_price >= list_total:
            final = floor_total * 0.95
            violations.append(VIOLATION_BELOW_FLOOR)
        else:
            final = over_budget_price
            violations.append(VIOLATION_OVER_BUDGET)
    final = round(final, 2)

    rounds = rng.randint(2, T)
    # Anlaşma yoksa alıcı alt sınırın altında kalır, satıcı alt sınırda durur: fiyatlar buluşmaz.
    buyer_end = final if reaches_deal else floor_total * 0.90
    seller_end = final if reaches_deal else floor_total
    names = ", ".join(l.title for l in items)

    offers: list[Offer] = []
    for r in range(1, rounds + 1):
        buyer_price = round(_concession(list_total * 0.60, buyer_end, r, rounds, beta=1.5), 2)
        offers.append(Offer(
            sender="buyer", round=r, action="offer" if r == 1 else "counter",
            listing_ids=ids, price=buyer_price,
            message=f"Merhaba, {names} için {buyer_price:.0f} TL teklif ediyorum, olur mu?"))
        if r < rounds:
            seller_price = round(_concession(list_total, seller_end, r, rounds, beta=0.8), 2)
            offers.append(Offer(
                sender="seller", round=r, action="counter", listing_ids=ids, price=seller_price,
                message=f"Ürünler çok temiz, en son {seller_price:.0f} TL yapabilirim."))
        elif reaches_deal:
            offers.append(Offer(
                sender="seller", round=r, action="accept", listing_ids=ids, price=final,
                message=f"Tamam, {final:.0f} TL'ye anlaştık. Hayırlı olsun!"))
        else:
            offers.append(Offer(
                sender="seller", round=r, action="reject", listing_ids=ids, price=seller_end,
                message="Kusura bakmayın, bu fiyata veremem."))

    return NegotiationResult(
        scenario_id=scenario.scenario_id, mode=mode,
        deal=reaches_deal and auto_approve,
        final_price=final if reaches_deal else None,
        listing_ids=ids, rounds=rounds, violations=violations, offers=offers)


def fake_approve(result: NegotiationResult, buyer_ok: bool, seller_ok: bool) -> NegotiationResult:
    """İki taraf da onayladıysa ve son teklif "accept" ise deal=True olan bir kopya döndürür."""
    accepted = bool(result.offers) and result.offers[-1].action == "accept"
    return result.model_copy(update={"deal": accepted and buyer_ok and seller_ok})


def fake_buyer_report(result: NegotiationResult, listings: list[Listing]) -> str:
    """Alıcı için kısa Türkçe özet: ürünler, liste toplamı, anlaşılan fiyat, kazanç."""
    by_id = {l.listing_id: l for l in listings}
    items = [by_id[i] for i in result.listing_ids]
    list_total = sum(l.list_price for l in items)
    lines = ["Ürünler: " + ", ".join(l.title for l in items),
             f"Liste toplamı: {list_total:.0f} TL"]
    if result.final_price is None:
        lines.append(f"Sonuç: {result.rounds} turda anlaşma sağlanamadı.")
    else:
        saving = list_total - result.final_price
        lines.append(f"Anlaşılan fiyat: {result.final_price:.0f} TL "
                     f"(kazanç {saving:.0f} TL, %{100 * saving / list_total:.1f})")
        lines.append(f"Kargo: {items[0].shipping_cost:.2f} TL (tek gönderi)")
        lines.append(f"Tur sayısı: {result.rounds}")
    return "\n".join(lines)
