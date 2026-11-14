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
python -m pytest -q
```

Yalnızca alıcı ve karşılaştırma koşulunun testleri için: `python -m pytest buyer baseline -q`.

Tek bir pazarlığı baştan sona çalıştırmak (alıcı + satıcı, sahte LLM ile):

Windows (PowerShell):

```
$env:USE_MOCK_LLM="1"; python -m scripts.run_one
```

macOS / Linux:

```
USE_MOCK_LLM=1 python -m scripts.run_one
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
| `core/` | Satıcı ajanı ve pazarlık motoru. Satıcının fiyatını zamana bağlı taviz fonksiyonuyla kod hesaplar (β = 0,5: yavaş taviz, T = 5 tur); LLM yalnızca Türkçe mesajı yazar. `check` kural kontrolü her teklifi denetler; ihlal olursa motor bir kez yeniden dener, olmazsa şablon mesajla düzeltir. `run_negotiation` bir pazarlığı baştan sona yürütür. Testleri `tests/` içinde. |
| `data/` | Sabit seed (42) ile üretilen veri: 50 ilan, 15 satıcı, 15 senaryo (`listings.json`, `scenarios.json`, ayrıca küçük `sample_listings.json`). `generate.py` üretir, `validate.py` şemaya göre doğrular ve paket pazarlığının mümkün olup olmadığını raporlar. |
| `eval/` | Deney ve ölçüm. `run_experiments.py` her senaryoyu 4 koşulda çalıştırır (asıl sistem / yalnızca LLM × tek ürün / paket) ve `results.jsonl`'a yazar; `metrics.py` bu dosyadan özet tablo (CSV ve Markdown) ile grafikleri üretir. |
| `app.py` | Pazar yeri görünümlü Streamlit demosu: alıcı bir ürün yazar, ajan satıcılarla pazarlık edip en iyi teklifleri sıralar; satıcı kendi ilanlarını ve teklifleri görür. Satıcının alt sınırı hiçbir ekranda gösterilmez. |

## Çalıştırma komutları

Tüm komutlar depo kökünden, sanal ortam açıkken çalıştırılır. Sahte LLM için önce `USE_MOCK_LLM=1` ayarla
(PowerShell: `$env:USE_MOCK_LLM="1"`, macOS/Linux: `export USE_MOCK_LLM=1`).

- `core/`: `python -m scripts.run_one` (tek pazarlık), `python -m pytest tests -q` (testler)
- `data/`: `python -m data.generate` (veriyi üretir), `python -m data.validate` (doğrular)
- `eval/`: `python -m eval.run_experiments --limit 2` (iki senaryoyla deneme), `python -m eval.run_experiments` (tüm deney; başlamadan onay ister, `--yes` ile sormaz), ardından `python -m eval.metrics` (tablo ve grafikler `eval/out/` içine yazılır)
- `app.py`: `streamlit run app.py`
