"""Taviz fonksiyonu ve alıcının tur hedef fiyatı. Fiyatı her zaman kod hesaplar.

Kaynaklar (parametre seçimleri):
- START_FRACTION = 0.70: Dolap yardım sayfalarına göre alıcı, ilan fiyatının en fazla %30
  indirimiyle teklif verebilir; ilk teklif bu sınırın hemen üstünde (liste x 0.70) başlar.
- BETA = 1.0: Genius / NegMAS zamana bağlı taviz ailesinde "Linear" (Boulware 0.2,
  Linear 1, Conceder 2). Beta küçüldükçe taviz gecikir, büyüdükçe erkene çekilir.
- Kabul koşulu (agent.py): karşı tarafın son fiyatı bu turun hedefine eşit ya da altındaysa
  kabul; Baarslag ve ark. 2014, "AC_next" kabul koşulu.
"""
import math

from schemas import Listing, Scenario

from . import config
from ._policy import buyer_shipping, max_affordable_price


def concession_price(start: float, limit: float, round_no: int,
                     beta: float | None = None, T: int | None = None) -> float:
    """fiyat(t) = başlangıç + (sınır - başlangıç) * (t / T) ** (1 / beta).

    t, 0..T aralığına sıkıştırılır: T. turda fiyat tam sınıra varır.
    beta ve T verilmezse config.BETA ve config.T ÇAĞRI ANINDA okunur (varsayılan argümanda
    yakalanmaz); böylece eval/ çalışma anında config değerlerini değiştirebilir.
    """
    beta = config.BETA if beta is None else beta
    T = config.T if T is None else T
    t = min(max(round_no, 0), T)
    return start + (limit - start) * (t / T) ** (1 / beta)


def _floor_cents(x: float) -> float:
    return math.floor(x * 100 + 1e-6) / 100


def _within_budget(price: float, bundle: list[Listing], budget: float) -> float:
    """Teklif + kargo bütçeyi aşıyorsa teklifi 'bütçe - kargo'ya indirir.

    Dolap kargosu fiyat arttıkça basamak basamak düşer (örn. 399,99 TL için kargo 29,99,
    400 TL için 0), yani p + kargo(p) tek yönlü artmaz: sınırın altındaki bir fiyat bile
    bütçeyi aşabilir. Her indirme kargoyu aynı kalır ya da artırır; en fazla 3 basamak
    olduğu için birkaç adımda sabitlenir.
    """
    for _ in range(4):
        shipping = buyer_shipping(bundle, price)
        if price + shipping <= budget + 1e-9:
            break
        price = max(0.0, _floor_cents(budget - shipping))
    return price


def buyer_target_price(scenario: Scenario, bundle: list[Listing], round_no: int) -> float:
    """Alıcının bu turdaki hedef fiyatı (paketin toplam fiyatı, kargo hariç, 2 basamak).

    başlangıç = config.START_FRACTION x liste toplamı
    sınır     = max_affordable_price(bundle, bütçe): liste toplamını aşmayan ve
                fiyat + alıcının ödediği kargo <= bütçe olan en yüksek fiyat
    Bütçe çok kısıtlıysa başlangıç sınırı aşmasın diye start = min(start, limit).
    """
    list_total = sum(l.list_price for l in bundle)
    limit = max(0.0, max_affordable_price(bundle, scenario.budget))
    start = min(config.START_FRACTION * list_total, limit)
    price = round(concession_price(start, limit, round_no), 2)
    return _within_budget(price, bundle, scenario.budget)
