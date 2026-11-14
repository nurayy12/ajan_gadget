"""results.jsonl dosyasından metrikleri, karşılaştırmaları, özet tabloyu ve grafikleri üretir.

Çalıştırma (proje kökünden):  python -m eval.metrics
Çıktılar eval/out/ klasörüne yazılır: summary.csv, summary.md ve üç PNG.

Dört koşul vardır: sistem ("system" = asıl sistem, "llm_only") x mod ("single", "bundle").
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
SYSTEMS = ["system", "llm_only"]
MODES = ["single", "bundle"]
SYSTEM_LABELS = {"system": "Asıl sistem", "llm_only": "Yalnızca LLM"}
MODE_LABELS = {"single": "Tek ürün", "bundle": "Paket"}
MODE_COLORS = {"single": "#2a78d6", "bundle": "#eb6834"}


def load_results(results_path: str | Path, listings_path: str | Path,
                 scenarios_path: str | Path) -> pd.DataFrame:
    """Sonuçları okur ve çalıştırma başına bir satırlık tablo döndürür.

    NegotiationResult içinde liste fiyatı, alt sınır, kargo ve bütçe olmadığı için
    bunlar ilan ve senaryo dosyalarından eklenir. Hata kayıtları atılır; aynı
    (senaryo, sistem, mod) birden fazla kez varsa son kayıt kullanılır.

    Türetilen sütunlar (yalnızca anlaşma varsa dolu, yoksa NaN):
      discount = (liste toplamı - anlaşılan fiyat) / liste toplamı
      utility  = (p_max - p) / (p_max - p_min)
                 p_max = min(bütçe - kargo, liste toplamı), p_min = alt sınırlar toplamı
    """
    listings = {l.listing_id: l for l in load_listings(listings_path)}
    scenarios = {s.scenario_id: s for s in load_scenarios(scenarios_path)}

    latest: dict[tuple[str, str, str], dict] = {}
    for line in Path(results_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            record.setdefault("system", "system")
            latest[(record["scenario_id"], record["system"], record["mode"])] = record

    rows = []
    for record in latest.values():
        if record["status"] != "ok":
            continue
        res = record["result"]
        scenario = scenarios[res["scenario_id"]]
        items = [listings[i] for i in res["listing_ids"] if i in listings]
        list_total = sum(l.list_price for l in items)
        floor_total = sum(l.floor_price for l in items)
        # Paket tek kargo öder: hedef ilanın kargosu (alıcı modülüyle aynı kural).
        shipping = listings[scenario.target_listing_id].shipping_cost
        price = res["final_price"]
        deal = bool(res["deal"]) and price is not None and list_total > 0

        discount = utility = float("nan")
        if deal:
            discount = (list_total - price) / list_total
            p_max = min(scenario.budget - shipping, list_total)
            if p_max > floor_total:
                utility = (p_max - price) / (p_max - floor_total)

        rows.append({
            "scenario_id": res["scenario_id"], "system": record["system"], "mode": res["mode"],
            "deal": deal, "final_price": price, "n_items": len(items),
            "list_total": list_total, "floor_total": floor_total,
            "discount": discount, "utility": utility, "rounds": res["rounds"],
            "violations": res["violations"], "has_violation": len(res["violations"]) > 0,
        })
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Dört satırlık özet tablo: sistem x mod.

    Anlaşma oranı, tur sayısı ve ihlal oranı tüm çalıştırmalar üzerinden;
    indirim ve alıcı faydası yalnızca anlaşmayla bitenler üzerinden hesaplanır.
    """
    rows = []
    for system in SYSTEMS:
        for mode in MODES:
            g = df[(df["system"] == system) & (df["mode"] == mode)]
            if g.empty:
                continue
            rows.append({
                "Sistem": SYSTEM_LABELS[system],
                "Mod": MODE_LABELS[mode],
                "Çalıştırma": len(g),
                "Anlaşma oranı (%)": 100 * g["deal"].mean(),
                "Ort. indirim (%)": 100 * g["discount"].mean(),
                "Ort. alıcı faydası": g["utility"].mean(),
                "Ort. tur": g["rounds"].mean(),
                "İhlal oranı (%)": 100 * g["has_violation"].mean(),
            })
    return pd.DataFrame(rows)


