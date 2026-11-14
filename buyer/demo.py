"""Alıcı ajanını sahte satıcıyla çalıştırıp pazarlığı ekrana yazar.

Çalıştırma (proje klasöründen):  .\\.venv\\Scripts\\python.exe -m buyer.demo
Gerçek LLM için .env dosyasına ANTHROPIC_API_KEY yaz ve USE_MOCK_LLM=1 olmadan çalıştır.
"""
import os

os.environ.setdefault("USE_MOCK_LLM", "1")

from buyer.bundle import select_bundle
from buyer.report import buyer_report
from buyer.tests.fake_seller import run_fake_negotiation
from buyer.tests.sample_data import LISTINGS, make_scenario
from buyer.text_utils import format_tl


def show(mode: str, budget: float) -> None:
    scenario = make_scenario(budget)
    bundle = select_bundle(scenario, LISTINGS, mode)
    result = run_fake_negotiation(scenario, bundle, mode)
    print(f"\n===== mod: {mode}, bütçe: {format_tl(budget)} =====")
    for o in result.offers:
        who = "ALICI " if o.sender == "buyer" else "SATICI"
        print(f"tur {o.round} {who} {o.action:<8} {format_tl(o.price):>10}  {o.message}")
    print()
    print(buyer_report(result, LISTINGS))


if __name__ == "__main__":
    show("single", 1800)
    show("bundle", 1800)
