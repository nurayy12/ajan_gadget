"""Kökteki gerçek policy.py (Rabia) ile testlerde kullanılan taklidin aynı değerleri verdiğini kontrol eder.

policy.py repoda yoksa bu testler atlanır. Taklit ile gerçek ayrışırsa burada kırılır;
o zaman ya fake_policy.py ya da buyer testlerindeki sayılar güncellenmelidir.
"""
import importlib.util
import itertools

import pytest

from buyer.tests import fake_policy
from buyer.tests.sample_data import LISTINGS

# Fixture sys.modules["policy"]'yi taklitle değiştirmeden ÖNCE (toplama anında) gerçeği ara.
_REAL_SPEC = importlib.util.find_spec("policy")

pytestmark = pytest.mark.skipif(_REAL_SPEC is None, reason="kökte policy.py yok")


@pytest.fixture
def real():
    module = importlib.util.module_from_spec(_REAL_SPEC)
    _REAL_SPEC.loader.exec_module(module)
    return module


BASKETS = [LISTINGS[:1], LISTINGS[:2], LISTINGS[:3], [LISTINGS[2]], [LISTINGS[8]], LISTINGS[3:5]]


def test_discount_rates_match(real):
    for n in range(1, 8):
        assert real.bundle_discount_rate(n) == pytest.approx(fake_policy.bundle_discount_rate(n))


@pytest.mark.parametrize("basket", BASKETS)
def test_floor_and_package_shipping_match(real, basket):
    assert real.bundle_floor(basket) == pytest.approx(fake_policy.bundle_floor(basket))
    assert real.package_shipping(basket) == pytest.approx(fake_policy.package_shipping(basket))


@pytest.mark.parametrize("basket,price", list(itertools.product(BASKETS, [0, 100, 249.99, 250, 300, 399.99, 400, 1000])))
def test_buyer_shipping_matches(real, basket, price):
    assert real.buyer_shipping(basket, price) == pytest.approx(fake_policy.buyer_shipping(basket, price))


@pytest.mark.parametrize("basket,budget", list(itertools.product(BASKETS, [30, 150, 300, 420, 455, 700, 1650, 5000])))
def test_max_affordable_price_matches(real, basket, budget):
    assert real.max_affordable_price(basket, budget) == pytest.approx(
        fake_policy.max_affordable_price(basket, budget), abs=0.011)
