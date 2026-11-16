"""metrics.py testleri. Çalıştırma (proje kökünden):  python -m pytest eval/

testdata/ içindeki 6 satırlık sonuç dosyası elle yazıldı (tekrar = 0):
  T1: liste 1000, alt sınır 800 | T2: liste 500, alt sınır 400 | kargo 50
  Paket indirimi (policy): 2 ürün %5 -> T1+T2 paket alt sınırı (800 + 400) × 0,95 = 1140
  Asıl sistem
    T-SC1 single: T1, 900 TL       -> indirim (1000-900)/1000  = 0.10
    T-SC1 bundle: T1+T2, 1200 TL   -> indirim (1500-1200)/1500 = 0.20
    T-SC2 single: T1, 950 TL       -> indirim (1000-950)/1000  = 0.05  (bir ihlal içerir)
    T-SC2 bundle: anlaşma yok
  Yalnızca LLM (ikisi de bundle, ikisi de ihlalli)
    T-SC1 bundle: T1+T2, 1050 TL   -> indirim 0.30; p_min 1140'ın altında: aralık dışı
    T-SC2 bundle: T1+T2, 1350 TL   -> indirim 0.10; bütçe 1100, p_max 1100'ün üstünde: aralık dışı
"""
from pathlib import Path

import pandas as pd
import pytest

from eval.metrics import (GAMMA, agenticpay_scores, distinct_n, load_results, paired_test,
                          per_scenario, shipping_saving, summarize, violation_comparison)
from schemas import Listing

TESTDATA = Path(__file__).parent / "testdata"


@pytest.fixture
def df():
    return load_results(TESTDATA / "results_small.jsonl",
                        TESTDATA / "listings.json", TESTDATA / "scenarios.json")


@pytest.fixture
def summary(df):
    return summarize(df).set_index(["Sistem", "Mod"])


def _listing(lid: str, price: float, ship: float = 39.99) -> Listing:
    return Listing(listing_id=lid, seller_id="x", title=lid, description="", category="c",
                   size=None, condition="iyi", list_price=price, floor_price=0.75 * price,
                   shipping_cost=ship)


def test_deal_rate(summary):
    # Asıl sistem: tek ürün 2/2, paket 1/2; yalnızca LLM paket 2/2
    assert summary.loc[("Asıl sistem", "Tek ürün"), "Anlaşma oranı (%)"] == pytest.approx(100.0)
    assert summary.loc[("Asıl sistem", "Paket"), "Anlaşma oranı (%)"] == pytest.approx(50.0)
    assert summary.loc[("Yalnızca LLM", "Paket"), "Anlaşma oranı (%)"] == pytest.approx(100.0)


def test_mean_discount(summary):
    # Asıl sistem tek ürün: (0.10 + 0.05) / 2 = 0.075; paket: yalnızca 0.20
    assert summary.loc[("Asıl sistem", "Tek ürün"), "Ort. indirim (%)"] == pytest.approx(7.5)
    assert summary.loc[("Asıl sistem", "Paket"), "Ort. indirim (%)"] == pytest.approx(20.0)
    # Yalnızca LLM paket: (0.30 + 0.10) / 2 = 0.20
    assert summary.loc[("Yalnızca LLM", "Paket"), "Ort. indirim (%)"] == pytest.approx(20.0)


def test_utility_uses_bundle_floor_and_affordable_price(summary):
    # T-SC1 single: p_max = min(1000, 1600) = 1000, p_min = 800 -> (1000-900)/200 = 0.50
    # T-SC2 single: p_max = min(1000, 1100) = 1000              -> (1000-950)/200 = 0.25
    assert summary.loc[("Asıl sistem", "Tek ürün"), "Ort. alıcı faydası"] == pytest.approx(0.375)
    # T-SC1 bundle: p_max = 1500, p_min = 1140 -> (1500-1200)/360
    assert summary.loc[("Asıl sistem", "Paket"), "Ort. alıcı faydası"] == pytest.approx(300 / 360)
    # Yalnızca LLM'in iki paket anlaşması da aralık dışı: fayda hesaplanmaz
    assert pd.isna(summary.loc[("Yalnızca LLM", "Paket"), "Ort. alıcı faydası"])
    assert summary.loc[("Yalnızca LLM", "Paket"), "Aralık dışı anlaşma"] == 2


