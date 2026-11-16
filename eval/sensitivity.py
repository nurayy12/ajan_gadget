"""Duyarlılık analizi: taviz parametreleri değişince anlaşma oranı ve indirim nasıl değişiyor?

Yalnızca asıl sistem, LLM'siz (USE_MOCK_LLM=1): fiyatları kod hesapladığı için şablon mesajlarla
fiyat sonuçları gerçek LLM'li çalıştırmayla aynıdır ve tüm ızgara birkaç saniyede biter.

Izgara (literatürdeki standart değerler; Genius/NegMAS zamana bağlı ajanları):
  alıcı β, satıcı β  ∈ {0,2 (Boulware), 1 (Linear), 2 (Conceder)}
  alıcı açılışı      ∈ {%60, %70 (Dolap'ta en fazla %30 indirim teklifi), %80}
  mod                ∈ {tek ürün, paket}

Çalıştırma (proje kökünden):  python -m eval.sensitivity
Çıktılar eval/out/ klasörüne: sensitivity.csv (ayar başına özet), sensitivity_runs.csv
(çalıştırma başına), duyarlilik_anlasma.png ve duyarlilik_indirim.png.

Parametreler buyer/ ve core/ dosyaları değiştirilmeden, çalışma anında modül sabitleri
geçici olarak değiştirilerek verilir; her ayardan sonra eski değerler geri yüklenir.
"""
import os

os.environ["USE_MOCK_LLM"] = "1"  # importlardan önce: hiçbir LLM çağrısı yapılmasın

import argparse
import inspect
import itertools
from contextlib import contextmanager
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import buyer.config as buyer_config
import buyer.pricing as buyer_pricing
import core.seller as core_seller
from data.validate import load_listings, load_scenarios
from eval.run_experiments import run_system

ROOT = Path(__file__).parent.parent
GRID = {
    "buyer_beta": [0.2, 1.0, 2.0],
    "seller_beta": [0.2, 1.0, 2.0],
    "start_fraction": [0.60, 0.70, 0.80],
}
MODES = ["single", "bundle"]
MODE_LABELS = {"single": "Tek ürün", "bundle": "Paket"}


@contextmanager
def override_params(buyer_beta: float, seller_beta: float, start_fraction: float):
    """Alıcı β, satıcı β ve alıcı açılışını geçici olarak değiştirir; çıkışta eski değerleri geri yükler.

    - Alıcı açılışı: buyer.config.START_FRACTION (alıcı fiyatı hesaplarken çağrı anında okur).
    - Alıcı β: buyer.config.BETA. Ayrıca buyer.pricing.concession_price β'yı varsayılan argüman
      olarak yakalıyorsa o varsayılan da geçici olarak değiştirilir.
    - Satıcı β: core.seller.SELLER_BETA (satıcı fiyatı hesaplarken çağrı anında okur).
    Paket seçimi bu değerlerden etkilenmez; böylece her ayarda aynı paketler karşılaştırılır.
    """
    saved = (buyer_config.BETA, buyer_config.START_FRACTION, core_seller.SELLER_BETA,
             buyer_pricing.concession_price.__defaults__)
    try:
        buyer_config.BETA = buyer_beta
        buyer_config.START_FRACTION = start_fraction
        core_seller.SELLER_BETA = seller_beta
        params = inspect.signature(buyer_pricing.concession_price).parameters
        defaults = buyer_pricing.concession_price.__defaults__
        if defaults and "beta" in params and params["beta"].default is not inspect.Parameter.empty:
            names = [n for n, p in params.items() if p.default is not inspect.Parameter.empty]
            values = list(defaults)
            values[names.index("beta")] = buyer_beta
            buyer_pricing.concession_price.__defaults__ = tuple(values)
        yield
    finally:
        (buyer_config.BETA, buyer_config.START_FRACTION, core_seller.SELLER_BETA,
         buyer_pricing.concession_price.__defaults__) = saved


def check_overrides_take_effect(scenario, listings) -> list[str]:
    """Her parametrenin gerçekten sonucu değiştirdiğini tek bir senaryoyla kontrol eder.

    Değiştirmiyorsa (ör. ilgili modül değeri import anında yakaladıysa) uyarı metni döndürür.
    """
    def offers(**kw):
        with override_params(**kw):
            result = run_system(scenario, listings, "single")
        return [(o.sender, o.round, o.price) for o in result.offers]

    base = dict(buyer_beta=1.0, seller_beta=1.0, start_fraction=0.70)
    warnings = []
    for name, value in [("buyer_beta", 0.2), ("seller_beta", 0.2), ("start_fraction", 0.60)]:
        if offers(**{**base, name: value}) == offers(**base):
            warnings.append(f"UYARI: {name} değişikliği teklifleri değiştirmedi; bu parametre "
                            "ızgarada etkisiz olabilir.")
    return warnings


