"""results.jsonl dosyasından metrikleri, karşılaştırmaları, özet tabloyu ve grafikleri üretir.

Çalıştırma (proje kökünden):  python -m eval.metrics
Çıktılar eval/out/ klasörüne yazılır: summary.csv, summary.md ve üç PNG.
eval/out/sensitivity.csv varsa (python -m eval.sensitivity) özet tabloya duyarlılık bölümü eklenir.

Dört koşul vardır: sistem ("system" = asıl sistem, "llm_only") x mod ("single", "bundle").
Her koşul birkaç kez tekrarlanmış olabilir ("repeat" alanı).

Anlaşma alanı (kökteki ortak policy.py ile):
  p_min = bundle_floor(ürünler)                       satıcının paket indirimli alt sınırı
  p_max = max_affordable_price(ürünler, bütçe)        alıcının kargo dahil bütçeyle ödeyebileceği en yüksek fiyat
  ZOPA  = p_max >= p_min (yoksa doğru davranış anlaşmamaktır)
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
from policy import bundle_floor, buyer_shipping, max_affordable_price

ROOT = Path(__file__).parent.parent
SYSTEMS = ["system", "llm_only"]
MODES = ["single", "bundle"]
SYSTEM_LABELS = {"system": "Asıl sistem", "llm_only": "Yalnızca LLM"}
MODE_LABELS = {"single": "Tek ürün", "bundle": "Paket"}
MODE_COLORS = {"single": "#2a78d6", "bundle": "#eb6834"}
# Çekirdek, LLM çağrısı başarısız olunca violations listesine bu kodu ekler. Bu bir kural
# ihlali değil teknik hatadır; ihlal oranına katılmaz, ayrı sütunda raporlanır.
LLM_ERROR = "llm_error"

# AgenticPay (arXiv 2602.06008, Algoritma 1) skor parametreleri.
GAMMA = 0.99          # tur başına verimlilik indirimi
DEAL_BONUS = 30.0     # D
QUALITY_WEIGHT = 55.0 # W
EFFICIENCY = 15.0     # E
FAIL_PENALTY = 15.0   # F
T_MAX = 5             # bu projedeki en fazla tur
EPS = 0.01            # TL; kuruş yuvarlamasına tolerans


def agenticpay_scores(deal: bool, price: float | None, p_min: float, p_max: float,
                      rounds: int, t_max: int = T_MAX) -> tuple[float, float, float]:
    """AgenticPay skorları: (alıcı skoru, satıcı skoru, genel skor).

    Geçerli anlaşma (fiyat [p_min, p_max] aralığında ve aralık boş değil):
      d = γ^(tur-1), r_b = (p_max - p)/(p_max - p_min), r_s = (p - p_min)/(p_max - p_min)
      alıcı = d·(D + W·r_b + E), satıcı = d·(D + W·r_s + E), genel = d·(D + W·4·r_b·r_s + E)
    Anlaşma yoksa ya da fiyat aralık dışındaysa (AgenticPay'de geçersiz işlem):
      d = γ^(T-1) ve üç skor da -F·(1 - d).
    """
    zone = p_max - p_min
    valid = (deal and price is not None and zone > EPS
             and p_min - EPS <= price <= p_max + EPS)
    if not valid:
        penalty = -FAIL_PENALTY * (1 - GAMMA ** (t_max - 1))
        return penalty, penalty, penalty
    d = GAMMA ** (rounds - 1)
    r_b = min(1.0, max(0.0, (p_max - price) / zone))
    r_s = 1.0 - r_b
    return (d * (DEAL_BONUS + QUALITY_WEIGHT * r_b + EFFICIENCY),
            d * (DEAL_BONUS + QUALITY_WEIGHT * r_s + EFFICIENCY),
            d * (DEAL_BONUS + QUALITY_WEIGHT * 4 * r_b * r_s + EFFICIENCY))


def shipping_saving(items: list, price: float) -> float:
    """Paketin kargo tasarrufu (TL): ürünler ayrı ayrı alınsaydı ödenecek kargo − paketin kargosu.

    Ayrı alımların fiyatı, anlaşılan paket fiyatı liste fiyatlarıyla orantılı bölünerek varsayılır;
    her parçaya Dolap kuralı (policy.buyer_shipping) ayrı uygulanır. Tek üründe 0.
    """
    if len(items) < 2:
        return 0.0
    list_total = sum(l.list_price for l in items)
    separate = sum(buyer_shipping([l], price * l.list_price / list_total) for l in items)
    return separate - buyer_shipping(items, price)


def load_results(results_path: str | Path, listings_path: str | Path,
                 scenarios_path: str | Path) -> pd.DataFrame:
    """Sonuçları okur ve çalıştırma başına bir satırlık tablo döndürür.

    NegotiationResult içinde liste fiyatı, alt sınır, kargo ve bütçe olmadığı için bunlar ilan
    ve senaryo dosyalarından eklenir. Hata kayıtları atılır; aynı (senaryo, sistem, mod, tekrar)
    birden fazla kez varsa son kayıt kullanılır.

    Türetilen sütunlar:
      p_min, p_max, zopa        anlaşma alanı
      discount                  (liste toplamı - fiyat) / liste toplamı        (anlaşma varsa)
      in_zone, out_of_zone      fiyat [p_min, p_max] içinde mi                 (anlaşma varsa)
      utility                   alıcı faydası r_b (AgenticPay)                 (geçerli anlaşmada)
      buyer_score, seller_score, global_score   AgenticPay skorları           (her çalıştırmada)
      ship_saving               paketin kargo tasarrufu (TL)                    (anlaşma varsa)
      seller_gain               satıcının kendi alt sınırının üstündeki kazancı (TL) = fiyat - p_min
      seller_utility            satıcı faydası r_s (AgenticPay)                (geçerli anlaşmada)
      buyer_msgs, seller_msgs   tarafların mesaj metinleri (çeşitlilik ölçümü için)
    """
    listings = {l.listing_id: l for l in load_listings(listings_path)}
    scenarios = {s.scenario_id: s for s in load_scenarios(scenarios_path)}

    latest: dict[tuple, dict] = {}
    for line in Path(results_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            key = (r["scenario_id"], r.get("system", "system"), r["mode"], int(r.get("repeat", 0)))
            latest[key] = r

    rows = []
    for (scenario_id, system, mode, repeat), record in latest.items():
        if record["status"] != "ok":
            continue
        res = record["result"]
        scenario = scenarios[scenario_id]
        items = [listings[i] for i in res["listing_ids"] if i in listings]
        if not items:
            continue
        list_total = sum(l.list_price for l in items)
        p_min = bundle_floor(items)
        p_max = max_affordable_price(items, scenario.budget)
        price = res["final_price"]
        deal = bool(res["deal"]) and price is not None

        nan = float("nan")
        discount = utility = ship = seller_gain = seller_utility = nan
        in_zone = False
        if deal:
            discount = (list_total - price) / list_total
            in_zone = p_min - EPS <= price <= p_max + EPS
            ship = shipping_saving(items, price)
            seller_gain = price - p_min
            if in_zone and p_max - p_min > EPS:
                utility = (p_max - price) / (p_max - p_min)
                seller_utility = 1.0 - utility
        buyer_s, seller_s, global_s = agenticpay_scores(deal, price, p_min, p_max, res["rounds"])

        rows.append({
            "scenario_id": scenario_id, "system": system, "mode": mode, "repeat": repeat,
            "deal": deal, "final_price": price, "n_items": len(items), "list_total": list_total,
            "p_min": p_min, "p_max": p_max, "zopa": p_max >= p_min - EPS,
            "discount": discount, "in_zone": in_zone, "out_of_zone": deal and not in_zone,
            "utility": utility, "buyer_score": buyer_s, "seller_score": seller_s,
            "global_score": global_s, "ship_saving": ship, "rounds": res["rounds"],
            "seller_gain": seller_gain, "seller_utility": seller_utility,
            "buyer_msgs": [o["message"] for o in res["offers"] if o["sender"] == "buyer"],
            "seller_msgs": [o["message"] for o in res["offers"] if o["sender"] == "seller"],
            "violations": res["violations"],
            "has_violation": any(v != LLM_ERROR for v in res["violations"]),
            "has_llm_error": LLM_ERROR in res["violations"],
        })
    return pd.DataFrame(rows)


def per_scenario(df: pd.DataFrame) -> pd.DataFrame:
    """Tekrarları (senaryo, sistem, mod) bazında ortalar.

    deal_rate tekrarların kaçında anlaşma olduğu; discount ve utility yalnızca anlaşmalı
    tekrarların ortalaması (hiç anlaşma yoksa NaN).
    """
    return (df.groupby(["scenario_id", "system", "mode"])
              .agg(deal_rate=("deal", "mean"), discount=("discount", "mean"),
                   utility=("utility", "mean"), buyer_score=("buyer_score", "mean"),
                   n_items=("n_items", "max"), repeats=("repeat", "nunique"))
              .reset_index())


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Dört satırlık özet tablo: sistem x mod (tüm tekrarlar birlikte).

    Anlaşma oranı, AgenticPay skorları, tur, ihlal, LLM hatası ve ZOPA tüm çalıştırmalar üzerinden;
    indirim ve kargo tasarrufu anlaşmayla bitenler, alıcı faydası geçerli anlaşmalar üzerinden.
    """
    rows = []
    for system in SYSTEMS:
        for mode in MODES:
            g = df[(df["system"] == system) & (df["mode"] == mode)]
            if g.empty:
                continue
            deals = g[g["deal"]]
            rows.append({
                "Sistem": SYSTEM_LABELS[system],
                "Mod": MODE_LABELS[mode],
                "Çalıştırma": len(g),
                "Senaryo": g["scenario_id"].nunique(),
                "Anlaşma oranı (%)": 100 * g["deal"].mean(),
                "Ort. indirim (%)": 100 * g["discount"].mean(),
                "Ort. alıcı faydası": g["utility"].mean(),
                "Ort. satıcı kazancı (TL)": deals["seller_gain"].mean() if len(deals) else float("nan"),
                "Ort. satıcı faydası": g["seller_utility"].mean(),
                "AgenticPay alıcı skoru": g["buyer_score"].mean(),
                "AgenticPay satıcı skoru": g["seller_score"].mean(),
                "AgenticPay genel skor": g["global_score"].mean(),
                "Ort. tur": g["rounds"].mean(),
                "İhlal oranı (%)": 100 * g["has_violation"].mean(),
                "Aralık dışı anlaşma": int(g["out_of_zone"].sum()),
                "LLM hatalı çalıştırma": int(g["has_llm_error"].sum()),
                "ZOPA'sız çalıştırma": int((~g["zopa"]).sum()),
                "Ort. kargo tasarrufu (TL)": deals["ship_saving"].mean() if len(deals) else float("nan"),
            })
    return pd.DataFrame(rows)


def distinct_n(messages: list[str], n: int) -> float:
    """distinct-n: farklı n-gram sayısı / toplam n-gram sayısı (Li ve ark. 2016, NAACL).

    1'e yakınsa mesajlar çeşitli, 0'a yakınsa aynı kalıplar tekrarlanıyor demektir.
    Sayılar ayrı bir simgeye çevrilir; yalnızca fiyatı değişen kalıp cümleler çeşitli sayılmasın.
    """
    import re
    grams, total = set(), 0
    for m in messages:
        words = ["<sayı>" if re.fullmatch(r"[\d.,]+", w) else w
                 for w in re.findall(r"[\wçğıöşüÇĞİÖŞÜ.,]+", m.lower())]
        for i in range(len(words) - n + 1):
            grams.add(tuple(words[i:i + n]))
            total += 1
    return len(grams) / total if total else float("nan")


def message_diversity(df: pd.DataFrame) -> pd.DataFrame:
    """Koşul ve taraf başına mesaj çeşitliliği: mesaj sayısı, benzersiz mesaj oranı, distinct-1/2.

    Benzersiz oran hesaplanırken sayılar yok sayılır: "1200 TL teklif ediyorum" ile
    "1300 TL teklif ediyorum" aynı kalıp sayılır.
    """
    import re
    rows = []
    for system in SYSTEMS:
        for mode in MODES:
            g = df[(df["system"] == system) & (df["mode"] == mode)]
            for side, col in (("Alıcı", "buyer_msgs"), ("Satıcı", "seller_msgs")):
                msgs = [m for ms in g[col] for m in ms]
                if not msgs:
                    continue
                patterns = {re.sub(r"[\d.,]+", "<sayı>", m.lower()) for m in msgs}
                rows.append({"Sistem": SYSTEM_LABELS[system], "Mod": MODE_LABELS[mode], "Taraf": side,
                             "Mesaj": len(msgs), "Benzersiz kalıp (%)": 100 * len(patterns) / len(msgs),
                             "distinct-1": distinct_n(msgs, 1), "distinct-2": distinct_n(msgs, 2)})
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
    """Eşleştirilmiş indirimler (sütunlar: single, bundle), senaryo başına tekrar ortalamasıyla.

    Yalnızca paket modunda gerçekten birden fazla ürünün pazarlık edildiği ve iki modda da en az
    bir anlaşmanın olduğu senaryolar alınır. Paket kurulamayan senaryolarda iki mod aynı ürün
    olduğu için karşılaştırmaya bilgi katmaz.
    """
    ps = per_scenario(df[df["system"] == system])
    bundled = set(ps[(ps["mode"] == "bundle") & (ps["n_items"] > 1)]["scenario_id"])
    wide = ps.pivot(index="scenario_id", columns="mode", values="discount").reindex(columns=MODES)
    return wide[wide.index.isin(bundled)].dropna()


def paired_test(df: pd.DataFrame) -> dict:
    """Karşılaştırma 1: asıl sistemde paket ve tek ürün indirimi farklı mı? (Wilcoxon, eşleştirilmiş)

    Döndürür: {"n", "statistic", "p_value", "median_diff"}; test uygulanamazsa (çift yok ya da
    tüm farklar sıfır) statistic ve p_value None olur.
    """
    wide = paired_discounts(df)
    out = {"n": len(wide), "statistic": None, "p_value": None, "median_diff": None}
    if len(wide) == 0:
        return out
    diff = wide["bundle"] - wide["single"]
    out["median_diff"] = float(diff.median())
    if (diff.abs() < 1e-12).all():
        return out
    stat, p = wilcoxon(wide["bundle"], wide["single"])
    out.update(statistic=float(stat), p_value=float(p))
    return out


def violation_comparison(df: pd.DataFrame) -> pd.DataFrame:
    """Karşılaştırma 2: paket modunda asıl sistem ve yalnızca-LLM'in ihlal oranı (test yapılmaz)."""
    rows = []
    for system in SYSTEMS:
        g = df[(df["system"] == system) & (df["mode"] == "bundle")]
        if g.empty:
            continue
        rows.append({"Sistem": SYSTEM_LABELS[system], "Çalıştırma (n)": len(g),
                     "İhlalli çalıştırma": int(g["has_violation"].sum()),
                     "İhlal oranı (%)": 100 * g["has_violation"].mean()})
    return pd.DataFrame(rows)


def zopa_table(df: pd.DataFrame) -> pd.DataFrame:
    """Anlaşma alanı olmayan çalıştırmalar: orada doğru davranış anlaşmamaktır.

    "Anlaşma" sütunu bu çalıştırmalarda yapılan (dolayısıyla bir kuralı çiğneyen) anlaşma sayısıdır.
    """
    rows = []
    for system in SYSTEMS:
        for mode in MODES:
            g = df[(df["system"] == system) & (df["mode"] == mode) & (~df["zopa"])]
            if g.empty:
                continue
            rows.append({"Sistem": SYSTEM_LABELS[system], "Mod": MODE_LABELS[mode],
                         "ZOPA'sız çalıştırma": len(g), "Anlaşma": int(g["deal"].sum()),
                         "Doğru davranış (%)": 100 * (1 - g["deal"].mean())})
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

    fig, ax = _new_axes((5, 5.5))
    for scenario_id, row in wide.iterrows():
        ax.plot([0, 1], [row["single"], row["bundle"]], color="#b5b4ab", linewidth=1.0, zorder=1)
    for i, m in enumerate(MODES):
        ax.scatter([i] * len(wide), wide[m], s=40, color=MODE_COLORS[m],
                   edgecolor="#fcfcfb", linewidth=1.5, zorder=2)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([MODE_LABELS[m] for m in MODES])
    ax.set_xlim(-0.3, 1.3)
    ax.set_ylabel("İndirim (%)")
    ax.set_title(f"Asıl sistem: senaryo bazında indirim (n={len(wide)})",
                 loc="left", color="#0b0b0b")
    ax.text(0, -0.12, "Her çizgi bir senaryo; tekrarların ortalaması. Yalnızca paket kurulan senaryolar.",
            transform=ax.transAxes, fontsize=8, color="#52514e")
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
        if isinstance(v, float):
            return "—" if pd.isna(v) else f"{v:.2f}"
        return str(v)
    lines = ["| " + " | ".join(str(c) for c in table.columns) + " |",
             "|" + "---|" * len(table.columns)]
    for _, row in table.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in row) + " |")
    return "\n".join(lines)


