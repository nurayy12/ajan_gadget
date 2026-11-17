"""opponent.py testleri. Çalıştırma (proje kökünden):  python -m pytest eval/test_opponent.py"""
from pathlib import Path

import pandas as pd
import pytest

import core.seller as seller_mod
from data.validate import load_listings
from eval.opponent import CLASSES, MAX_OFFERS, cross_validate, features, generate, models

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def listings():
    return load_listings(ROOT / "data" / "listings.json")


@pytest.fixture(scope="module")
def small(listings):
    return generate(listings, n_per_class=60, seed=7)


def test_generation_is_balanced_and_reproducible(listings, small):
    assert small["label"].value_counts().to_dict() == {c: 60 for c in CLASSES}
    again = generate(listings, n_per_class=60, seed=7)
    pd.testing.assert_frame_equal(small, again)


def test_seller_beta_is_restored(listings):
    before = seller_mod.SELLER_BETA
    generate(listings, n_per_class=3, seed=1)
    assert seller_mod.SELLER_BETA == before


def test_offers_never_increase_and_stay_below_list(small):
    for t in range(2, MAX_OFFERS + 1):
        assert (small[f"p{t}"] <= small[f"p{t - 1}"] + 1e-9).all()
    assert (small["p1"] <= small["list_total"] * 1.08).all()   # gürültü payıyla


def test_features_use_only_buyer_visible_information(small):
    X = features(small, 2)
    assert "beta" not in X.columns and "label" not in X.columns
    assert not any("floor" in c for c in X.columns)
    assert list(X.columns) == ["n_items", "log_list_total", "c1", "c2", "d2", "r"]


def test_conceder_concedes_more_than_boulware_on_first_offer(listings):
    clean = generate(listings, n_per_class=80, seed=3, noise=False)
    c1 = features(clean, 1).assign(label=clean["label"]).groupby("label")["c1"].mean()
    assert c1["boulware"] < c1["linear"] < c1["conceder"]


def test_models_beat_majority_baseline(small):
    table, _ = cross_validate(features(small, 2), small["label"], n_folds=3)
    table = table.set_index("Model")
    baseline = table.loc["Çoğunluk sınıfı (taban çizgisi)", "Accuracy"]
    assert baseline == pytest.approx(1 / 3, abs=0.02)
    learned = [m for m in models() if not m.startswith("Çoğunluk")]
    assert (table.loc[learned, "Accuracy"] > baseline + 0.2).all()
    assert ((table[["Accuracy", "Precision", "Recall", "F1", "ROC-AUC"]] >= 0)
            & (table[["Accuracy", "Precision", "Recall", "F1", "ROC-AUC"]] <= 1)).all().all()