def run_grid(scenarios, listings) -> pd.DataFrame:
    """Tüm ızgarayı çalıştırır; çalıştırma başına bir satır döndürür."""
    rows = []
    combos = list(itertools.product(GRID["buyer_beta"], GRID["seller_beta"], GRID["start_fraction"]))
    for n, (b_beta, s_beta, start) in enumerate(combos, start=1):
        print(f"[{n}/{len(combos)}] alıcı β={b_beta}, satıcı β={s_beta}, açılış={start:.2f}")
        with override_params(b_beta, s_beta, start):
            for scenario in scenarios:
                for mode in MODES:
                    result = run_system(scenario, listings, mode)
                    by_id = {l.listing_id: l for l in listings}
                    list_total = sum(by_id[i].list_price for i in result.listing_ids)
                    deal = result.deal and result.final_price is not None
                    rows.append({
                        "buyer_beta": b_beta, "seller_beta": s_beta, "start_fraction": start,
                        "mode": mode, "scenario_id": scenario.scenario_id,
                        "n_items": len(result.listing_ids), "deal": deal,
                        "discount": (list_total - result.final_price) / list_total if deal else float("nan"),
                        "rounds": result.rounds,
                        "has_violation": bool([v for v in result.violations if v != "llm_error"]),
                    })
    return pd.DataFrame(rows)


def aggregate(runs: pd.DataFrame) -> pd.DataFrame:
    """Ayar ve mod başına özet: anlaşma oranı, ortalama indirim (anlaşmalılarda), ortalama tur."""
    return (runs.groupby(["buyer_beta", "seller_beta", "start_fraction", "mode"])
                .agg(n=("deal", "size"), deal_rate=("deal", "mean"),
                     mean_discount=("discount", "mean"), mean_rounds=("rounds", "mean"),
                     violation_rate=("has_violation", "mean"))
                .reset_index())


def plot_heatmaps(summary: pd.DataFrame, metric: str, title: str, out_path: str | Path) -> None:
    """Küçük çoklu ısı haritası: satırlar mod, sütunlar alıcı açılışı; hücre = alıcı β × satıcı β.

    Tek renk tonlu ardışık skala (açık → koyu); tüm paneller aynı ölçeği paylaşır ki
    karşılaştırılabilsin. Hücre değerleri yüzde olarak yazılır.
    """
    starts, betas = GRID["start_fraction"], GRID["buyer_beta"]
    values = 100 * summary[metric]
    vmin, vmax = float(values.min()), float(values.max())
    fig, axes = plt.subplots(len(MODES), len(starts), figsize=(10, 6.4), facecolor="#fcfcfb",
                             sharex=True, sharey=True)
    for r, mode in enumerate(MODES):
        for c, start in enumerate(starts):
            ax = axes[r][c]
            sub = summary[(summary["mode"] == mode) & ((summary["start_fraction"] - start).abs() < 1e-9)]
            grid = (100 * sub.pivot(index="buyer_beta", columns="seller_beta", values=metric)
                    .reindex(index=betas, columns=GRID["seller_beta"]))
            im = ax.imshow(grid.values, cmap="Blues", vmin=vmin, vmax=vmax, aspect="equal")
            for i in range(len(betas)):
                for j in range(len(GRID["seller_beta"])):
                    v = grid.values[i, j]
                    if pd.notna(v):
                        dark = (v - vmin) / ((vmax - vmin) or 1) > 0.55
                        ax.text(j, i, f"%{v:.1f}", ha="center", va="center", fontsize=8,
                                color="#fcfcfb" if dark else "#0b0b0b")
            ax.set_xticks(range(len(GRID["seller_beta"])), [f"{b:g}" for b in GRID["seller_beta"]])
            ax.set_yticks(range(len(betas)), [f"{b:g}" for b in betas])
            for side in ("top", "right", "left", "bottom"):
                ax.spines[side].set_visible(False)
            if r == 0:
                ax.set_title(f"Alıcı açılışı %{100 * start:.0f}", fontsize=10, color="#0b0b0b")
            if c == 0:
                ax.set_ylabel(f"{MODE_LABELS[mode]}\nalıcı β", color="#52514e")
            if r == len(MODES) - 1:
                ax.set_xlabel("satıcı β", color="#52514e")
    fig.suptitle(title, x=0.02, ha="left", color="#0b0b0b")
    cbar = fig.colorbar(im, ax=axes, shrink=0.75)
    cbar.set_label("%", color="#52514e")
    fig.text(0.02, 0.01, "β: 0,2 = yavaş taviz (Boulware), 1 = doğrusal, 2 = hızlı taviz (Conceder). "
             "Asıl sistem, LLM'siz.", fontsize=8, color="#52514e")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    """Komut satırı girişi: ızgarayı çalıştırır, CSV'leri ve iki ısı haritasını kaydeder."""
    parser = argparse.ArgumentParser(description="Taviz parametrelerine duyarlılık analizi")
    parser.add_argument("--listings", default=ROOT / "data" / "listings.json")
    parser.add_argument("--scenarios", default=ROOT / "data" / "scenarios.json")
    parser.add_argument("--out-dir", default=ROOT / "eval" / "out")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    listings, scenarios = load_listings(args.listings), load_scenarios(args.scenarios)

    for warning in check_overrides_take_effect(scenarios[0], listings):
        print(warning)
    runs = run_grid(scenarios, listings)
    summary = aggregate(runs)
    runs.to_csv(out_dir / "sensitivity_runs.csv", index=False, encoding="utf-8")
    summary.round(4).to_csv(out_dir / "sensitivity.csv", index=False, encoding="utf-8")
    plot_heatmaps(summary, "deal_rate", "Duyarlılık: anlaşma oranı (%)", out_dir / "duyarlilik_anlasma.png")
    plot_heatmaps(summary, "mean_discount", "Duyarlılık: ortalama indirim (%)",
                  out_dir / "duyarlilik_indirim.png")
    print(f"\n{len(runs)} çalıştırma; çıktılar {out_dir} klasöründe.")


if __name__ == "__main__":
    main()