def sensitivity_section(sens_path: str | Path) -> list[str]:
    """eval/sensitivity.py çıktısı varsa, alıcı açılışı %70 için kısa bir duyarlılık tablosu döndürür."""
    sens_path = Path(sens_path)
    if not sens_path.exists():
        return []
    sens = pd.read_csv(sens_path)
    base = sens[(sens["start_fraction"] - 0.70).abs() < 1e-9]
    wide = base.pivot_table(index=["buyer_beta", "seller_beta"], columns="mode",
                            values=["deal_rate", "mean_discount"]).reset_index()
    table = pd.DataFrame({
        "Alıcı β": wide["buyer_beta"], "Satıcı β": wide["seller_beta"],
        "Anlaşma tek ürün (%)": 100 * wide[("deal_rate", "single")],
        "Anlaşma paket (%)": 100 * wide[("deal_rate", "bundle")],
        "İndirim tek ürün (%)": 100 * wide[("mean_discount", "single")],
        "İndirim paket (%)": 100 * wide[("mean_discount", "bundle")],
    })
    return ["## Duyarlılık analizi (asıl sistem, LLM'siz, alıcı açılışı %70)", "",
            _to_markdown(table), "",
            f"Tüm ızgara (açılış %60/%70/%80): {sens_path.name}. "
            "Isı haritaları: duyarlilik_anlasma.png, duyarlilik_indirim.png.", ""]


