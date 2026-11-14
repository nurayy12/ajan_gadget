"""Taviz fonksiyonu ve alıcının tur hedef fiyatı. Fiyatı her zaman kod hesaplar."""
from schemas import Listing, Scenario

from . import config
from .bundle import bundle_shipping


def concession_price(start: float, limit: float, round_no: int,
                     beta: float = config.BETA, T: int = config.T) -> float:
    """fiyat(t) = başlangıç + (sınır - başlangıç) * (t / T) ** (1 / beta).

    t, 0..T aralığına sıkıştırılır: 5. turda fiyat tam sınıra varır.
    """
    t = min(max(round_no, 0), T)
    return start + (limit - start) * (t / T) ** (1 / beta)


def buyer_target_price(scenario: Scenario, bundle: list[Listing], round_no: int) -> float:
    """Alıcının bu turdaki hedef fiyatı (paketin toplam fiyatı, kargo hariç, 2 basamak).

    başlangıç = liste toplamının %70'i
    sınır     = min(bütçe - kargo, liste toplamı)
    Bütçe çok kısıtlıysa başlangıç sınırı aşmasın diye start = min(start, limit).
    """
    list_total = sum(l.list_price for l in bundle)
    shipping = bundle_shipping(bundle, scenario.target_listing_id)
    limit = max(0.0, min(scenario.budget - shipping, list_total))
    start = min(config.START_FRACTION * list_total, limit)
    return round(concession_price(start, limit, round_no), 2)
