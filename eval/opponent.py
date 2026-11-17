"""Rakip modelleme: satıcının taviz tipini ilk tekliflerinden tahmin eden sınıflandırıcı.

Çalıştırma (proje kökünden):  python -m eval.opponent
Çıktılar eval/out/opponent/ klasörüne yazılır: metrics.csv, summary.md, karmasiklik_matrisi.png,
dogruluk_teklif_sayisi.png.

Soru: Alıcı, satıcının ilk birkaç karşı teklifine bakarak satıcının ne kadar inatçı olduğunu
(taviz tipini) anlayabilir mi? Literatürde buna rakip modelleme denir (Baarslag vd. 2016).

Sınıflar (zamana bağlı taviz fonksiyonundaki β, Genius/NegMAS adlandırması):
  boulware  β ~ U(0,15; 0,60)   son turlara kadar az taviz
  linear    β ~ U(0,60; 1,60)   sabit hızla taviz
  conceder  β ~ U(1,60; 3,00)   erken taviz
Aralıklar bitişiktir; sınıf sınırına yakın satıcılar bilerek karışabilir.

Veri: Satıcı teklifleri çekirdeğin kendi fiyat fonksiyonuyla (core.seller.seller_target_price)
üretilir; LLM gerekmez. Görevi gerçekçi ve zor tutmak için:
  - β sabit üç değer yerine her sınıfın aralığından rastgele seçilir,
  - satıcının alt sınırı alıcıya görünmez (liste fiyatının %70-85'i arasında değişir), yani aynı
    taviz miktarı hem "inatçı satıcı, düşük alt sınır" hem "esnek satıcı, yüksek alt sınır" olabilir,
  - gizlilik payı u ~ U(0,01; 0,03) her pazarlıkta farklıdır,
  - teklifler insan satıcı gibi yarı olasılıkla 10 TL'ye yuvarlanır ve %2 (std) gürültü eklenir.
Özellikler yalnızca alıcının gördüğü bilgilerdir: liste toplamı, ürün sayısı, satıcının teklifleri.
Alt sınır ve β özelliklerde yer almaz.

Modeller: lojistik regresyon, random forest, çok katmanlı algılayıcı (MLP). 5 katlı tabakalı
çapraz doğrulama; Accuracy, makro Precision / Recall / F1, ROC-AUC (bire karşı hepsi, makro).
"""
import argparse
import random
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedKFold
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import core.seller as seller_mod
from data.validate import load_listings

ROOT = Path(__file__).parent.parent
SEED = 42
CLASSES = ["boulware", "linear", "conceder"]
CLASS_LABELS = {"boulware": "Boulware (inatçı)", "linear": "Doğrusal", "conceder": "Conceder (esnek)"}
BETA_RANGES = {"boulware": (0.15, 0.60), "linear": (0.60, 1.60), "conceder": (1.60, 3.00)}
MAX_OFFERS = 3          # alıcının gördüğü en fazla satıcı teklifi (tur 1..3)
MAIN_K = 2              # ana deneyde kullanılan teklif sayısı
N_PER_CLASS = 1000
N_FOLDS = 5
NOISE_STD = 0.02        # satıcı teklifindeki göreli gürültü


# ---- veri üretimi ----------------------------------------------------------------

def _seller_offers(bundle, beta: float, scenario_id: str, rng: random.Random, noise: bool) -> list[float]:
    """Satıcının ilk MAX_OFFERS teklifi, çekirdeğin fiyat fonksiyonu ve verilen β ile.

    SELLER_BETA geçici olarak değiştirilir ve sonra eski değerine döndürülür.
    """
    old = seller_mod.SELLER_BETA
    seller_mod.SELLER_BETA = beta
    try:
        prices = [seller_mod.seller_target_price(bundle, t, scenario_id=scenario_id, mode="opp")
                  for t in range(1, MAX_OFFERS + 1)]
    finally:
        seller_mod.SELLER_BETA = old
    if not noise:
        return prices
    out, prev = [], None
    for p in prices:
        q = p * (1 + rng.gauss(0, NOISE_STD))
        if rng.random() < 0.5:
            q = round(q / 10) * 10
        if prev is not None:
            q = min(q, prev)          # satıcı teklifini geri yükseltmez
        out.append(float(q))
        prev = q
    return out


