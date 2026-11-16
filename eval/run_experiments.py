"""Her senaryoyu 2 sistem x 2 mod = 4 koşulda, her koşulu birkaç kez çalıştırır; sonuçları results.jsonl'a yazar.

Sistemler: "system" (asıl sistem: fiyatı kod hesaplar) ve "llm_only" (karşılaştırma).
Modlar   : "single" (tek ürün) ve "bundle" (paket).
Tekrar   : LLM mesajları rastgelelik içerdiği için her koşul --repeats kez çalıştırılır (varsayılan 3).
           Asıl sistemde fiyatlar her tekrarda aynıdır; değişebilen mesajlar ve ihlallerdir.

Çalıştırma (proje kökünden):
  python -m eval.run_experiments                       # tüm deney, başlamadan önce onay ister
  python -m eval.run_experiments --limit 2 --repeats 1 # deneme
  python -m eval.run_experiments --yes                 # onay sormadan başla
Yarıda kesilirse aynı komutla kaldığı yerden sürer.

Dosyadaki her satır bir zarftır:
  {"scenario_id", "system", "mode", "repeat", "status": "ok" | "error", "error",
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
RunKey = tuple[str, str, str, int]   # (scenario_id, system, mode, repeat)
MODES = ("single", "bundle")
ROOT = Path(__file__).parent.parent

# Süre tahmini: 14 Kasım'da Ollama + gemma3:4b ile ölçülen ortalama çalıştırma süreleri (saniye).
SECONDS_PER_RUN = {"system": 25.0, "llm_only": 100.0}


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


def record_key(record: dict) -> RunKey:
    """Bir kaydın anahtarı. Eski kayıtlarda system ve repeat alanı yoksa "system" ve 0 sayılır."""
    return (record["scenario_id"], record.get("system", "system"), record["mode"],
            int(record.get("repeat", 0)))


def load_done(path: str | Path, include_errors: bool = True) -> set[RunKey]:
    """Dosyada zaten bulunan (scenario_id, system, mode, repeat) dörtlülerini döndürür.

    include_errors=False ise hata kayıtları "yapılmış" sayılmaz, yani tekrar denenir.
    """
    return {record_key(r) for r in read_records(path) if include_errors or r["status"] == "ok"}


def run_one(negotiate_fn: NegotiateFn, system: str, scenario: Scenario, listings: list[Listing],
            mode: str, repeat: int, meter: TokenMeter) -> dict:
    """Tek bir pazarlığı çalıştırır ve zarf kaydını döndürür; hata olursa yakalayıp kaydeder.

    Token sayıları, çalıştırmadan önceki ve sonraki sayaç farkından bulunur.
    """
    record = {"scenario_id": scenario.scenario_id, "system": system, "mode": mode,
              "repeat": repeat, "status": "ok", "error": None, "result": None}
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


def pending_runs(scenarios: list[Scenario], done: set[RunKey], systems: dict[str, NegotiateFn],
                 repeats: int) -> list[tuple[int, Scenario, str, str, int]]:
    """Henüz yapılmamış çalıştırmalar: (senaryo sırası, senaryo, sistem, mod, tekrar).

    Sıra: önce tüm senaryoların 1. tekrarı, sonra 2. tekrarı... Böylece deney yarıda kalsa bile
    elde her senaryonun en az bir sonucu olur.
    """
    return [(i, s, system, mode, rep)
            for rep in range(repeats)
            for i, s in enumerate(scenarios, start=1)
            for system in systems for mode in MODES
            if (s.scenario_id, system, mode, rep) not in done]


def estimate_seconds(todo: list[tuple], mock: bool) -> float:
    """Kalan çalıştırmaların tahmini süresi (saniye). Mock modda neredeyse sıfır."""
    if mock:
        return 0.05 * len(todo)
    return sum(SECONDS_PER_RUN.get(system, 60.0) for _, _, system, _, _ in todo)


def confirm(todo: list[tuple], n_skipped: int, mock: bool) -> bool:
    """Toplam çalıştırma ve çağrı sayısını, tahmini süreyi yazdırır, kullanıcıdan onay ister."""
    minutes = estimate_seconds(todo, mock) / 60
    by_system = {name: sum(1 for t in todo if t[2] == name) for name in SYSTEMS}
    print(f"Yapılacak çalıştırma: {len(todo)}  (daha önce yapılmış, atlanacak: {n_skipped})")
    print("  " + ", ".join(f"{name}: {n}" for name, n in by_system.items()))
    if mock:
        print("USE_MOCK_LLM=1: API çağrısı yapılmayacak, süre birkaç saniye.")
    else:
        print(f"LLM çağrısı: en fazla {len(todo) * 10} (çalıştırma başına en fazla 10)")
        print(f"Tahmini süre: ~{minutes:.0f} dakika (~{minutes / 60:.1f} saat; asıl sistem "
              f"{SECONDS_PER_RUN['system']:.0f} sn, llm_only {SECONDS_PER_RUN['llm_only']:.0f} sn "
              f"çalıştırma başına, Ollama ölçümü)")
        print(f"Model: {os.getenv('MODEL_NAME', 'claude-haiku-5-5')}")
    return input("Devam edilsin mi? [e/h] ").strip().lower() in ("e", "evet", "y", "yes")


def run_all(systems: dict[str, NegotiateFn], scenarios: list[Scenario], listings: list[Listing],
            out_path: str | Path, repeats: int = 3, retry_errors: bool = False,
            ask: bool = True) -> None:
    """Tüm senaryo x sistem x mod x tekrar çalıştırmalarını yapar; yapılmış olanları atlar.

    Başlamadan önce özet yazdırıp onay ister (ask=False ise sormaz). Her sonuç biter
    bitmez dosyaya eklenir; program kesilse bile o ana kadarki sonuçlar kaybolmaz.
    Sonunda dosyadaki tüm kayıtların token toplamını yazdırır.
    """
    done = load_done(out_path, include_errors=not retry_errors)
    todo = pending_runs(scenarios, done, systems, repeats)
    total_possible = len(scenarios) * len(systems) * len(MODES) * repeats
    mock = os.getenv("USE_MOCK_LLM") == "1"
    if not todo:
        print("Tüm çalıştırmalar zaten yapılmış.")
    elif ask and not confirm(todo, total_possible - len(todo), mock):
        print("İptal edildi; hiçbir çalıştırma yapılmadı.")
        return

    meter = TokenMeter()
    meter.install()
    started = time.perf_counter()
    with open(out_path, "a", encoding="utf-8") as f:
        for n, (i, scenario, system, mode, rep) in enumerate(todo, start=1):
            print(f"[{n}/{len(todo)}] tekrar {rep + 1}/{repeats} · senaryo {i}/{len(scenarios)} "
                  f"{scenario.scenario_id} · {system} · {mode} ...", end=" ", flush=True)
            record = run_one(systems[system], system, scenario, listings, mode, rep, meter)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            remaining = estimate_seconds(todo[n:], mock) / 60
            print(f"{record['status']}  {record['seconds']} sn, {record['input_tokens']} girdi / "
                  f"{record['output_tokens']} çıktı token  (kalan ~{remaining:.0f} dk)")

    records = read_records(out_path)
    errors = sum(r["status"] == "error" for r in records)
    print(f"\nDosyadaki kayıt: {len(records)}  (hata: {errors}); bu oturum "
          f"{(time.perf_counter() - started) / 60:.1f} dk sürdü")
    print(f"Toplam token: {sum(r.get('input_tokens', 0) for r in records)} girdi, "
          f"{sum(r.get('output_tokens', 0) for r in records)} çıktı  "
          f"({sum(r.get('llm_calls', 0) for r in records)} LLM çağrısı)")


def main() -> None:
    """Komut satırı girişi: veri dosyalarını okur ve deneyi başlatır."""
    parser = argparse.ArgumentParser(description="Pazarlık deneyi: 2 sistem x 2 mod x tekrar")
    parser.add_argument("--listings", default=ROOT / "data" / "listings.json")
    parser.add_argument("--scenarios", default=ROOT / "data" / "scenarios.json")
    parser.add_argument("--out", default=ROOT / "eval" / "results.jsonl")
    parser.add_argument("--repeats", type=int, default=3, help="Her koşulun tekrar sayısı")
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
    run_all(SYSTEMS, scenarios, load_listings(args.listings), args.out, repeats=args.repeats,
            retry_errors=args.retry_errors, ask=not args.yes)


if __name__ == "__main__":
    main()