def test_agenticpay_scores():
    # Geçerli anlaşma: 3. tur, r_b = 0.5 -> d = 0.99^2; alıcı = d·(30 + 55·0.5 + 15)
    d = GAMMA ** 2
    buyer, seller, overall = agenticpay_scores(True, 900, 800, 1000, rounds=3)
    assert buyer == pytest.approx(d * 72.5)
    assert seller == pytest.approx(d * 72.5)
    assert overall == pytest.approx(d * (30 + 55 + 15))   # 4·0.5·0.5 = 1
    # Anlaşma yok ya da aralık dışı: -15·(1 - 0.99^4)
    penalty = -15 * (1 - GAMMA ** 4)
    assert agenticpay_scores(False, None, 800, 1000, rounds=5) == (penalty,) * 3
    assert agenticpay_scores(True, 700, 800, 1000, rounds=2) == (penalty,) * 3


def test_shipping_saving_dolap_rule():
    # İki küçük paket, liste 200 + 150, paket fiyatı 300 TL.
    # Ayrı alım: 171,43 ve 128,57 TL -> ikisi de 250 altı -> 39,99 + 39,99
    # Paket: 300 TL -> paylaşımlı aralık -> alıcı 29,99. Tasarruf = 79,98 - 29,99
    items = [_listing("A", 200), _listing("B", 150)]
    assert shipping_saving(items, 300) == pytest.approx(79.98 - 29.99)
    assert shipping_saving(items[:1], 150) == 0.0


def test_per_scenario_averages_repeats():
    df = pd.DataFrame([
        {"scenario_id": "S", "system": "system", "mode": "single", "repeat": r, "deal": d,
         "discount": disc, "utility": float("nan"), "buyer_score": 0.0, "n_items": 1}
        for r, d, disc in [(0, True, 0.10), (1, True, 0.20), (2, False, float("nan"))]])
    row = per_scenario(df).iloc[0]
    assert row["deal_rate"] == pytest.approx(2 / 3)
    assert row["discount"] == pytest.approx(0.15)
    assert row["repeats"] == 3


def test_paired_test_uses_only_bundled_scenarios_with_two_deals(df):
    # Asıl sistemde paket kurulan ve iki modda da anlaşmayla biten yalnızca T-SC1 var
    assert paired_test(df)["n"] == 1


def test_violation_comparison_in_bundle_mode(df):
    # Paket modu: asıl sistem 0/2 ihlalli, yalnızca LLM 2/2 ihlalli
    table = violation_comparison(df).set_index("Sistem")
    assert table.loc["Asıl sistem", "İhlalli çalıştırma"] == 0
    assert table.loc["Yalnızca LLM", "Çalıştırma (n)"] == 2
    assert table.loc["Yalnızca LLM", "İhlal oranı (%)"] == pytest.approx(100.0)


def test_seller_gain_and_utility(summary):
    # T-SC1 bundle: fiyat 1200, paket alt sınırı 1140 -> satıcı kazancı 60 TL; r_s = 60/360
    assert summary.loc[("Asıl sistem", "Paket"), "Ort. satıcı kazancı (TL)"] == pytest.approx(60.0)
    assert summary.loc[("Asıl sistem", "Paket"), "Ort. satıcı faydası"] == pytest.approx(60 / 360)
    # Tek ürün: 900-800 = 100 ve 950-800 = 150 -> ortalama 125 TL
    assert summary.loc[("Asıl sistem", "Tek ürün"), "Ort. satıcı kazancı (TL)"] == pytest.approx(125.0)


def test_distinct_n_ignores_numbers():
    same = ["1200 TL teklif ediyorum", "1300 TL teklif ediyorum"]
    varied = ["1200 TL teklif ediyorum", "ürün çok temiz duruyor"]
    assert distinct_n(same, 2) == pytest.approx(3 / 6)     # 3 farklı ikili / 6 ikili
    assert distinct_n(varied, 2) > distinct_n(same, 2)
