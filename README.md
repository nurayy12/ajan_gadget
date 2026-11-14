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
python -m pytest buyer baseline -q
```

Alıcı ajanının sahte satıcıyla örnek pazarlığı:

```
python -m buyer.demo
```

## Klasör yapısı

| Klasör / dosya | Ne işe yarar |
| --- | --- |
| `schemas.py` | Ortak veri tipleri: `Listing`, `Scenario`, `Offer`, `NegotiationResult`. |
| `buyer/` | Alıcı ajanı: BM25 ile ilan eşleştirme (`find_matches`), paket seçimi (`select_bundle`), taviz fonksiyonuyla teklif üretme (`buyer_turn`) ve sonuç raporu (`buyer_report`). Testleri `buyer/tests/` içinde. |
| `baseline/` | Karşılaştırma koşulu: fiyatı da LLM'in verdiği "yalnızca LLM" pazarlığı (`run_negotiation_llm_only`). Testleri `baseline/tests/` içinde. |
| `core/` | Ekip arkadaşları dolduracak. |
| `data/` | Ekip arkadaşları dolduracak. |
| `eval/` | Ekip arkadaşları dolduracak. |
| `app.py` | Ekip arkadaşları dolduracak. |

## Çalıştırma komutları (ekip arkadaşları dolduracak)

- `core/`: ekip arkadaşları dolduracak
- `data/`: ekip arkadaşları dolduracak
- `eval/`: ekip arkadaşları dolduracak
- `app.py`: ekip arkadaşları dolduracak
