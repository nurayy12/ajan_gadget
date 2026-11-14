"""results.jsonl dosyasından metrikleri, istatistik testini, özet tabloyu ve grafikleri üretir.

Çalıştırma (proje kökünden):  python -m eval.metrics
Çıktılar eval/out/ klasörüne yazılır: summary.csv, summary.md, iki PNG.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # ekran açmadan dosyaya çiz
import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import wilcoxon

from data.validate import load_listings, load_scenarios

ROOT = Path(__file__).parent.parent
MODES = ["single", "bundle"]
MODE_LABELS = {"single": "Tek ürün", "bundle": "Paket"}
MODE_COLORS = {"single": "#2a78d6", "bundle": "#eb6834"}


def load_results(results_path: str | Path, listings_path: str | Path,
                 scenarios_path: str | Path) -> pd.DataFrame:
    """Sonuçları okur ve çalıştırma başına bir satırlık tablo döndürür.

    NegotiationResult içinde liste fiyatı, alt sınır, kargo ve bütçe olmadığı için
    bunlar ilan ve senaryo dosyalarından eklenir. Hata kayıtları atılır; aynı
    (senaryo, mod) çifti birden fazla kez varsa son kayıt kullanılır.

    Türetilen sütunlar (yalnızca anlaşma varsa dolu, yoksa NaN):
      discount     = (liste toplamı - anlaşılan fiyat) / liste toplamı
      utility      = (p_max - p) / (p_max - p_min)
                     p_max = min(bütçe - kargo, liste toplamı), p_min = alt sınırlar toplamı
      ship_saving  = (ürün sayısı - 1) * kargo ücreti  (tek gönderi sayesinde)
    """
    listings = {l.listing_id: l for l in load_listings(listings_path)}
    scenarios = {s.scenario_id: s for s in load_scenarios(scenarios_path)}

    latest: dict[tuple[str, str], dict] = {}
    for line in Path(results_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            latest[(record["scenario_id"], record["mode"])] = record

    rows = []
    for record in latest.values():
        if record["status"] != "ok":
            continue
        res = record["result"]
        items = [listings[i] for i in res["listing_ids"]]
        list_total = sum(l.list_price for l in items)
        floor_total = sum(l.floor_price for l in items)
        shipping = items[0].shipping_cost if items else 0.0
        budget = scenarios[res["scenario_id"]].budget
        price = res["final_price"]
        deal = bool(res["deal"]) and price is not None

        discount = utility = ship_saving = float("nan")
        if deal:
            discount = (list_total - price) / list_total
            p_max = min(budget - shipping, list_total)
            if p_max > floor_total:
                utility = (p_max - price) / (p_max - floor_total)
            ship_saving = (len(items) - 1) * shipping

        rows.append({
            "scenario_id": res["scenario_id"], "mode": res["mode"], "deal": deal,
            "final_price": price, "n_items": len(items), "list_total": list_total,
            "floor_total": floor_total, "shipping": shipping, "budget": budget,
            "discount": discount, "utility": utility, "ship_saving": ship_saving,
            "rounds": res["rounds"], "violations": res["violations"],
            "has_violation": len(res["violations"]) > 0,
        })
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Koşul (tek ürün / paket) başına bir satırlık özet tablo.

    Anlaşma oranı, tur sayısı ve ihlal oranı tüm çalıştırmalar üzerinden;
    indirim, fayda ve kargo tasarrufu yalnızca anlaşmayla bitenler üzerinden hesaplanır.
    """
    rows = []
    for mode in MODES:
        g = df[df["mode"] == mode]
        if g.empty:
            continue
        rows.append({
            "Koşul": MODE_LABELS[mode],
            "Çalıştırma": len(g),
            "Anlaşma oranı (%)": 100 * g["deal"].mean(),
            "Ort. indirim (%)": 100 * g["discount"].mean(),
            "İndirim std (%)": 100 * g["discount"].std(),
            "Ort. alıcı faydası": g["utility"].mean(),
            "Ort. tur": g["rounds"].mean(),
            "İhlal oranı (%)": 100 * g["has_violation"].mean(),
            "Ort. kargo tasarrufu (TL)": g["ship_saving"].mean(),
        })
    return pd.DataFrame(rows)


def violation_counts(df: pd.DataFrame) -> pd.DataFrame:
    """İhlal türüne göre sayım: satırlar ihlal türü, sütunlar koşul."""
    counts = {MODE_LABELS[m]: Counter(v for vs in df[df["mode"] == m]["violations"] for v in vs)
              for m in MODES}
    table = pd.DataFrame(counts).fillna(0).astype(int)
    table.index.name = "İhlal türü"
    return table


def paired_discounts(df: pd.DataFrame) -> pd.DataFrame:
    """İki koşulda da anlaşmayla biten senaryoların indirimleri (sütunlar: single, bundle)."""
    deals = df[df["deal"]]
    wide = deals.pivot(index="scenario_id", columns="mode", values="discount")
    return wide.reindex(columns=MODES).dropna()


def paired_test(df: pd.DataFrame) -> dict:
    """Wilcoxon işaretli sıralar testi (eşleştirilmiş): paket indirimi tek ürün indiriminden farklı mı?

    Yalnızca iki koşulda da anlaşmayla biten senaryolar kullanılır.
    Döndürür: {"n", "statistic", "p_value"}; test uygulanamazsa (çift yok ya da
    tüm farklar sıfır) statistic ve p_value None olur.
    """
    wide = paired_discounts(df)
    out = {"n": len(wide), "statistic": None, "p_value": None}
    if len(wide) == 0 or (wide["bundle"] == wide["single"]).all():
        return out
    stat, p = wilcoxon(wide["bundle"], wide["single"])
    out.update(statistic=float(stat), p_value=float(p))
    return out


