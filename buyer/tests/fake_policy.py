"""policy.py taklidi (yalnızca testler için). Gerçek policy.py repoya gelince
test_policy_contract.py, ikisinin aynı değerleri verdiğini kontrol eder."""
import math

BUNDLE_DISCOUNT = {2: 0.05, 3: 0.10}
_MID_SHIPPING = 29.99   # 250 <= fiyat < 400
_LOW, _HIGH = 250.0, 400.0


def _floor_cents(x: float) -> float:
    return math.floor(x * 100 + 1e-6) / 100


def bundle_discount_rate(n_items: int) -> float:
    if n_items <= 1:
        return 0.0
    return BUNDLE_DISCOUNT[3] if n_items >= 3 else BUNDLE_DISCOUNT[n_items]


def bundle_floor(items) -> float:
    return sum(l.floor_price for l in items) * (1 - bundle_discount_rate(len(items)))


def package_shipping(items) -> float:
    return max((l.shipping_cost for l in items), default=0.0)


def buyer_shipping(items, price: float) -> float:
    if price < _LOW:
        return package_shipping(items)
    if price < _HIGH:
        return _MID_SHIPPING
    return 0.0


def max_affordable_price(items, budget: float) -> float:
    cap = _floor_cents(sum(l.list_price for l in items))
    bands = [(0.0, _LOW, package_shipping(items)), (_LOW, _HIGH, _MID_SHIPPING), (_HIGH, math.inf, 0.0)]
    best = 0.0
    for lo, hi, ship in bands:
        p = min(cap, _floor_cents(budget - ship))
        if hi != math.inf:
            p = min(p, hi - 0.01)
        if p >= lo and p > best:
            best = p
    return round(best, 2)
