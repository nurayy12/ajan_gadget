"""metrics.py testleri. Çalıştırma (proje kökünden):  python -m pytest eval/

testdata/ içindeki 4 satırlık sonuç dosyası elle yazıldı:
  T1: liste 1000, alt sınır 800 | T2: liste 500, alt sınır 400 | kargo 50
  T-SC1 single: T1, 900 TL       -> indirim (1000-900)/1000  = 0.10
  T-SC1 bundle: T1+T2, 1200 TL   -> indirim (1500-1200)/1500 = 0.20
  T-SC2 single: T1, 950 TL       -> indirim (1000-950)/1000  = 0.05  (bir ihlal içerir)
  T-SC2 bundle: anlaşma yok
"""
from pathlib import Path

import pytest

from eval.metrics import load_results, paired_test, summarize

TESTDATA = Path(__file__).parent / "testdata"


@pytest.fixture
def summary():
    df = load_results(TESTDATA / "results_small.jsonl",
                      TESTDATA / "listings.json", TESTDATA / "scenarios.json")
    return summarize(df).set_index("Koşul")


def test_deal_rate(summary):
    # Tek ürün: 2/2 anlaşma; paket: 1/2 anlaşma
    assert summary.loc["Tek ürün", "Anlaşma oranı (%)"] == pytest.approx(100.0)
    assert summary.loc["Paket", "Anlaşma oranı (%)"] == pytest.approx(50.0)


def test_mean_discount(summary):
    # Tek ürün: (0.10 + 0.05) / 2 = 0.075; paket: yalnızca 0.20
    assert summary.loc["Tek ürün", "Ort. indirim (%)"] == pytest.approx(7.5)
    assert summary.loc["Paket", "Ort. indirim (%)"] == pytest.approx(20.0)


def test_utility_violation_and_shipping(summary):
    # Fayda, T-SC1 single: p_max = min(1600-50, 1000) = 1000, p_min = 800 -> (1000-900)/200 = 0.50
    #        T-SC2 single: p_max = min(1100-50, 1000) = 1000            -> (1000-950)/200 = 0.25
    assert summary.loc["Tek ürün", "Ort. alıcı faydası"] == pytest.approx(0.375)
    # Fayda, T-SC1 bundle: p_max = min(1550, 1500) = 1500, p_min = 1200 -> (1500-1200)/300 = 1.0
    assert summary.loc["Paket", "Ort. alıcı faydası"] == pytest.approx(1.0)
    assert summary.loc["Tek ürün", "İhlal oranı (%)"] == pytest.approx(50.0)
    # Pakette 2 ürün tek kargoyla gitti: (2 - 1) * 50 = 50 TL tasarruf
    assert summary.loc["Paket", "Ort. kargo tasarrufu (TL)"] == pytest.approx(50.0)


def test_paired_test_uses_only_scenarios_with_two_deals():
    df = load_results(TESTDATA / "results_small.jsonl",
                      TESTDATA / "listings.json", TESTDATA / "scenarios.json")
    # Yalnızca T-SC1 iki koşulda da anlaşmayla bitti
    assert paired_test(df)["n"] == 1
