"""Her senaryoyu "single" ve "bundle" modunda çalıştırır, sonuçları results.jsonl'a yazar.

Çalıştırma (proje kökünden):  python -m eval.run_experiments
Yarıda kesilirse aynı komutla kaldığı yerden sürer.

Dosyadaki her satır bir zarftır:
  {"scenario_id", "mode", "status": "ok" | "error", "error", "result"}
"result" alanı NegotiationResult'ın JSON halidir (hata varsa null).
"""
import argparse
import json
import traceback
from pathlib import Path
from typing import Callable

from schemas import Listing, NegotiationResult, Scenario
from data.validate import load_listings, load_scenarios

# GERÇEK FONKSİYONA GEÇİŞ: yalnızca aşağıdaki satırı değiştir, örn.
#   from core.negotiation import run_negotiation as negotiate
from eval.fake import fake_run_negotiation as negotiate

NegotiateFn = Callable[..., NegotiationResult]
MODES = ("single", "bundle")
ROOT = Path(__file__).parent.parent


def load_done(path: str | Path, include_errors: bool = True) -> set[tuple[str, str]]:
    """Dosyada zaten bulunan (scenario_id, mode) çiftlerini döndürür.

    include_errors=False ise hata kayıtları "yapılmış" sayılmaz, yani tekrar denenir.
    """
    done: set[tuple[str, str]] = set()
    path = Path(path)
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if include_errors or record["status"] == "ok":
            done.add((record["scenario_id"], record["mode"]))
    return done


def run_one(negotiate_fn: NegotiateFn, scenario: Scenario,
            listings: list[Listing], mode: str) -> dict:
    """Tek bir pazarlığı çalıştırır ve zarf kaydını döndürür; hata olursa yakalayıp kaydeder."""
    record = {"scenario_id": scenario.scenario_id, "mode": mode,
              "status": "ok", "error": None, "result": None}
    try:
        result = negotiate_fn(scenario, listings, mode, auto_approve=True)
        record["result"] = result.model_dump()
    except Exception as exc:
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    return record


def run_all(negotiate_fn: NegotiateFn, scenarios: list[Scenario], listings: list[Listing],
            out_path: str | Path, retry_errors: bool = False) -> None:
    """Tüm senaryo x mod çiftlerini çalıştırır; yapılmış olanları atlar.

    Her sonuç biter bitmez dosyaya eklenir (append), böylece program kesilse
    bile o ana kadarki sonuçlar kaybolmaz.
    """
    done = load_done(out_path, include_errors=not retry_errors)
    with open(out_path, "a", encoding="utf-8") as f:
        for scenario in scenarios:
            for mode in MODES:
                if (scenario.scenario_id, mode) in done:
                    print(f"atlandı  {scenario.scenario_id} {mode}")
                    continue
                record = run_one(negotiate_fn, scenario, listings, mode)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                print(f"{record['status']:7}  {scenario.scenario_id} {mode}")


def main() -> None:
    """Komut satırı girişi: veri dosyalarını okur ve deneyi başlatır."""
    parser = argparse.ArgumentParser(description="Tek ürün / paket pazarlığı deneyi")
    parser.add_argument("--listings", default=ROOT / "data" / "listings.json")
    parser.add_argument("--scenarios", default=ROOT / "data" / "scenarios.json")
    parser.add_argument("--out", default=ROOT / "eval" / "results.jsonl")
    parser.add_argument("--retry-errors", action="store_true",
                        help="Daha önce hata vermiş çalıştırmaları tekrar dene")
    args = parser.parse_args()
    run_all(negotiate, load_scenarios(args.scenarios), load_listings(args.listings),
            args.out, retry_errors=args.retry_errors)


if __name__ == "__main__":
    main()
