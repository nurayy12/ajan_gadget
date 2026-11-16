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


# --- Paket kademesi, kargo ve tasarruf; bütçe/alt sınır asla görünmez -----------------------

def test_report_bundle_tier_shipping_and_saving():
    text = buyer_report(make_result(True, 1400, ["L1", "L2", "L3"]), LISTINGS)
    assert "Satıcının paket esnekliği: %10 (3 ürün; gerçekleşen indirim yukarıda)" in text
    assert "Kargo: satıcı öder" in text                      # 1400 TL >= 400 TL
    assert "Toplam ödeme (kargo dahil): 1.400 TL" in text
    # ayrı ayrı: 400 (kargo 0) + 900 (kargo 0) + 300 + 29,99 = 1.629,99 -> tasarruf 229,99
    assert "ayrı ayrı alsaydın: 1.629,99 TL" in text
    assert "Toplam tasarruf: 229,99 TL" in text


def test_report_two_items_tier_is_five_percent():
    text = buyer_report(make_result(True, 600, ["L1", "L3"]), LISTINGS)
    assert "Satıcının paket esnekliği: %5 (2 ürün; gerçekleşen indirim yukarıda)" in text


def test_report_buyer_pays_shipping_below_250():
    text = buyer_report(make_result(True, 120, ["L9"], mode="single"), LISTINGS)   # L9: 150 TL, kargo 30
    assert "Kargo: alıcı öder (30 TL)" in text
    assert "Toplam ödeme (kargo dahil): 150 TL" in text
    assert "Paket indirim" not in text and "paket esnekliği" not in text and "ayrı ayrı" not in text   # tek ürün


def test_report_shipping_is_shared_between_250_and_400():
    text = buyer_report(make_result(True, 280, ["L3"], mode="single"), LISTINGS)   # L3: kargo 40
    assert "Kargo: alıcı 29,99 TL öder, kalanı (10,01 TL) satıcıya aittir." in text


def test_report_never_shows_budget_or_floor():
    from schemas import Listing
    # alt sınırlar listede başka hiçbir sayıyla çakışmayan değerler: 123, 456, 789
    items = [Listing(listing_id=f"R{i}", seller_id="sr", title=f"Ürün {i}", description="d", category="c",
                     size=None, condition="iyi", list_price=lp, floor_price=fl, shipping_cost=40)
             for i, (lp, fl) in enumerate([(500, 123), (800, 456), (900, 789)])]
    result = make_result(True, 1700, [l.listing_id for l in items])
    text = buyer_report(result, items)
    floor_sum = 123 + 456 + 789
    for secret in ("123", "456", "789", f"{floor_sum:,}".replace(",", "."), "bütçe", "alt sınır"):
        assert secret not in text, secret


def test_report_does_not_present_tier_as_discount_received():
    # Gerçekleşen indirim ayrı satırda; %10 satıcının esnekliği olarak adlandırılır.
    text = buyer_report(make_result(True, 1400, ["L1", "L2", "L3"]), LISTINGS)
    assert "indirim kademesi" not in text
    assert text.index("İndirim: %") < text.index("Satıcının paket esnekliği")
