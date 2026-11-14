"""Her senaryoyu 2 sistem x 2 mod = 4 koşulda çalıştırır, sonuçları results.jsonl'a yazar.

Sistemler: "system" (asıl sistem: fiyatı kod hesaplar) ve "llm_only" (karşılaştırma).
Modlar   : "single" (tek ürün) ve "bundle" (paket).

Çalıştırma (proje kökünden):
  python -m eval.run_experiments                 # tüm deney, başlamadan önce onay ister
  python -m eval.run_experiments --limit 2       # yalnızca ilk 2 senaryo (deneme)
  python -m eval.run_experiments --yes           # onay sormadan başla
Yarıda kesilirse aynı komutla kaldığı yerden sürer.

Dosyadaki her satır bir zarftır:
  {"scenario_id", "system", "mode", "status": "ok" | "error", "error",
   "input_tokens", "output_tokens", "llm_calls", "seconds", "result"}
"result" alanı NegotiationResult'ın JSON halidir (hata varsa null).
"""
import argparse
import json
import os
import time
import traceback
from pathlib import Path
from typing import Callable

from schemas import Listing, NegotiationResult, Scenario
from data.validate import load_listings, load_scenarios

# ---- GERÇEK FONKSİYONLAR -------------------------------------------------------
from buyer.agent import buyer_turn                     # alıcı ajanının tur hamlesi
from buyer.bundle import select_bundle                 # paket seçimi
from core.negotiation import run_negotiation           # asıl sistem (pazarlık döngüsü)
from core.rules import check                           # kural denetimi
from baseline.llm_only import run_negotiation_llm_only # karşılaştırma sistemi
# --------------------------------------------------------------------------------

NegotiateFn = Callable[[Scenario, list[Listing], str], NegotiationResult]
MODES = ("single", "bundle")
ROOT = Path(__file__).parent.parent

# Süre tahmini için varsayımlar: bir pazarlık en çok 5 tur, turda 2 mesaj (alıcı + satıcı).
MAX_LLM_CALLS_PER_RUN = 10
SECONDS_PER_LLM_CALL = 3.0


def run_system(scenario: Scenario, listings: list[Listing], mode: str) -> NegotiationResult:
    """Asıl sistem: fiyatı kod hesaplar, LLM yalnızca mesaj yazar.

    Alıcı modülünün select_bundle ve buyer_turn fonksiyonları çekirdeğe açıkça verilir;
    verilmezse çekirdek bunları kendi bulmaya çalışır ve bulamazsa yedek davranışa düşer.
    """
    return run_negotiation(scenario, listings, mode, auto_approve=True,
                           select_bundle_fn=select_bundle, buyer_turn_fn=buyer_turn)


def run_llm_only(scenario: Scenario, listings: list[Listing], mode: str) -> NegotiationResult:
    """Karşılaştırma sistemi: fiyatı da LLM belirler; ihlaller core'daki check ile sayılır."""
    return run_negotiation_llm_only(scenario, listings, mode, check_fn=check)


SYSTEMS: dict[str, NegotiateFn] = {"system": run_system, "llm_only": run_llm_only}


class TokenMeter:
    """Anthropic SDK çağrılarındaki girdi/çıktı token sayılarını toplar.

    NegotiationResult içinde token alanı olmadığı için sayım SDK seviyesinde yapılır:
    install(), client.messages.create fonksiyonunu sarar ve her yanıtın usage bilgisini
    sayaçlara ekler. Böylece buyer/, core/ ve baseline/ kodlarına dokunmak gerekmez.
    USE_MOCK_LLM=1 iken API çağrılmadığı için sayaçlar 0 kalır.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def install(self) -> None:
        """SDK'nın create fonksiyonunu sayaçlı sürümle değiştirir (anthropic kurulu değilse bir şey yapmaz)."""
        try:
            from anthropic.resources.messages import Messages
        except ImportError:
            return
        original = Messages.create
        meter = self

        def counted_create(self_, *args, **kwargs):
            response = original(self_, *args, **kwargs)
            usage = getattr(response, "usage", None)
            if usage is not None:
                meter.input_tokens += getattr(usage, "input_tokens", 0) or 0
                meter.output_tokens += getattr(usage, "output_tokens", 0) or 0
            meter.calls += 1
            return response

        Messages.create = counted_create

    def snapshot(self) -> tuple[int, int, int]:
        """O ana kadarki (girdi token, çıktı token, çağrı sayısı)."""
        return self.input_tokens, self.output_tokens, self.calls