def save_summary(df: pd.DataFrame, out_dir: str | Path) -> None:
    """Özet tabloyu summary.csv ve summary.md olarak kaydeder; md dosyasına karşılaştırmalar,
    ZOPA tablosu, ihlal sayımı ve (varsa) duyarlılık analizi eklenir."""
    out_dir = Path(out_dir)
    summary = summarize(df)
    summary.round(3).to_csv(out_dir / "summary.csv", index=False, encoding="utf-8")

    test = paired_test(df)
    if test["p_value"] is None:
        test_line = (f"Wilcoxon testi uygulanamadı (eşleşmiş senaryo sayısı n = {test['n']}"
                     + (", tüm farklar sıfır" if test["n"] else "") + ").")
    else:
        test_line = (f"Wilcoxon işaretli sıralar testi (indirim, paket − tek ürün): "
                     f"n = {test['n']} senaryo, medyan fark = {100 * test['median_diff']:.2f} puan, "
                     f"W = {test['statistic']:.1f}, p = {test['p_value']:.4f}")
    repeats = int(df["repeat"].nunique()) if len(df) else 0
    violations = violation_counts(df)
    zopa = zopa_table(df)
    parts = ["# Deney özeti", "",
             f"Tekrar sayısı: {repeats}. Anlaşma alanı p_min = paket indirimli alt sınır, "
             "p_max = bütçeyle ödenebilecek en yüksek fiyat (Dolap kargo kuralıyla).", "",
             _to_markdown(summary), "",
             "## Karşılaştırma 1: asıl sistemde tek ürün ve paket indirimi", "", test_line,
             "Senaryo başına tekrar ortalaması kullanıldı; yalnızca paket kurulan senaryolar.", "",
             "## Karşılaştırma 2: paket modunda ihlal oranı (test yapılmadı)", "",
             _to_markdown(violation_comparison(df)), "",
             "## Anlaşma alanı olmayan çalıştırmalar", "",
             _to_markdown(zopa) if not zopa.empty else "Tüm çalıştırmalarda anlaşma alanı var.", "",
             "## Mesaj çeşitliliği", "",
             _to_markdown(message_diversity(df)), "",
             "Benzersiz kalıp: sayılar yok sayıldığında farklı mesaj oranı. distinct-n: farklı n-gram / "
             "toplam n-gram (Li ve ark. 2016). Düşük değer, mesajların aynı kalıpla tekrarlandığını gösterir.", "",
             "## İhlal türleri", "",
             _to_markdown(violations.reset_index()) if not violations.empty else "İhlal yok.", "",
             *sensitivity_section(out_dir / "sensitivity.csv")]
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

    save_summary(df, out_dir)
    plot_mean_discount(df, out_dir / "ortalama_indirim.png")
    plot_paired(df, out_dir / "eslestirilmis_indirim.png")
    plot_violation_rate(df, out_dir / "ihlal_orani.png")
    print((out_dir / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
