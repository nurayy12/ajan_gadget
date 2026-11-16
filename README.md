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

## Ücretsiz çalıştırma: Ollama ile yerel model

API anahtarı olmadan, kendi bilgisayarındaki bir modelle de çalıştırabilirsin. Ollama, Anthropic
SDK'nın kullandığı `/v1/messages` uç noktasını sunar ([Ollama: Anthropic uyumluluğu](https://docs.ollama.com/api/anthropic-compatibility)).

1. [Ollama](https://ollama.com)'yı kur ve modeli indir: `ollama pull gemma3:4b`
2. `.env` dosyasını şöyle yap:

```
ANTHROPIC_BASE_URL=http://localhost:11434
ANTHROPIC_API_KEY=ollama
MODEL_NAME=gemma3:4b
USE_MOCK_LLM=0
```

`ANTHROPIC_BASE_URL`'i Anthropic SDK kendisi okur (kodda ayrıca bir ayar yok); `ollama` değeri Ollama
tarafından yok sayılır, yalnızca SDK boş anahtarla başlamasın diye gerekir. Küçük bir modelin Türkçesi
zayıf olabilir; fiyatı her zaman kod hesapladığı için model yanlış fiyat yazarsa mesaj şablona döner.

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
| `policy.py` | Ortak kargo ve paket indirimi kuralları (Dolap kargo eşikleri, sepet kargosu, indirim kademeleri). `buyer/` ve `baseline/` buna `buyer/_policy.py` üzerinden bağlanır; testlerde taklidi (`buyer/tests/fake_policy.py`) kullanılır. |
| `core/` | Satıcı ajanı ve pazarlık motoru. Satıcının fiyatını zamana bağlı taviz fonksiyonuyla kod hesaplar (β = 0,5: yavaş taviz, T = 5 tur); LLM yalnızca Türkçe mesajı yazar. `check` kural kontrolü her teklifi denetler; ihlal olursa motor bir kez yeniden dener, olmazsa şablon mesajla düzeltir. `run_negotiation` bir pazarlığı baştan sona yürütür. Testleri `tests/` içinde. |
| `data/` | Sabit seed (42) ile üretilen veri: 50 ilan, 15 satıcı, 15 senaryo (`listings.json`, `scenarios.json`, ayrıca küçük `sample_listings.json`). `generate.py` üretir, `validate.py` şemaya göre doğrular ve paket pazarlığının mümkün olup olmadığını raporlar. |
| `eval/` | Deney ve ölçüm. `run_experiments.py` her senaryoyu 4 koşulda çalıştırır (asıl sistem / yalnızca LLM × tek ürün / paket) ve `results.jsonl`'a yazar; `metrics.py` bu dosyadan özet tablo (CSV ve Markdown) ile grafikleri üretir. |
| `app.py` | Pazar yeri görünümlü Streamlit demosu: alıcı bir ürün yazar, ajan satıcılarla pazarlık edip en iyi teklifleri sıralar; satıcı kendi ilanlarını ve teklifleri görür. Satıcının alt sınırı hiçbir ekranda gösterilmez. |

## Kısıtlar ve dayanakları

Her kısıtın değeri, uygulandığı dosya ve dayandığı kaynak. Doğrulayamadığımız kaynaklar açıkça işaretlidir.

| Kısıt | Değer | Dosya | Kaynak |
| --- | --- | --- | --- |
| Teklif indirim sınırı | Alıcı en fazla %30 indirim teklif eder; ilk teklif = 0,70 × liste toplamı | `buyer/config.py` (`START_FRACTION`) | [Dolap Yardım: Fiyat teklifi nedir?](https://dolap-help.freshdesk.com/support/solutions/articles/150000037057-fiyat-teklifi-nedir-) |
| Sepet büyüklüğü | Aynı satıcıdan en fazla 10 ürün | `buyer/bundle.py` (`MAX_BASKET_ITEMS`) | [Dolap Yardım: Dolap'ta sepet kullanımı](https://dolap-help.freshdesk.com/support/solutions/articles/150000041537-dolap-ta-sepet-kullan-m-) |
| Sepet kargosu | Sepette tek kargo; en büyük paket fiyatlanır, kodda `max(shipping_cost)` | `policy.py` (`package_shipping`), `buyer/bundle.py` | Aynı sayfa |
| Kargo ödeme eşikleri | Fiyat < 250 TL: kargo alıcıda; 250–399 TL: alıcı sabit 29,99 TL, kalanı satıcı; ≥ 400 TL: satıcı öder | `policy.py` (`buyer_shipping`), `buyer/pricing.py`, `buyer/bundle.py` | [Dolap Yardım: Kargo ücretini hangi durumlarda satıcı öder?](https://dolap-help.freshdesk.com/support/solutions/articles/150000064282-kargo-%C3%BCcretini-hangi-durumlarda-sat-c-%C3%B6der-) |
| Paket indirimi | 2 ürün %5, 3 ve üzeri %10 | `policy.py` (`BUNDLE_DISCOUNT`) | *Kaynak eklenecek:* Dolap sepet sayfasında paket indirimi geçmiyor |
| Tur sayısı | T = 5 | `buyer/config.py` (`T`) | Backus, Blake, Larsen, Tadelis (2020), *Sequential Bargaining in the Field*, QJE 135(3): 1319–1361 (eBay Best Offer). *Doğrulanacak:* teklif sınırının 3 (2017'de 5) olduğu ve ortalama anlaşma fiyatının listenin %73'ü olduğu bilgisi taranan sayfalarda bulunamadı |
| Alıcının taviz hızı | β = 1,0 ("Linear") | `buyer/config.py` (`BETA`) | Genius / NegMAS zamana bağlı taviz: Boulware e = 0,2, Linear 1, Conceder 2 ([NegMAS belgeleri](https://negmas.readthedocs.io/en/latest/negotiators.html)) |
| Satıcının taviz hızı | β = 0,5 | `core/seller.py` (`SELLER_BETA`) | Elle seçildi (Boulware ile Linear arası); kaynak yok |
| Kabul koşulu | Karşı fiyat bu turun hedefine eşit ya da düşükse kabul | `buyer/agent.py` | Baarslag, Hindriks, Jonker (2014), *Effective acceptance conditions in real-time automated negotiation*, Decision Support Systems 60: 68–77 (`AC_next(1, 0)`) |
| Strateji ile dilin ayrılması | Fiyatı kod hesaplar, LLM yalnızca Türkçe mesaj yazar | `buyer/agent.py`, `core/` | He ve ark. (2018), [*Decoupling Strategy and Generation in Negotiation Dialogues*](https://aclanthology.org/D18-1256/), EMNLP; Xia ve ark. (2024), *Measuring Bargaining Abilities of LLMs* (OG-Narrator), [arXiv:2402.15813](https://arxiv.org/abs/2402.15813) |
| Alıcı faydası | (p_max − p) / (p_max − p_min) | `eval/metrics.py` | Liu, Gu, Song (2026), [*AgenticPay*](https://arxiv.org/abs/2602.06008), Algoritma 1. Not: `eval/` alt sınır olarak paket indirimsiz `floor_total` kullanıyor |
| Gizli bilgi | Bütçe ve alt sınır ne LLM'e (alıcı ajanı) ne raporlara ne de mesajlara girer | `buyer/report.py`, `core/rules.py` (`budget_leak`, `floor_leak`) | Tasarım kararı |

## Çalıştırma komutları

Tüm komutlar depo kökünden, sanal ortam açıkken çalıştırılır. Sahte LLM için önce `USE_MOCK_LLM=1` ayarla
(PowerShell: `$env:USE_MOCK_LLM="1"`, macOS/Linux: `export USE_MOCK_LLM=1`).

- `core/`: `python -m scripts.run_one` (tek pazarlık), `python -m pytest tests -q` (testler)
- `data/`: `python -m data.generate` (veriyi üretir), `python -m data.validate` (doğrular)
- `eval/`: `python -m eval.run_experiments --limit 2` (iki senaryoyla deneme), `python -m eval.run_experiments` (tüm deney; başlamadan onay ister, `--yes` ile sormaz), ardından `python -m eval.metrics` (tablo ve grafikler `eval/out/` içine yazılır)
- `app.py`: `streamlit run app.py`
