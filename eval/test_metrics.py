"""metrics.py testleri. Çalıştırma (proje kökünden):  python -m pytest eval/

testdata/ içindeki 6 satırlık sonuç dosyası elle yazıldı:
  T1: liste 1000, alt sınır 800 | T2: liste 500, alt sınır 400 | kargo 50
  Asıl sistem
    T-SC1 single: T1, 900 TL       -> indirim (1000-900)/1000  = 0.10
    T-SC1 bundle: T1+T2, 1200 TL   -> indirim (1500-1200)/1500 = 0.20
    T-SC2 single: T1, 950 TL       -> indirim (1000-950)/1000  = 0.05  (bir ihlal içerir)
    T-SC2 bundle: anlaşma yok
  Yalnızca LLM (ikisi de bundle, ikisi de ihlalli)
    T-SC1 bundle: T1+T2, 1050 TL   -> indirim (1500-1050)/1500 = 0.30
    T-SC2 bundle: T1+T2, 1350 TL   -> indirim (1500-1350)/1500 = 0.10
"""
from pathlib import Path

import pytest

from eval.metrics import load_results, paired_test, summarize, violation_comparison

TESTDATA = Path(__file__).parent / "testdata"


@pytest.fixture
def df():
    return load_results(TESTDATA / "results_small.jsonl",
                        TESTDATA / "listings.json", TESTDATA / "scenarios.json")


@pytest.fixture
def summary(df):
    return summarize(df).set_index(["Sistem", "Mod"])


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


def test_utility(summary):
    # T-SC1 single: p_max = min(1600-50, 1000) = 1000, p_min = 800 -> (1000-900)/200 = 0.50
    # T-SC2 single: p_max = min(1100-50, 1000) = 1000            -> (1000-950)/200 = 0.25
    assert summary.loc[("Asıl sistem", "Tek ürün"), "Ort. alıcı faydası"] == pytest.approx(0.375)
    # T-SC1 bundle: p_max = min(1550, 1500) = 1500, p_min = 1200 -> (1500-1200)/300 = 1.0
    assert summary.loc[("Asıl sistem", "Paket"), "Ort. alıcı faydası"] == pytest.approx(1.0)


def test_paired_test_uses_only_main_system_scenarios_with_two_deals(df):
    # Asıl sistemde yalnızca T-SC1 iki modda da anlaşmayla bitti
    assert paired_test(df)["n"] == 1


def test_violation_comparison_in_bundle_mode(df):
    # Paket modu: asıl sistem 0/2 ihlalli, yalnızca LLM 2/2 ihlalli
    table = violation_comparison(df).set_index("Sistem")
    assert table.loc["Asıl sistem", "İhlalli çalıştırma"] == 0
    assert table.loc["Asıl sistem", "İhlal oranı (%)"] == pytest.approx(0.0)
    assert table.loc["Yalnızca LLM", "Çalıştırma (n)"] == 2
    assert table.loc["Yalnızca LLM", "İhlal oranı (%)"] == pytest.approx(100.0)
