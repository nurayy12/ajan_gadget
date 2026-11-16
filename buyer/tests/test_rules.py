"""Takımın 6 ihlal kodunun alıcı tarafı: alıcı bunları hiçbir durumda ihlal etmemeli.

over_budget    alıcı teklifi + alıcının ödediği kargo (Dolap eşikleri), bütçeyi aşmamalı
below_floor    (satıcı kuralı; alıcıyı ilgilendirmez)
round_limit    tur numarası 5'i geçmemeli
price_mismatch mesajda yazan fiyat, kodun fiyatı olmalı (ve mesajda fiyat yazmalı)
floor_leak     mesajda ilanların alt sınırı (ya da toplamı) geçmemeli
budget_leak    mesajda alıcının bütçesi geçmemeli

Not: Mesajdaki sayı, o teklifin kendi fiyatına eşitse sızıntı sayılmaz (tesadüf olabilir).
"""
import re

import pytest

from buyer._policy import buyer_shipping
from buyer.bundle import select_bundle
from buyer.tests.fake_seller import run_fake_negotiation
from buyer.tests.sample_data import LISTINGS, make_scenario
from buyer.text_utils import format_tl

BUDGETS = [100, 300, 450, 700, 1650, 3000]
TARGETS = ["L1", "L2", "L4"]

_NUMBER = re.compile(r"\d[\d.,]*")


def _to_float(token: str) -> float:
    """Türkçe sayı biçimi: '1.250,50' -> 1250.5, '1.216' -> 1216, '760' -> 760."""
    token = token.rstrip(".,")
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        token = token.replace(".", "")
    return float(token)


def price_like_numbers(message: str) -> list[float]:
    """Fiyat sayılabilecek sayılar: 3+ haneli olanlar ya da yanında TL/lira/₺ olanlar."""
    found = []
    for m in _NUMBER.finditer(message):
        value = _to_float(m.group())
        digits = re.sub(r"\D", "", m.group())
        after = message[m.end(): m.end() + 6].lower()
        if len(digits) >= 3 or re.match(r"\s*(tl|lira|₺)", after):
            found.append(value)
    return found


def leaked(message: str, offer_price: float, secrets: list[float]) -> list[float]:
    """Mesajda geçen gizli değerler (teklifin kendi fiyatına eşit olanlar sayılmaz)."""
    numbers = price_like_numbers(message)
    return [s for s in secrets if s != offer_price and any(abs(n - s) < 0.005 for n in numbers)]


def run(budget, target, mode):
    scenario = make_scenario(budget, target_listing_id=target)
    bundle = select_bundle(scenario, LISTINGS, mode)
    result = run_fake_negotiation(scenario, bundle, mode)
    return scenario, bundle, result


def buyer_offers(result):
    return [o for o in result.offers if o.sender == "buyer"]


# --- Kontrol fonksiyonlarının kendisi ---------------------------------------

def test_price_parser_reads_turkish_numbers():
    assert price_like_numbers("Teklifim 1.250,50 TL, 2 ürün için") == [1250.5]
    assert price_like_numbers("Paket 1.216 TL olur") == [1216]
    assert price_like_numbers("760 TL") == [760]
    assert price_like_numbers("5 TL olur mu") == [5]


def test_leak_check_ignores_own_price_but_catches_others():
    assert leaked("Paket 1.350 TL olur", 1350, [1350.0]) == []        # tesadüf: kendi fiyatı
    assert leaked("Paket 1.350 TL olur", 1300, [1350.0]) == [1350.0]  # gerçek sızıntı


# --- Alıcının kuralları ihlal etmediğinin kanıtı -----------------------------

@pytest.mark.parametrize("mode", ["single", "bundle"])
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("budget", BUDGETS)
def test_over_budget(budget, target, mode):
    scenario, bundle, result = run(budget, target, mode)
    for offer in buyer_offers(result):
        assert offer.price + buyer_shipping(bundle, offer.price) <= budget + 1e-9


@pytest.mark.parametrize("mode", ["single", "bundle"])
@pytest.mark.parametrize("budget", BUDGETS)
def test_round_limit(budget, mode):
    _, _, result = run(budget, "L1", mode)
    assert max(o.round for o in result.offers) <= 5
    assert result.rounds <= 5


@pytest.mark.parametrize("mode", ["single", "bundle"])
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("budget", BUDGETS)
def test_price_mismatch(budget, target, mode):
    _, _, result = run(budget, target, mode)
    for offer in buyer_offers(result):
        assert format_tl(offer.price) in offer.message          # mesajda fiyat var
        assert price_like_numbers(offer.message) == [offer.price]  # başka fiyat yok


@pytest.mark.parametrize("mode", ["single", "bundle"])
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("budget", BUDGETS)
def test_floor_leak(budget, target, mode):
    _, bundle, result = run(budget, target, mode)
    secrets = [l.floor_price for l in bundle] + [sum(l.floor_price for l in bundle)]
    for offer in buyer_offers(result):
        assert leaked(offer.message, offer.price, secrets) == []


@pytest.mark.parametrize("mode", ["single", "bundle"])
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("budget", BUDGETS)
def test_budget_leak(budget, target, mode):
    _, _, result = run(budget, target, mode)
    for offer in buyer_offers(result):
        assert leaked(offer.message, offer.price, [float(budget)]) == []
