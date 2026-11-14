"""İhtiyaç maddelerini ilanlarla eşleştirme (BM25).

Yapı, ileride ikinci bir sıralayıcı (örn. multilingual-e5-large embedding) eklemeye
uygun: her sıralayıcı `Ranker` arayüzünü sağlar, `build_rankers` listeye ekler,
`_combine` puanları birleştirir (şimdilik tek sıralayıcı; ileride Reciprocal Rank
Fusion burada yapılır).
"""
from typing import Protocol

from rank_bm25 import BM25Okapi

from schemas import Listing

from . import config
from .text_utils import tokenize


class Ranker(Protocol):
    def scores(self, query: str) -> list[float]:
        """Her ilan için bir puan döndürür (ilan sırası, kurulumdaki sırayla aynı)."""
        ...


class BM25Ranker:
    def __init__(self, listings: list[Listing]):
        corpus = [tokenize(f"{l.title} {l.description} {l.category}") for l in listings]
        self._n = len(listings)
        self._bm25 = BM25Okapi(corpus)

    def scores(self, query: str) -> list[float]:
        tokens = tokenize(query)
        if not tokens:
            return [0.0] * self._n
        return [float(s) for s in self._bm25.get_scores(tokens)]


def build_rankers(listings: list[Listing]) -> list[Ranker]:
    return [BM25Ranker(listings)]


def _combine(score_lists: list[list[float]]) -> list[float]:
    """Birden çok sıralayıcının puanını birleştirir. Şimdilik tek sıralayıcı var."""
    return score_lists[0]


def _match_per_need(need_list: list[str], listings: list[Listing]) -> list[list[tuple[Listing, float]]]:
    """Her ihtiyaç maddesi için (ilan, puan) listesi; need_list ile aynı sırada, puana göre azalan.

    Eşik: puan > 0 ve o maddenin en yüksek puanının MIN_REL_SCORE katından az olmayan ilanlar kalır.
    """
    if not listings:
        return [[] for _ in need_list]
    rankers = build_rankers(listings)
    result: list[list[tuple[Listing, float]]] = []
    for need in need_list:
        scores = _combine([r.scores(need) for r in rankers])
        top = max(scores)
        if top <= 0:
            result.append([])
            continue
        cutoff = config.MIN_REL_SCORE * top
        hits = [(l, s) for l, s in zip(listings, scores) if s > 0 and s >= cutoff]
        hits.sort(key=lambda pair: -pair[1])
        result.append(hits)
    return result


def find_matches(need_list: list[str], listings: list[Listing]) -> dict[str, list[Listing]]:
    """Eşleşen ilanları seller_id'ye göre gruplar. Bir ilan birden çok maddeye uysa da bir kez yazılır."""
    per_need = _match_per_need(need_list, listings)
    by_seller: dict[str, list[Listing]] = {}
    for hits in per_need:
        for listing, _score in hits:
            group = by_seller.setdefault(listing.seller_id, [])
            if all(g.listing_id != listing.listing_id for g in group):
                group.append(listing)
    return by_seller
