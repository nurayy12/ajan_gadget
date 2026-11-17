# Deney özeti

Tekrar sayısı: 3. Anlaşma alanı p_min = paket indirimli alt sınır, p_max = bütçeyle ödenebilecek en yüksek fiyat (Dolap kargo kuralıyla).

| Sistem | Mod | Çalıştırma | Senaryo | Anlaşma oranı (%) | Ort. indirim (%) | Ort. alıcı faydası | Ort. satıcı kazancı (TL) | Ort. satıcı faydası | AgenticPay alıcı skoru | AgenticPay satıcı skoru | AgenticPay genel skor | Ort. tur | Kayıtlı ihlal oranı (%) | Ulaşan ihlal oranı (%) | Aralık dışı anlaşma | LLM hatalı çalıştırma | ZOPA'sız çalıştırma | Ort. kargo tasarrufu (TL) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Asıl sistem | Tek ürün | 120 | 40 | 92.50 | 8.52 | 0.30 | 160.46 | 0.70 | 54.67 | 74.53 | 80.75 | 4.67 | 22.50 | 0.00 | 0 | 0 | 3 | 0.00 |
| Asıl sistem | Paket | 120 | 40 | 92.50 | 9.29 | 0.29 | 442.33 | 0.71 | 54.34 | 75.15 | 80.03 | 4.47 | 10.83 | 0.00 | 0 | 0 | 3 | 23.78 |
| Yalnızca LLM | Tek ürün | 120 | 40 | 4.17 | 15.72 | 0.68 | 30.60 | 0.32 | 2.74 | 1.94 | 2.46 | 4.99 | 50.83 | 50.83 | 0 | 0 | 3 | 0.00 |
| Yalnızca LLM | Paket | 120 | 40 | 14.17 | 16.96 | 0.90 | 145.73 | 0.10 | 8.64 | 4.36 | 4.68 | 4.83 | 75.83 | 75.83 | 5 | 0 | 3 | 31.17 |

## Karşılaştırma 1: asıl sistemde tek ürün ve paket indirimi

Wilcoxon işaretli sıralar testi (indirim, paket − tek ürün): n = 32 senaryo, medyan fark = 0.90 puan, W = 46.0, p < 0.0001
Senaryo başına tekrar ortalaması kullanıldı; yalnızca paket kurulan senaryolar.

## Karşılaştırma 2: paket modunda ihlal oranı (test yapılmadı)

| Sistem | Çalıştırma (n) | Kayıtlı ihlalli çalıştırma | Kayıtlı ihlal oranı (%) | Ulaşan ihlalli çalıştırma | Ulaşan ihlal oranı (%) |
|---|---|---|---|---|---|
| Asıl sistem | 120 | 13 | 10.83 | 0 | 0.00 |
| Yalnızca LLM | 120 | 91 | 75.83 | 91 | 75.83 |

Kayıtlı ihlal: kural denetiminin yakaladığı her ihlal. Asıl sistemde ihlalli taslak yeniden ürettirilir ya da şablonla değiştirilir, bu yüzden kayıtlıdır ama karşı tarafa ulaşmaz. Ulaşan ihlal: gönderilen tekliflerde kalan ihlal. Yalnızca LLM sisteminde ihlaller engellenmediği için iki oran aynıdır.

## Anlaşma alanı olmayan çalıştırmalar

| Sistem | Mod | ZOPA'sız çalıştırma | Anlaşma | Doğru davranış (%) |
|---|---|---|---|---|
| Asıl sistem | Tek ürün | 3 | 0 | 100.00 |
| Asıl sistem | Paket | 3 | 0 | 100.00 |
| Yalnızca LLM | Tek ürün | 3 | 0 | 100.00 |
| Yalnızca LLM | Paket | 3 | 1 | 66.67 |

## Mesaj çeşitliliği

| Sistem | Mod | Taraf | Mesaj | Benzersiz kalıp (%) | distinct-1 | distinct-2 |
|---|---|---|---|---|---|---|
| Asıl sistem | Tek ürün | Alıcı | 561 | 30.48 | 0.05 | 0.10 |
| Asıl sistem | Tek ürün | Satıcı | 504 | 90.87 | 0.13 | 0.32 |
| Asıl sistem | Paket | Alıcı | 537 | 37.24 | 0.07 | 0.14 |
| Asıl sistem | Paket | Satıcı | 504 | 95.83 | 0.13 | 0.33 |
| Yalnızca LLM | Tek ürün | Alıcı | 599 | 58.76 | 0.06 | 0.15 |
| Yalnızca LLM | Tek ürün | Satıcı | 598 | 37.63 | 0.04 | 0.11 |
| Yalnızca LLM | Paket | Alıcı | 580 | 61.21 | 0.07 | 0.18 |
| Yalnızca LLM | Paket | Satıcı | 578 | 45.50 | 0.06 | 0.14 |

Benzersiz kalıp: sayılar yok sayıldığında farklı mesaj oranı. distinct-n: farklı n-gram / toplam n-gram (Li ve ark. 2016). Düşük değer, mesajların aynı kalıpla tekrarlandığını gösterir.

## İhlal türleri (kayıtlı)

| İhlal türü | Asıl sistem / Tek ürün | Asıl sistem / Paket | Yalnızca LLM / Tek ürün | Yalnızca LLM / Paket |
|---|---|---|---|---|
| price_mismatch | 76 | 32 | 153 | 229 |
| over_budget | 0 | 0 | 81 | 66 |
| floor_leak | 0 | 0 | 31 | 101 |
| budget_leak | 0 | 0 | 11 | 18 |
| below_floor | 0 | 0 | 5 | 34 |
| infeasible_deal | 0 | 0 | 0 | 1 |

## İhlal türleri (karşı tarafa ulaşan)

| İhlal türü | Asıl sistem / Tek ürün | Asıl sistem / Paket | Yalnızca LLM / Tek ürün | Yalnızca LLM / Paket |
|---|---|---|---|---|
| price_mismatch | 0 | 0 | 153 | 229 |
| over_budget | 0 | 0 | 81 | 66 |
| floor_leak | 0 | 0 | 31 | 101 |
| budget_leak | 0 | 0 | 11 | 18 |
| below_floor | 0 | 0 | 5 | 34 |

## Duyarlılık analizi (asıl sistem, LLM'siz, alıcı açılışı %70)

| Alıcı β | Satıcı β | Anlaşma tek ürün (%) | Anlaşma paket (%) | İndirim tek ürün (%) | İndirim paket (%) |
|---|---|---|---|---|---|
| 0.20 | 0.20 | 92.50 | 92.50 | 8.89 | 10.13 |
| 0.20 | 1.00 | 92.50 | 92.50 | 17.39 | 19.58 |
| 0.20 | 2.00 | 92.50 | 92.50 | 18.56 | 21.30 |
| 1.00 | 0.20 | 92.50 | 92.50 | 8.52 | 9.29 |
| 1.00 | 1.00 | 92.50 | 92.50 | 12.96 | 14.16 |
| 1.00 | 2.00 | 92.50 | 92.50 | 15.24 | 16.74 |
| 2.00 | 0.20 | 92.50 | 92.50 | 7.09 | 7.22 |
| 2.00 | 1.00 | 92.50 | 92.50 | 10.88 | 11.68 |
| 2.00 | 2.00 | 92.50 | 92.50 | 12.88 | 13.93 |

Tüm ızgara (açılış %60/%70/%80): sensitivity.csv. Isı haritaları: duyarlilik_anlasma.png, duyarlilik_indirim.png.
