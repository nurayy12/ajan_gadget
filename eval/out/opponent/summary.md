# Rakip modelleme: satıcının taviz tipi

Veri: 3000 sentetik pazarlık (1000 / sınıf), sınıflar boulware, linear, conceder. Özellikler yalnızca alıcının gördüğü bilgiler (liste toplamı, ürün sayısı, satıcı teklifleri).

## Ana sonuç: ilk 2 satıcı teklifi, 5 katlı tabakalı çapraz doğrulama

Precision, Recall, F1 ve ROC-AUC makro ortalamadır (ROC-AUC: bire karşı hepsi).

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | F1 std |
|---|---|---|---|---|---|---|
| Çoğunluk sınıfı (taban çizgisi) | 0.333 | 0.111 | 0.333 | 0.167 | 0.500 | 0.000 |
| Lojistik regresyon | 0.853 | 0.852 | 0.853 | 0.852 | 0.961 | 0.009 |
| Random forest | 0.842 | 0.841 | 0.842 | 0.841 | 0.953 | 0.007 |
| MLP | 0.852 | 0.852 | 0.852 | 0.852 | 0.960 | 0.007 |

En iyi model (F1): Lojistik regresyon. Karmaşıklık matrisi: karmasiklik_matrisi.png

## Gördüğü teklif sayısına göre doğruluk

| Model | Doğruluk, 1 teklif | Doğruluk, 2 teklif | Doğruluk, 3 teklif |
|---|---|---|---|
| Lojistik regresyon | 0.791 | 0.853 | 0.865 |
| MLP | 0.797 | 0.852 | 0.861 |
| Random forest | 0.778 | 0.842 | 0.859 |
| Çoğunluk sınıfı (taban çizgisi) | 0.333 | 0.333 | 0.333 |

Grafik: dogruluk_teklif_sayisi.png