def generate(listings, n_per_class: int = N_PER_CLASS, seed: int = SEED, noise: bool = True) -> pd.DataFrame:
    """Taviz tipi bilinen sentetik pazarlıklar üretir: her satır bir satıcı ve ilk teklifleri.

    Paket rastgele bir satıcının 1-3 ilanından oluşur (sitedeki gerçek ilanlar).
    """
    rng = random.Random(seed)
    by_seller: dict[str, list] = {}
    for l in listings:
        by_seller.setdefault(l.seller_id, []).append(l)
    sellers = sorted(by_seller)
    rows = []
    for cls in CLASSES:
        lo, hi = BETA_RANGES[cls]
        for i in range(n_per_class):
            items = by_seller[rng.choice(sellers)]
            bundle = rng.sample(items, rng.randint(1, min(3, len(items))))
            beta = rng.uniform(lo, hi)
            offers = _seller_offers(bundle, beta, f"OPP-{cls}-{i}", rng, noise)
            row = {"label": cls, "beta": beta, "n_items": len(bundle),
                   "list_total": sum(l.list_price for l in bundle)}
            row.update({f"p{t}": offers[t - 1] for t in range(1, MAX_OFFERS + 1)})
            rows.append(row)
    return pd.DataFrame(rows).sample(frac=1.0, random_state=seed).reset_index(drop=True)


def features(df: pd.DataFrame, k: int) -> pd.DataFrame:
    """Alıcının ilk k satıcı teklifinden hesapladığı özellikler (alt sınır ve β kullanılmaz).

    c_t  : t. teklifte liste toplamına göre indirim oranı, (L - p_t) / L
    d_t  : t-1'den t'ye taviz (liste toplamına oranla)
    r    : son tavizin ilk indirime oranı (taviz hızlanıyor mu?)
    """
    L = df["list_total"]
    out = pd.DataFrame({"n_items": df["n_items"], "log_list_total": np.log(L)})
    for t in range(1, k + 1):
        out[f"c{t}"] = (L - df[f"p{t}"]) / L
    for t in range(2, k + 1):
        out[f"d{t}"] = (df[f"p{t - 1}"] - df[f"p{t}"]) / L
    if k >= 2:
        out["r"] = out[f"d{k}"] / (out["c1"] + 1e-3)
    return out


# ---- modeller ve değerlendirme ---------------------------------------------------

def models() -> dict:
    """Karşılaştırılan modeller ve hiperparametreleri."""
    return {
        "Çoğunluk sınıfı (taban çizgisi)": DummyClassifier(strategy="most_frequent"),
        "Lojistik regresyon": make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000)),
        "Random forest": RandomForestClassifier(n_estimators=300, max_depth=None, min_samples_leaf=2,
                                                random_state=SEED, n_jobs=-1),
        "MLP": make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(32, 16), alpha=1e-3,
                                                             max_iter=1500, random_state=SEED)),
    }


