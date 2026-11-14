from schemas import NegotiationResult
from buyer.report import buyer_report
from buyer.tests.sample_data import LISTINGS


def make_result(deal, final_price, ids, mode="bundle"):
    return NegotiationResult(scenario_id="sc1", mode=mode, deal=deal, final_price=final_price,
                             listing_ids=ids, rounds=4, violations=[], offers=[])


def test_report_with_deal():
    text = buyer_report(make_result(True, 1400, ["L1", "L2", "L3"]), LISTINGS)
    assert "Mavi kot pantolon" in text and "Siyah deri ceket" in text
    assert "1.600 TL" in text      # liste toplamı
    assert "1.400 TL" in text      # anlaşılan fiyat
    assert "%12,5" in text         # (1600-1400)/1600


def test_report_without_deal():
    text = buyer_report(make_result(False, None, ["L1"], mode="single"), LISTINGS)
    assert "anlaşma sağlanamadı" in text and "Mavi kot pantolon" in text
