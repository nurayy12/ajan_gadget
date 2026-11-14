"""Gerçek alıcı (buyer/) ve çekirdek (core/) modüllerini bağlayarak
data/sample_listings.json üzerinde bir senaryoyu hem 'single' hem 'bundle'
modunda çalıştırır; her turun teklifini, mesajını ve ihlalleri ekrana yazdırır.

Çalıştırma (proje kökünden):
  USE_MOCK_LLM=1 ile:
    $env:USE_MOCK_LLM="1"; python -m scripts.run_one
  Gerçek API ile (.env içinde ANTHROPIC_API_KEY varken):
    $env:USE_MOCK_LLM="0"; python -m scripts.run_one
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from schemas import Listing, Scenario
from buyer.bundle import select_bundle
from buyer.agent import buyer_turn
from core.engine import run_negotiation

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_LISTINGS_PATH = ROOT / "data" / "sample_listings.json"


def load_sample_listings(path: Path = SAMPLE_LISTINGS_PATH) -> list[Listing]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Listing.model_validate(item) for item in raw]


def build_sample_scenario() -> Scenario:
    """data/sample_listings.json içindeki s01 satıcısının ilanlarına uygun örnek senaryo."""
    return Scenario(
        scenario_id="SC_SAMPLE_01",
        need_list=["siyah deri ceket", "yüksek bel kot pantolon", "beyaz keten gömlek"],
        budget=2550.0,
        target_listing_id="L001",
    )


def run_mode(mode: Literal["single", "bundle"], listings: list[Listing], scenario: Scenario) -> None:
    print(f"\n{'=' * 65}")
    print(f"MOD: {mode.upper()} | Senaryo: {scenario.scenario_id} | Bütçe: {scenario.budget:.2f} TL")
    print(f"{'=' * 65}")

    result = run_negotiation(
        scenario=scenario,
        listings=listings,
        mode=mode,
        auto_approve=True,
        select_bundle_fn=select_bundle,
        buyer_turn_fn=buyer_turn,
    )

    print(f"Seçilen İlanlar : {result.listing_ids}")
    print("-" * 65)
    for offer in result.offers:
        who = "ALICI " if offer.sender == "buyer" else "SATICI"
        print(f"[Tur {offer.round}] {who} ({offer.action:<7}) | Fiyat: {offer.price:>8.2f} TL | Mesaj: {offer.message}")
    print("-" * 65)
    print(f"Anlaşma Durumu  : {'EVET' if result.deal else 'HAYIR'}")
    print(f"Nihai Fiyat     : {f'{result.final_price:.2f} TL' if result.final_price is not None else '-'}")
    print(f"Toplam Tur      : {result.rounds}")
    print(f"İhlaller        : {result.violations if result.violations else 'Yok ([])'}")


def main() -> None:
    listings = load_sample_listings()
    scenario = build_sample_scenario()
    for mode in ("single", "bundle"):
        run_mode(mode, listings, scenario)


if __name__ == "__main__":
    main()