def read_records(path: str | Path) -> list[dict]:
    """results.jsonl dosyasındaki tüm kayıtları okur (dosya yoksa boş liste)."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_done(path: str | Path, include_errors: bool = True) -> set[tuple[str, str, str]]:
    """Dosyada zaten bulunan (scenario_id, system, mode) üçlülerini döndürür.

    include_errors=False ise hata kayıtları "yapılmış" sayılmaz, yani tekrar denenir.
    """
    return {(r["scenario_id"], r.get("system", "system"), r["mode"])
            for r in read_records(path) if include_errors or r["status"] == "ok"}


def run_one(negotiate_fn: NegotiateFn, system: str, scenario: Scenario,
            listings: list[Listing], mode: str, meter: TokenMeter) -> dict:
    """Tek bir pazarlığı çalıştırır ve zarf kaydını döndürür; hata olursa yakalayıp kaydeder.

    Token sayıları, çalıştırmadan önceki ve sonraki sayaç farkından bulunur.
    """
    record = {"scenario_id": scenario.scenario_id, "system": system, "mode": mode,
              "status": "ok", "error": None, "result": None}
    tokens_in, tokens_out, calls = meter.snapshot()
    started = time.perf_counter()
    try:
        record["result"] = negotiate_fn(scenario, listings, mode).model_dump()
    except Exception as exc:
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    after_in, after_out, after_calls = meter.snapshot()
    record.update(input_tokens=after_in - tokens_in, output_tokens=after_out - tokens_out,
                  llm_calls=after_calls - calls, seconds=round(time.perf_counter() - started, 2))
    return record


def pending_runs(scenarios: list[Scenario], done: set[tuple[str, str, str]],
                 systems: dict[str, NegotiateFn]) -> list[tuple[int, Scenario, str, str]]:
    """Henüz yapılmamış çalıştırmalar: (senaryo sırası, senaryo, sistem, mod)."""
    return [(i, s, system, mode)
            for i, s in enumerate(scenarios, start=1)
            for system in systems for mode in MODES
            if (s.scenario_id, system, mode) not in done]


def confirm(n_runs: int, n_skipped: int, mock: bool) -> bool:
    """Toplam çağrı sayısını ve tahmini süreyi yazdırır, kullanıcıdan onay ister."""
    max_calls = 0 if mock else n_runs * MAX_LLM_CALLS_PER_RUN
    minutes = max_calls * SECONDS_PER_LLM_CALL / 60
    print(f"Yapılacak çalıştırma: {n_runs}  (daha önce yapılmış, atlanacak: {n_skipped})")
    if mock:
        print("USE_MOCK_LLM=1: API çağrısı yapılmayacak, süre birkaç saniye.")
    else:
        print(f"LLM çağrısı: en fazla {max_calls} "
              f"({MAX_LLM_CALLS_PER_RUN} çağrı/çalıştırma üst sınırıyla)")
        print(f"Tahmini süre: en fazla ~{minutes:.0f} dakika "
              f"(çağrı başına {SECONDS_PER_LLM_CALL:.0f} sn varsayımıyla)")
        print(f"Model: {os.getenv('MODEL_NAME', 'claude-haiku-5-5')}")
    return input("Devam edilsin mi? [e/h] ").strip().lower() in ("e", "evet", "y", "yes")


def run_all(systems: dict[str, NegotiateFn], scenarios: list[Scenario], listings: list[Listing],
            out_path: str | Path, retry_errors: bool = False, ask: bool = True) -> None:
    """Tüm senaryo x sistem x mod çalıştırmalarını yapar; yapılmış olanları atlar.

    Başlamadan önce özet yazdırıp onay ister (ask=False ise sormaz). Her sonuç biter
    bitmez dosyaya eklenir; program kesilse bile o ana kadarki sonuçlar kaybolmaz.
    Sonunda dosyadaki tüm kayıtların token toplamını yazdırır.
    """
    done = load_done(out_path, include_errors=not retry_errors)
    todo = pending_runs(scenarios, done, systems)
    total_possible = len(scenarios) * len(systems) * len(MODES)
    mock = os.getenv("USE_MOCK_LLM") == "1"
    if not todo:
        print("Tüm çalıştırmalar zaten yapılmış.")
    elif ask and not confirm(len(todo), total_possible - len(todo), mock):
        print("İptal edildi; hiçbir çalıştırma yapılmadı.")
        return

    meter = TokenMeter()
    meter.install()
    with open(out_path, "a", encoding="utf-8") as f:
        for n, (i, scenario, system, mode) in enumerate(todo, start=1):
            print(f"[{n}/{len(todo)}] senaryo {i}/{len(scenarios)} {scenario.scenario_id} "
                  f"· {system} · {mode} ...", end=" ", flush=True)
            record = run_one(systems[system], system, scenario, listings, mode, meter)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{record['status']}  {record['seconds']} sn, "
                  f"{record['input_tokens']} girdi / {record['output_tokens']} çıktı token")

    records = read_records(out_path)
    errors = sum(r["status"] == "error" for r in records)
    print(f"\nDosyadaki kayıt: {len(records)}  (hata: {errors})")
    print(f"Toplam token: {sum(r.get('input_tokens', 0) for r in records)} girdi, "
          f"{sum(r.get('output_tokens', 0) for r in records)} çıktı  "
          f"({sum(r.get('llm_calls', 0) for r in records)} LLM çağrısı)")


def main() -> None:
    """Komut satırı girişi: veri dosyalarını okur ve deneyi başlatır."""
    parser = argparse.ArgumentParser(description="Pazarlık deneyi: 2 sistem x 2 mod")
    parser.add_argument("--listings", default=ROOT / "data" / "listings.json")
    parser.add_argument("--scenarios", default=ROOT / "data" / "scenarios.json")
    parser.add_argument("--out", default=ROOT / "eval" / "results.jsonl")
    parser.add_argument("--limit", type=int, default=None,
                        help="Yalnızca ilk N senaryoyu çalıştır (deneme için)")
    parser.add_argument("--retry-errors", action="store_true",
                        help="Daha önce hata vermiş çalıştırmaları tekrar dene")
    parser.add_argument("--yes", action="store_true", help="Onay sormadan başla")
    args = parser.parse_args()

    try:  # .env varsa oku (API anahtarı, MODEL_NAME, USE_MOCK_LLM)
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    scenarios = load_scenarios(args.scenarios)[:args.limit]
    run_all(SYSTEMS, scenarios, load_listings(args.listings), args.out,
            retry_errors=args.retry_errors, ask=not args.yes)


if __name__ == "__main__":
    main()