def _style_axes(ax) -> None:
    """Grafiklerde ortak sade görünüm: üst/sağ çerçeve yok, silik yatay ızgara."""
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e")
    ax.yaxis.grid(True, color="#e8e7e2", linewidth=0.8)
    ax.set_axisbelow(True)


def plot_mean_discount(df: pd.DataFrame, out_path: str | Path) -> None:
    """Koşullara göre ortalama indirim; hata çubukları standart sapmadır."""
    deals = df[df["deal"]]
    stats = deals.groupby("mode")["discount"].agg(["mean", "std", "count"]).reindex(MODES)
    means = 100 * stats["mean"]
    stds = (100 * stats["std"]).fillna(0)

    fig, ax = plt.subplots(figsize=(5, 4.2), facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    x = range(len(MODES))
    ax.bar(x, means, yerr=stds, width=0.45, capsize=5,
           color=[MODE_COLORS[m] for m in MODES], ecolor="#52514e", error_kw={"linewidth": 1.2})
    for i, m in enumerate(MODES):
        if pd.notna(means[m]):
            ax.text(i + 0.26, means[m], f"%{means[m]:.1f}", va="bottom", ha="left", color="#0b0b0b")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{MODE_LABELS[m]}\n(n={int(stats['count'][m] or 0)})" for m in MODES])
    ax.set_ylabel("Ortalama indirim (%)")
    ax.set_title("Koşullara göre ortalama indirim", loc="left", color="#0b0b0b")
    ax.text(0, -0.2, "Hata çubukları: standart sapma. Yalnızca anlaşmayla biten çalıştırmalar.",
            transform=ax.transAxes, fontsize=8, color="#52514e")
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_paired(df: pd.DataFrame, out_path: str | Path) -> None:
    """Senaryo bazında eşleştirilmiş nokta grafiği: her çizgi bir senaryonun iki koşuldaki indirimi."""
    wide = 100 * paired_discounts(df)

    fig, ax = plt.subplots(figsize=(5, 5), facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    for scenario_id, row in wide.iterrows():
        ax.plot([0, 1], [row["single"], row["bundle"]], color="#b5b4ab", linewidth=1.2, zorder=1)
        ax.text(1.05, row["bundle"], scenario_id, va="center", fontsize=7, color="#52514e")
    for i, m in enumerate(MODES):
        ax.scatter([i] * len(wide), wide[m], s=55, color=MODE_COLORS[m],
                   edgecolor="#fcfcfb", linewidth=1.5, zorder=2)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([MODE_LABELS[m] for m in MODES])
    ax.set_xlim(-0.3, 1.4)
    ax.set_ylabel("İndirim (%)")
    ax.set_title(f"Senaryo bazında indirim (n={len(wide)} eşleşmiş senaryo)",
                 loc="left", color="#0b0b0b")
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _to_markdown(table: pd.DataFrame) -> str:
    """DataFrame'i Markdown tablosuna çevirir (ek kütüphane gerektirmeden)."""
    def fmt(v):
        return f"{v:.2f}" if isinstance(v, float) else str(v)
    lines = ["| " + " | ".join(table.columns) + " |",
             "|" + "---|" * len(table.columns)]
    for _, row in table.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines)


def save_summary(summary: pd.DataFrame, violations: pd.DataFrame, test: dict,
                 out_dir: str | Path) -> None:
    """Özet tabloyu summary.csv ve summary.md olarak kaydeder; md dosyasına ihlal sayımı ve test sonucu da eklenir."""
    out_dir = Path(out_dir)
    summary.round(3).to_csv(out_dir / "summary.csv", index=False, encoding="utf-8")

    if test["p_value"] is None:
        test_line = f"Wilcoxon testi uygulanamadı (eşleşmiş senaryo sayısı n = {test['n']})."
    else:
        test_line = (f"Wilcoxon işaretli sıralar testi (indirim, paket - tek ürün): "
                     f"n = {test['n']}, W = {test['statistic']:.1f}, p = {test['p_value']:.4f}")
    parts = ["# Deney özeti", "", _to_markdown(summary), "",
             "## İhlal türleri", "",
             _to_markdown(violations.reset_index()) if not violations.empty else "İhlal yok.", "",
             "## Eşleştirilmiş test", "", test_line, ""]
    (out_dir / "summary.md").write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    """Komut satırı girişi: tabloyu, testi ve grafikleri üretip ekrana özet yazdırır."""
    parser = argparse.ArgumentParser(description="Deney metrikleri")
    parser.add_argument("--results", default=ROOT / "eval" / "results.jsonl")
    parser.add_argument("--listings", default=ROOT / "data" / "listings.json")
    parser.add_argument("--scenarios", default=ROOT / "data" / "scenarios.json")
    parser.add_argument("--out-dir", default=ROOT / "eval" / "out")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_results(args.results, args.listings, args.scenarios)
    summary = summarize(df)
    violations = violation_counts(df)
    test = paired_test(df)

    save_summary(summary, violations, test, out_dir)
    plot_mean_discount(df, out_dir / "ortalama_indirim.png")
    plot_paired(df, out_dir / "eslestirilmis_indirim.png")
    print((out_dir / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
