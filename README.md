# Dolap tarzı ikinci el pazar yerinde LLM ajanlarıyla pazarlık

Alıcı ve satıcı adına pazarlık yapan ajanlar. Alıcı ajanı, ihtiyaç listesindeki ürünleri
aynı satıcıda bulursa **paket** pazarlığı yapar. Fiyatı her zaman kod hesaplar; LLM yalnızca
Türkçe mesaj yazar. Karşılaştırma için fiyatı da LLM'in verdiği bir "yalnızca LLM" koşulu vardır.

## Kurulum

Python **3.11** gerekir.

Windows (PowerShell):

```
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux:

```
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Not: `requirements.txt` yalnızca `buyer/` ve `baseline/` klasörlerinin paketlerini içerir.
Diğer klasörlerin ek paketleri varsa ekip arkadaşları ekleyecek.

## .env dosyası

Depo kökünde `.env` adlı bir dosya oluştur (bu dosya depoya **yüklenmez**, anahtarı kimseyle paylaşma):

```
ANTHROPIC_API_KEY=buraya_kendi_anahtarin
MODEL_NAME=claude-haiku-5-5
USE_MOCK_LLM=0
```

| Değişken | Anlamı |
| --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic API anahtarı. Gerçek LLM çağrıları için gerekir. |
| `MODEL_NAME` | Kullanılacak model adı. Yazılmazsa `claude-haiku-5-5`. |
| `USE_MOCK_LLM` | `1` ise API hiç çağrılmaz; şablon/önceden yazılmış yanıtlar kullanılır (anahtar gerekmez). `0` ise gerçek model. |

## Testleri çalıştırma

Testler `USE_MOCK_LLM=1` ile çalışır, API anahtarı ve internet gerekmez.

```
python -m pytest buyer baseline tests -q
```

Alıcı ajanının sahte satıcıyla örnek pazarlığı:

```
python -m buyer.demo
```

Gerçek alıcı (`buyer/`) ve pazarlık çekirdeği (`core/`) ile `data/sample_listings.json` üzerinde tek ürün (`single`) ve paket (`bundle`) örnek çalıştırması:

```
python -m scripts.run_one
```

## Klasör yapısı

| Klasör / dosya | Ne işe yarar |
| --- | --- |
| `schemas.py` | Ortak veri tipleri: `Listing`, `Scenario`, `Offer`, `NegotiationResult`. |
| `buyer/` | Alıcı ajanı: BM25 ile ilan eşleştirme (`find_matches`), paket seçimi (`select_bundle`), taviz fonksiyonuyla teklif üretme (`buyer_turn`) ve sonuç raporu (`buyer_report`). Testleri `buyer/tests/` içinde. |
| `baseline/` | Karşılaştırma koşulu: fiyatı da LLM'in verdiği "yalnızca LLM" pazarlığı (`run_negotiation_llm_only`). Testleri `baseline/tests/` içinde. |
| `core/` | Pazarlık çekirdeği, satıcı ajanı (`seller_turn`, $\beta=0.5, T=5$ taviz fonksiyonu, 3 denemeli LLM retry/fallback), güvenlik kural katmanı (`check`: `over_budget`, `below_floor`, `round_limit`, `price_mismatch`, `floor_leak`, `budget_leak`) ve müzakere motoru (`run_negotiation`, `approve`, `trace_path`). Testleri `tests/` içinde. |
| `scripts/run_one.py` | Gerçek `buyer/` ve `core/` modüllerini bağlayarak örnek veri üzerinde tek ürün ve paket pazarlığını çalıştırıp tur-tur ekrana yazdıran betik. |
| `data/` | Ekip arkadaşları dolduracak. |
| `eval/` | Ekip arkadaşları dolduracak. |
| `app.py` | Ekip arkadaşları dolduracak. |

## Çalıştırma komutları

- **`core/` ve `scripts/run_one.py`:**
  - Kural ve çekirdek birim testlerini çalıştırmak için: `python -m pytest tests/ -v`
  - Şablon mesajlarla (API anahtarsız) örnek senaryo çalıştırmak için:
    - Windows PowerShell: `$env:USE_MOCK_LLM="1"; python -m scripts.run_one`
    - macOS / Linux: `USE_MOCK_LLM=1 python -m scripts.run_one`
  - Gerçek LLM API ile (`.env` içinde `ANTHROPIC_API_KEY` varken) çalıştırmak için:
    - Windows PowerShell: `$env:USE_MOCK_LLM="0"; python -m scripts.run_one`
    - macOS / Linux: `USE_MOCK_LLM=0 python -m scripts.run_one`
- `data/`: ekip arkadaşları dolduracak
- `eval/`: ekip arkadaşları dolduracak
- `app.py`: ekip arkadaşları dolduracak