def violation_counts(df: pd.DataFrame) -> pd.DataFrame:
    """İhlal türüne göre sayım: satırlar ihlal türü, sütunlar dört koşul."""
    counts = {}
    for system in SYSTEMS:
        for mode in MODES:
            g = df[(df["system"] == system) & (df["mode"] == mode)]
            counts[f"{SYSTEM_LABELS[system]} / {MODE_LABELS[mode]}"] = Counter(
                v for vs in g["violations"] for v in vs)
    table = pd.DataFrame(counts).fillna(0).astype(int)
    table.index.name = "İhlal türü"
    return table


def paired_discounts(df: pd.DataFrame, system: str = "system") -> pd.DataFrame:
    """Bir sistemde iki modda da anlaşmayla biten senaryoların indirimleri (sütunlar: single, bundle)."""
    deals = df[(df["system"] == system) & df["deal"]]
    wide = deals.pivot(index="scenario_id", columns="mode", values="discount")
    return wide.reindex(columns=MODES).dropna()


def paired_test(df: pd.DataFrame) -> dict:
    """Karşılaştırma 1: asıl sistemde paket ve tek ürün indirimi farklı mı? (Wilcoxon, eşleştirilmiş)

    Yalnızca asıl sistemde iki modda da anlaşmayla biten senaryolar kullanılır.
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


def violation_comparison(df: pd.DataFrame) -> pd.DataFrame:
    """Karşılaştırma 2: paket modunda asıl sistem ve yalnızca-LLM'in ihlal oranı.

    Örneklem küçük olduğu için istatistik testi yapılmaz; yalnızca sayılar ve oranlar verilir.
    """
    rows = []
    for system in SYSTEMS:
        g = df[(df["system"] == system) & (df["mode"] == "bundle")]
        if g.empty:
            continue
        rows.append({"Sistem": SYSTEM_LABELS[system], "Çalıştırma (n)": len(g),
                     "İhlalli çalıştırma": int(g["has_violation"].sum()),
                     "İhlal oranı (%)": 100 * g["has_violation"].mean()})
    return pd.DataFrame(rows)


def _new_axes(figsize: tuple[float, float]):
    """Ortak sade görünümle boş bir grafik açar: üst/sağ çerçeve yok, silik yatay ızgara."""
    fig, ax = plt.subplots(figsize=figsize, facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e")
    ax.yaxis.grid(True, color="#e8e7e2", linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _grouped_bars(ax, values: dict[tuple[str, str], float], errors: dict | None = None) -> None:
    """Sistemleri x ekseninde, modları yan yana iki sütun olarak çizer ve değerleri üstüne yazar."""
    width = 0.36
    for j, mode in enumerate(MODES):
        xs = [i + (j - 0.5) * (width + 0.03) for i in range(len(SYSTEMS))]
        heights = [values.get((s, mode), float("nan")) for s in SYSTEMS]
        yerr = [errors.get((s, mode), 0) for s in SYSTEMS] if errors else None
        ax.bar(xs, [0 if pd.isna(h) else h for h in heights], width=width, yerr=yerr, capsize=4,
               color=MODE_COLORS[mode], label=MODE_LABELS[mode],
               ecolor="#52514e", error_kw={"linewidth": 1.2})
        for x, h, e in zip(xs, heights, yerr or [0] * len(xs)):
            if not pd.isna(h):
                ax.text(x, h + (e or 0), f"%{h:.1f}", ha="center", va="bottom",
                        fontsize=9, color="#0b0b0b")
    ax.set_xticks(range(len(SYSTEMS)))
    ax.set_xticklabels([SYSTEM_LABELS[s] for s in SYSTEMS])
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))


def plot_mean_discount(df: pd.DataFrame, out_path: str | Path) -> None:
    """Grafik 1: dört koşulda ortalama indirim; hata çubukları standart sapmadır."""
    deals = df[df["deal"]]
    stats = deals.groupby(["system", "mode"])["discount"].agg(["mean", "std"])
    means = {k: 100 * v for k, v in stats["mean"].items()}
    stds = {k: 0 if pd.isna(v) else 100 * v for k, v in stats["std"].items()}

    fig, ax = _new_axes((6.4, 4.4))
    _grouped_bars(ax, means, stds)
    ax.set_ylabel("Ortalama indirim (%)")
    ax.set_title("Koşullara göre ortalama indirim", loc="left", color="#0b0b0b")
    ax.text(0, -0.17, "Hata çubukları: standart sapma. Yalnızca anlaşmayla biten çalıştırmalar.",
            transform=ax.transAxes, fontsize=8, color="#52514e")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_paired(df: pd.DataFrame, out_path: str | Path) -> None:
    """Grafik 2: asıl sistemde senaryo bazında eşleştirilmiş nokta grafiği (her çizgi bir senaryo)."""
    wide = 100 * paired_discounts(df)

    fig, ax = _new_axes((5, 5))
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
    ax.set_title(f"Asıl sistem: senaryo bazında indirim (n={len(wide)})",
                 loc="left", color="#0b0b0b")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_violation_rate(df: pd.DataFrame, out_path: str | Path) -> None:
    """Grafik 3: sisteme göre ihlal oranı (en az bir ihlal içeren çalıştırmaların yüzdesi)."""
    rates = {k: 100 * v for k, v in df.groupby(["system", "mode"])["has_violation"].mean().items()}

    fig, ax = _new_axes((6.4, 4.4))
    _grouped_bars(ax, rates)
    ax.set_ylabel("İhlal oranı (%)")
    ax.set_ylim(0, max(10.0, max(rates.values(), default=0) * 1.2))
    ax.set_title("Sisteme göre ihlal oranı", loc="left", color="#0b0b0b")
    ax.text(0, -0.17, "En az bir kural ihlali içeren çalıştırmaların oranı.",
            transform=ax.transAxes, fontsize=8, color="#52514e")
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
                 comparison: pd.DataFrame, out_dir: str | Path) -> None:
    """Özet tabloyu summary.csv ve summary.md olarak kaydeder; md dosyasına iki karşılaştırma ve ihlal sayımı da eklenir."""
    out_dir = Path(out_dir)
    summary.round(3).to_csv(out_dir / "summary.csv", index=False, encoding="utf-8")

    if test["p_value"] is None:
        test_line = f"Wilcoxon testi uygulanamadı (eşleşmiş senaryo sayısı n = {test['n']})."
    else:
        test_line = (f"Wilcoxon işaretli sıralar testi (indirim, paket - tek ürün): "
                     f"n = {test['n']}, W = {test['statistic']:.1f}, p = {test['p_value']:.4f}")
    parts = ["# Deney özeti", "", _to_markdown(summary), "",
             "## Karşılaştırma 1: asıl sistemde tek ürün ve paket indirimi", "", test_line, "",
             "## Karşılaştırma 2: paket modunda ihlal oranı (test yapılmadı)", "",
             _to_markdown(comparison), "",
             "## İhlal türleri", "",
             _to_markdown(violations.reset_index()) if not violations.empty else "İhlal yok.", ""]
    (out_dir / "summary.md").write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    """Komut satırı girişi: tabloyu, karşılaştırmaları ve grafikleri üretip ekrana özet yazdırır."""
    parser = argparse.ArgumentParser(description="Deney metrikleri")
    parser.add_argument("--results", default=ROOT / "eval" / "results.jsonl")
    parser.add_argument("--listings", default=ROOT / "data" / "listings.json")
    parser.add_argument("--scenarios", default=ROOT / "data" / "scenarios.json")
    parser.add_argument("--out-dir", default=ROOT / "eval" / "out")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_results(args.results, args.listings, args.scenarios)

    save_summary(summarize(df), violation_counts(df), paired_test(df),
                 violation_comparison(df), out_dir)
    plot_mean_discount(df, out_dir / "ortalama_indirim.png")
    plot_paired(df, out_dir / "eslestirilmis_indirim.png")
    plot_violation_rate(df, out_dir / "ihlal_orani.png")
    print((out_dir / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
