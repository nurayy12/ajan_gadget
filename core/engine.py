from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Literal
from schemas import Listing, NegotiationResult, Offer, Scenario
from policy import bundle_floor, buyer_shipping, max_affordable_price
from core.rules import check
from core.seller import format_price_tr, pop_seller_llm_error, seller_turn, T_MAX


def _default_select_bundle(
    scenario: Scenario,
    listings: list[Listing],
    mode: Literal["single", "bundle"],
) -> list[Listing]:
    """
    Eğer dışarıdan select_bundle verilmemişse önce buyer modülünden import etmeyi dener;
    buyer modülü henüz yoksa target_listing_id üzerinden temel seçimi yapar.
    """
    try:
        from buyer.bundle import select_bundle as buyer_select_bundle  # type: ignore

        return buyer_select_bundle(scenario, listings, mode)
    except ImportError:
        target = next((x for x in listings if x.listing_id == scenario.target_listing_id), None)
        if target is None:
            return listings[:1] if mode == "single" else listings
        if mode == "single":
            return [target]
        return [x for x in listings if x.seller_id == target.seller_id]


def _default_buyer_turn(
    scenario: Scenario,
    bundle: list[Listing],
    history: list[Offer],
    round: int,
) -> Offer:
    """Eğer dışarıdan buyer_turn verilmemişse buyer modülünden import eder."""
    try:
        from buyer.agent import buyer_turn as real_buyer_turn  # type: ignore

        return real_buyer_turn(scenario, bundle, history, round)
    except ImportError:
        from buyer import buyer_turn as real_buyer_turn  # type: ignore

        return real_buyer_turn(scenario, bundle, history, round)


def _sanitize_offer_with_template(
    offer: Offer,
    scenario: Scenario,
    bundle: list[Listing],
    history: list[Offer] | None = None,
) -> Offer:
    """
    İkinci denemede de kural ihlali devam ederse:
    - Fiyat sınır dışıysa güvenli sınıra çeker (max_affordable_price veya bundle_floor).
    - Sabit, temiz bir Türkçe şablon mesaj yazar.
    """
    eff_floor = bundle_floor(bundle)
    safe_price = offer.price

    if offer.sender == "buyer":
        max_allowed = max_affordable_price(bundle, scenario.budget)
        if safe_price + buyer_shipping(bundle, safe_price) > scenario.budget + 0.01:
            safe_price = max_allowed
        if abs(safe_price - scenario.budget) < 0.02:
            safe_price = max(0.0, round(safe_price - 1.0, 2))
    else:
        if safe_price < eff_floor:
            safe_price = round(eff_floor + 1.0, 2)

    safe_round = min(max(1, offer.round), T_MAX)
    price_str = format_price_tr(safe_price)

    if offer.sender == "seller":
        # Satıcının o turdaki stratejisine uygun, ürüne göre doldurulmuş şablon (tek üründe "paket" demez,
        # 1. turdan sonra "Merhaba" ile başlamaz).
        from .seller import _template_seller_message, choose_seller_tactic
        tactic = choose_seller_tactic(bundle, history or [], safe_round, offer.action)
        template_msg = _template_seller_message(price_str, offer.action, tactic, bundle, safe_round)
    elif offer.action == "accept":
        template_msg = f"Teklifinizi kabul ediyorum, {price_str} TL üzerinden anlaşalım."
    else:
        what = "bu ürünler" if len(bundle) > 1 else "bu ürün"
        template_msg = f"{what} için teklifim {price_str} TL."
        template_msg = ("Merhaba, " + template_msg) if safe_round <= 1 else template_msg[0].upper() + template_msg[1:]

    return Offer(
        sender=offer.sender,
        round=safe_round,
        action=offer.action,
        listing_ids=offer.listing_ids,
        price=safe_price,
        message=template_msg,
    )


def _append_trace(
    trace_path: str | Path | None,
    round_no: int,
    sender: str,
    price: float,
    message: str,
    violations: list[str],
) -> None:
    if trace_path is None:
        return
    p = Path(trace_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "round": round_no,
        "sender": sender,
        "price": price,
        "message": message,
        "violations": violations,
    }
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _call_seller(
    s_fn: Callable[..., Offer],
    bundle: list[Listing],
    history: list[Offer],
    round_no: int,
    scenario_id: str,
    mode: str,
) -> Offer:
    """Varsayılan seller_turn ise scenario_id ve mode geçirir, özel 3 argümanlı fonksiyonsa 3 argümanla çağırır."""
    if s_fn is seller_turn:
        return seller_turn(bundle, history, round_no, scenario_id=scenario_id, mode=mode)
    return s_fn(bundle, history, round_no)


def approve(
    result: NegotiationResult,
    buyer_ok: bool,
    seller_ok: bool,
) -> NegotiationResult:
    """
    Demo modunda (auto_approve=False) arayüzden alınan alıcı ve satıcı onayını uygular.
    İki taraf da onaylarsa (buyer_ok ve seller_ok True) ve geçerli bir final_price varsa
    deal=True olur; aksi halde deal=False yapılır.
    """
    approved_deal = bool(buyer_ok and seller_ok and result.final_price is not None)
    return NegotiationResult(
        scenario_id=result.scenario_id,
        mode=result.mode,
        deal=approved_deal,
        final_price=result.final_price if approved_deal else None,
        listing_ids=list(result.listing_ids),
        rounds=result.rounds,
        violations=list(result.violations),
        offers=list(result.offers),
    )


