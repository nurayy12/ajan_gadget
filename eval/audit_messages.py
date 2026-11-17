"""Mesaj denetimi: gerçek LLM ile birkaç pazarlık yürütür ve sorunlu mesajları listeler.

Çalıştırma (proje kökünden, Ollama açıkken):
    python -m eval.audit_messages              # 10 senaryo x 2 mod
    python -m eval.audit_messages --limit 20

Her gönderilen mesaja şu denetimler uygulanır:
  - kural katmanı (core.rules.check): fiyat uyuşmazlığı, sızıntı, bütçe/alt sınır ihlali
  - dil denetimi: satıcı için core.seller.seller_message_problem, alıcı için
    buyer.llm.buyer_message_problem (firma adı, uydurma durum, bakış açısı, erken "son teklif", tekrar)
  - 1. turdan sonra "Merhaba" ile başlama, tek üründe "paket" kelimesi
Ayrıca kalite denetimine takılıp yeniden üretilen / şablona düşen mesaj sayıları ve şablonla
gönderilen mesaj oranı raporlanır. Çıktı: eval/out/audit.md (konuşmaların tamamı dahil).
"""
import argparse
import json
import re
from pathlib import Path

from schemas import Listing, Scenario
from buyer.agent import buyer_turn
from buyer.bundle import select_bundle
import buyer.llm as buyer_llm
import core.seller as seller_mod
from core.negotiation import run_negotiation
from core.rules import check

ROOT = Path(__file__).parent.parent
_GREETING = re.compile(r"^\s*(merhaba|selam|iyi günler)", re.IGNORECASE)


def _seller_templates() -> set[str]:
    """Satıcı şablonlarının sabit kısımları (doldurulmuş hâlleri eşleştirmek için)."""
    parts = set()
    for spec in seller_mod.SELLER_TACTICS.values():
        for key in ("sablonlar", "sablonlar_paket"):
            for tpl in spec.get(key, []):
                parts.add(re.split(r"\{", tpl)[0].strip()[:25] or tpl.split("}")[-1].strip()[:25])
    return {p for p in parts if len(p) >= 8}


def _buyer_templates() -> set[str]:
    return {re.split(r"\{", t)[0].strip()[:25] for v in buyer_llm._TACTIC_TEMPLATES.values() for t in v
            if len(re.split(r"\{", t)[0].strip()) >= 8}


def audit_offer(offer, scenario, bundle, history, n_items) -> list[str]:
    """Tek bir gönderilmiş mesajın sorunları."""
    issues = list(check(offer, scenario, bundle, history))
    if offer.sender == "seller":
        p = seller_mod.seller_message_problem(offer.message, bundle, history, offer.round, offer.action,
                                              offer.price)
    else:
        p = buyer_llm.buyer_message_problem(offer.message, [l.title for l in bundle], offer.round, history,
                                            last_round=offer.round >= 5)
    if p:
        issues.append(f"dil:{p}")
    if offer.round > 1 and _GREETING.match(offer.message):
        issues.append("selam_tekrari")
    if n_items == 1 and re.search(r"\bpaket(?!le)", offer.message.lower()):  # "paketleyip" fiili serbest
        issues.append("tek_urunde_paket")
    return issues


def run(limit: int, out_path: Path) -> dict:
    listings = [Listing(**l) for l in json.loads((ROOT / "data" / "listings.json").read_text(encoding="utf-8"))]
    scenarios = [Scenario(**s) for s in json.loads((ROOT / "data" / "scenarios.json").read_text(encoding="utf-8"))]
    by_id = {l.listing_id: l for l in listings}
    seller_tpl, buyer_tpl = _seller_templates(), _buyer_templates()

    totals = {"mesaj": 0, "sorunlu": 0, "satici_sablon": 0, "satici_mesaj": 0, "alici_sablon": 0, "alici_mesaj": 0}
    issue_counts: dict[str, int] = {}
    lines = ["# Mesaj denetimi", ""]
    for scenario in scenarios[:limit]:
        for mode in ("single", "bundle"):
            res = run_negotiation(scenario, listings, mode, auto_approve=True,
                                  select_bundle_fn=select_bundle, buyer_turn_fn=buyer_turn)
            bundle = [by_id[i] for i in res.listing_ids]
            lines += [f"## {scenario.scenario_id} / {mode} ({len(bundle)} ürün, anlaşma: {res.deal})", ""]
            for k, offer in enumerate(res.offers):
                issues = audit_offer(offer, scenario, bundle, res.offers[:k], len(bundle))
                totals["mesaj"] += 1
                side = "satici" if offer.sender == "seller" else "alici"
                totals[f"{side}_mesaj"] += 1
                pool = seller_tpl if side == "satici" else buyer_tpl
                if any(offer.message.startswith(p) or p in offer.message for p in pool):
                    totals[f"{side}_sablon"] += 1
                if issues:
                    totals["sorunlu"] += 1
                    for i in issues:
                        issue_counts[i] = issue_counts.get(i, 0) + 1
                flag = f"  **SORUN: {', '.join(issues)}**" if issues else ""
                lines.append(f"- {offer.sender} {offer.round}. tur ({offer.action}): {offer.message}{flag}")
            lines.append("")

    summary = [
        "## Özet", "",
        f"- Gönderilen mesaj: {totals['mesaj']}, sorunlu: {totals['sorunlu']}",
        f"- Sorun türleri: {issue_counts or 'yok'}",
        f"- Şablonla gönderilen (yaklaşık): satıcı {totals['satici_sablon']}/{totals['satici_mesaj']}, "
        f"alıcı {totals['alici_sablon']}/{totals['alici_mesaj']}",
        f"- Dil denetimine takılıp yeniden üretilen: satıcı {dict(seller_mod.SELLER_QUALITY_FALLBACKS)}, "
        f"alıcı {dict(buyer_llm.BUYER_QUALITY_FALLBACKS)}", "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines[:2] + summary + lines[2:]), encoding="utf-8")
    print("\n".join(summary))
    print(f"Konuşmaların tamamı: {out_path}")
    return {"totals": totals, "issues": issue_counts}


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerçek LLM mesajlarını denetle")
    parser.add_argument("--limit", type=int, default=10, help="Kaç senaryo (her biri 2 mod)")
    parser.add_argument("--out", default=ROOT / "eval" / "out" / "audit.md")
    args = parser.parse_args()
    run(args.limit, Path(args.out))


if __name__ == "__main__":
    main()
