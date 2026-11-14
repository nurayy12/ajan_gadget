"""Alıcı tarafının ayarları. Sayıları değiştirmek için yalnızca bu dosyayı düzenle."""

# --- Taviz fonksiyonu (alıcı) ---
# fiyat(t) = başlangıç + (sınır - başlangıç) * (t / T) ** (1 / beta)
START_FRACTION = 0.70  # ilk teklif = liste fiyatları toplamının %70'i
BETA = 1.0             # 1.0 düz çizgi; 1'den büyük erken, küçük geç taviz demek
T = 5                  # toplam tur sayısı (schemas'taki round 1..5 ile aynı)

# --- Arama (BM25) ---
MIN_REL_SCORE = 0.30   # bir ihtiyaç maddesinin en yüksek puanının en az bu kadarını alan ilanlar eşleşir
STEM_PREFIX = 5        # kelimenin ilk kaç harfi alınsın (kaba Türkçe ek atma); 0 = kapalı