def cross_validate(X: pd.DataFrame, y: pd.Series, model_factory=models, n_folds: int = N_FOLDS) -> tuple:
    """Tabakalı k katlı çapraz doğrulama. Her model için ortalama ± std metrikler ve
    katlardan birleştirilmiş tahminler (karmaşıklık matrisi için) döndürür."""
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=SEED)
    rows, preds = [], {}
    for name in model_factory():
        scores = {m: [] for m in ["Accuracy", "Precision", "Recall", "F1", "ROC-AUC"]}
        y_pred_all = pd.Series(index=y.index, dtype=object)
        for train, test in skf.split(X, y):
            model = model_factory()[name]
            model.fit(X.iloc[train], y.iloc[train])
            pred = model.predict(X.iloc[test])
            proba = model.predict_proba(X.iloc[test])
            y_test = y.iloc[test]
            y_pred_all.iloc[test] = pred
            scores["Accuracy"].append(accuracy_score(y_test, pred))
            scores["Precision"].append(precision_score(y_test, pred, average="macro", zero_division=0))
            scores["Recall"].append(recall_score(y_test, pred, average="macro", zero_division=0))
            scores["F1"].append(f1_score(y_test, pred, average="macro", zero_division=0))
            scores["ROC-AUC"].append(roc_auc_score(y_test, proba, multi_class="ovr", average="macro",
                                                   labels=list(model.classes_)))
        row = {"Model": name}
        for m, vals in scores.items():
            row[m] = float(np.mean(vals))
            row[f"{m} std"] = float(np.std(vals))
        rows.append(row)
        preds[name] = y_pred_all
    return pd.DataFrame(rows), preds


# ---- grafikler -----------------------------------------------------------------