def run_negotiation(
    scenario: Scenario,
    listings: list[Listing],
    mode: Literal["single", "bundle"],
    auto_approve: bool = True,
    select_bundle_fn: Callable[[Scenario, list[Listing], Literal["single", "bundle"]], list[Listing]] | None = None,
    buyer_turn_fn: Callable[[Scenario, list[Listing], list[Offer], int], Offer] | None = None,
    seller_turn_fn: Callable[[list[Listing], list[Offer], int], Offer] | None = None,
    trace_path: str | Path | None = None,
) -> NegotiationResult:
    """
    Pazarlık döngüsünü çalıştırır:
    1. select_bundle ile paketi alır.
    2. 1'den 5'e kadar her turda önce buyer_turn, sonra seller_turn çağırır.
    3. Her tekliften sonra check() çalıştırır:
       - İhlal varsa result.violations listesine yazar ve teklifi 1 kez yeniden ürettirir.
       - Yeniden üretimde de ihlal varsa sabit şablon mesaj kullanır.
       - trace_path verilmişse her turu JSONL olarak dosyaya yazar.
    4. Bir taraf 'accept' derse döngü biter. 5 turda anlaşma yoksa deal=False döner.
    """
    sel_fn = select_bundle_fn or _default_select_bundle
    b_fn = buyer_turn_fn or _default_buyer_turn
    s_fn = seller_turn_fn or seller_turn

    bundle = sel_fn(scenario, listings, mode)
    listing_ids = [item.listing_id for item in bundle]

    history: list[Offer] = []
    all_violations: list[str] = []
    agreed_price: float | None = None
    last_round = 0

    for r in range(1, T_MAX + 1):
        last_round = r

        # --- 1. ALICI TURU ---
        b_turn_violations: list[str] = []
        b_offer = b_fn(scenario, bundle, history, r)
        b_violations = check(b_offer, scenario, bundle, history)
        if b_violations:
            all_violations.extend(b_violations)
            b_turn_violations.extend(b_violations)
            b_offer_retry = b_fn(scenario, bundle, history, r)
            b_violations_retry = check(b_offer_retry, scenario, bundle, history)
            if b_violations_retry:
                all_violations.extend(b_violations_retry)
                b_turn_violations.extend(b_violations_retry)
                b_offer = _sanitize_offer_with_template(b_offer_retry, scenario, bundle, history)
            else:
                b_offer = b_offer_retry

        history.append(b_offer)
        _append_trace(trace_path, r, b_offer.sender, b_offer.price, b_offer.message, b_turn_violations)

        if b_offer.action == "accept":
            agreed_price = b_offer.price
            break
        if b_offer.action == "reject":
            break

        # --- 2. SATICI TURU ---
        s_turn_violations: list[str] = []
        pop_seller_llm_error()
        s_offer = _call_seller(s_fn, bundle, history, r, scenario.scenario_id, mode)
        if pop_seller_llm_error():
            all_violations.append("llm_error")
            s_turn_violations.append("llm_error")

        s_violations = check(s_offer, scenario, bundle, history)
        if s_violations:
            all_violations.extend(s_violations)
            s_turn_violations.extend(s_violations)
            s_offer_retry = _call_seller(s_fn, bundle, history, r, scenario.scenario_id, mode)
            if pop_seller_llm_error():
                all_violations.append("llm_error")
                s_turn_violations.append("llm_error")
            s_violations_retry = check(s_offer_retry, scenario, bundle, history)
            if s_violations_retry:
                all_violations.extend(s_violations_retry)
                s_turn_violations.extend(s_violations_retry)
                s_offer = _sanitize_offer_with_template(s_offer_retry, scenario, bundle, history)
            else:
                s_offer = s_offer_retry

        history.append(s_offer)
        _append_trace(trace_path, r, s_offer.sender, s_offer.price, s_offer.message, s_turn_violations)

        if s_offer.action == "accept":
            agreed_price = s_offer.price
            break
        if s_offer.action == "reject":
            break

    # Sınırlar içinde geçerli bir anlaşma olup olmadığını doğrula (policy kurallarına göre)
    eff_floor = bundle_floor(bundle)
    within_bounds = (
        agreed_price is not None
        and (agreed_price + buyer_shipping(bundle, agreed_price) <= scenario.budget + 0.01)
        and (agreed_price >= eff_floor - 0.01)
    )

    if not within_bounds:
        deal = False
        final_price = None
    elif auto_approve:
        deal = True
        final_price = agreed_price
    else:
        deal = False
        final_price = agreed_price

    return NegotiationResult(
        scenario_id=scenario.scenario_id,
        mode=mode,
        deal=deal,
        final_price=final_price,
        listing_ids=listing_ids,
        rounds=last_round,
        violations=all_violations,
        offers=history,
    )