def _axes(figsize):
    fig, ax = plt.subplots(figsize=figsize, facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e")
    return fig, ax


def plot_confusion(y_true, y_pred, title: str, out_path: Path) -> None:
    """Satır = gerçek sınıf, sütun = tahmin; hücrede satır yüzdesi ve sayı."""
    cm = confusion_matrix(y_true, y_pred, labels=CLASSES)
    pct = cm / cm.sum(axis=1, keepdims=True)
    fig, ax = _axes((5.6, 4.6))
    ax.imshow(pct, cmap="Blues", vmin=0, vmax=1)
    labels = [CLASS_LABELS[c] for c in CLASSES]
    ax.set_xticks(range(3), labels, fontsize=8.5)
    ax.set_yticks(range(3), labels, fontsize=8.5)
    ax.set_xlabel("Tahmin", color="#52514e")
    ax.set_ylabel("Gerçek", color="#52514e")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"%{100 * pct[i, j]:.0f}\n({cm[i, j]})".replace(".", ","), ha="center",
                    va="center", fontsize=9, color="white" if pct[i, j] > 0.55 else "#1d2433")
    ax.set_title(title, loc="left", fontsize=10.5, color="#0b0b0b")
    ax.spines[["left", "bottom"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_accuracy_by_k(table: pd.DataFrame, out_path: Path) -> None:
    """Gördüğü teklif sayısı arttıkça en iyi modelin doğruluğu; diğer modellerin farkı alt notta.

    Modeller birbirine çok yakın olduğu için (çizgiler üst üste biner) yalnızca en iyisi çizilir.
    """
    learned = [m for m in table["Model"].unique() if not m.startswith("Çoğunluk")]
    main = table[table["k"] == MAIN_K].set_index("Model").loc[learned, "Accuracy"]
    best = main.idxmax()
    g = table[table["Model"] == best].sort_values("k")
    spread = (table[table["Model"].isin(learned)].groupby("k")["Accuracy"].agg(lambda a: a.max() - a.min())
              .max() * 100)

    fig, ax = _axes((6.4, 4.2))
    ax.yaxis.grid(True, color="#e8e7e2", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.plot(g["k"], 100 * g["Accuracy"], marker="o", lw=2.2, color="#2a78d6", zorder=3)
    for _, r in g.iterrows():
        ax.text(r["k"], 100 * r["Accuracy"] + 3, f"%{100 * r['Accuracy']:.1f}".replace(".", ","),
                ha="center", fontsize=9.5, color="#1d2433")
    ax.axhline(100 / 3, color="#9a998f", lw=1, ls="--")
    ax.text(MAX_OFFERS, 100 / 3 + 1.5, "rastgele tahmin (%33)", ha="right", fontsize=8, color="#6b6a63")
    ax.set_xticks(range(1, MAX_OFFERS + 1), [f"İlk {k} teklif" for k in range(1, MAX_OFFERS + 1)])
    ax.set_xlim(0.7, MAX_OFFERS + 0.3)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Doğruluk (%)")
    ax.set_title(f"Satıcının taviz tipi ilk tekliflerinden tahmin edilebiliyor ({best})", loc="left",
                 fontsize=10.5, color="#0b0b0b")
    others = ", ".join(m if m.isupper() else m.lower() for m in learned if m != best)
    ax.text(0, -0.16, f"Diğer modeller ({others}) her noktada en fazla "
            f"{spread:.1f} puan farklı. 5 katlı tabakalı çapraz doğrulama.".replace(".", ",", 1),
            transform=ax.transAxes, fontsize=8, color="#52514e")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---- ana akış -------------------------------------------------------------------

def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = [f"{v:.3f}" if isinstance(v, float) else str(v) for v in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def run(out_dir: Path, n_per_class: int = N_PER_CLASS) -> pd.DataFrame:
    """Veriyi üretir, her teklif sayısı (k = 1..3) için modelleri değerlendirir, çıktıları yazar."""
    out_dir.mkdir(parents=True, exist_ok=True)
    listings = load_listings(ROOT / "data" / "listings.json")
    data = generate(listings, n_per_class=n_per_class)
    y = data["label"]

    tables, main_preds = [], None
    for k in range(1, MAX_OFFERS + 1):
        table, preds = cross_validate(features(data, k), y)
        table.insert(1, "k", k)
        tables.append(table)
        if k == MAIN_K:
            main_preds = preds
    table = pd.concat(tables, ignore_index=True)
    table.round(4).to_csv(out_dir / "metrics.csv", index=False, encoding="utf-8")

    main = table[table["k"] == MAIN_K]
    learned = main[~main["Model"].str.startswith("Çoğunluk")]
    best = learned.loc[learned["F1"].idxmax(), "Model"]
    plot_confusion(y, main_preds[best], f"{best}, ilk {MAIN_K} teklif (5 katlı ÇD)",
                   out_dir / "karmasiklik_matrisi.png")
    plot_accuracy_by_k(table, out_dir / "dogruluk_teklif_sayisi.png")

    show = main[["Model", "Accuracy", "Precision", "Recall", "F1", "ROC-AUC", "F1 std"]]
    by_k = table.pivot(index="Model", columns="k", values="Accuracy")
    by_k.columns = [f"Doğruluk, {c} teklif" for c in by_k.columns]
    parts = [
        "# Rakip modelleme: satıcının taviz tipi", "",
        f"Veri: {len(data)} sentetik pazarlık ({n_per_class} / sınıf), sınıflar {', '.join(CLASSES)}. "
        "Özellikler yalnızca alıcının gördüğü bilgiler (liste toplamı, ürün sayısı, satıcı teklifleri).", "",
        f"## Ana sonuç: ilk {MAIN_K} satıcı teklifi, {N_FOLDS} katlı tabakalı çapraz doğrulama", "",
        "Precision, Recall, F1 ve ROC-AUC makro ortalamadır (ROC-AUC: bire karşı hepsi).", "",
        _md_table(show), "",
        f"En iyi model (F1): {best}. Karmaşıklık matrisi: karmasiklik_matrisi.png", "",
        "## Gördüğü teklif sayısına göre doğruluk", "",
        _md_table(by_k.reset_index()), "",
        "Grafik: dogruluk_teklif_sayisi.png",
    ]
    (out_dir / "summary.md").write_text("\n".join(parts), encoding="utf-8")
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Satıcı taviz tipi sınıflandırıcısı")
    parser.add_argument("--out-dir", default=ROOT / "eval" / "out" / "opponent")
    parser.add_argument("--n-per-class", type=int, default=N_PER_CLASS)
    args = parser.parse_args()
    table = run(Path(args.out_dir), args.n_per_class)
    main_rows = table[table["k"] == MAIN_K][["Model", "Accuracy", "Precision", "Recall", "F1", "ROC-AUC"]]
    print(main_rows.round(3).to_string(index=False))
    print(f"\nÇıktılar: {args.out_dir}")


if __name__ == "__main__":
    main()
