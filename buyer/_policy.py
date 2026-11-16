"""Ortak kural modülü (kökteki policy.py, Rabia yazıyor) için tek giriş noktası.

buyer/ ve baseline/ policy'ye yalnızca buradan ulaşır. Modül çağrı anında yüklenir
(import anında değil); böylece policy.py henüz repoda yokken `import buyer` kırılmaz
ve testler policy'yi sys.modules üzerinden taklit edebilir. policy.py yoksa ilk çağrıda
açıklayıcı bir ImportError verilir.

Arayüz (policy.py):
  bundle_discount_rate(n_items) -> float   paket indirim oranı (2 ürün %5, 3+ ürün %10)
  bundle_floor(items) -> float             alt sınırlar toplamı x (1 - indirim)
  package_shipping(items) -> float         sepetin kargosu = max(shipping_cost)
  buyer_shipping(items, price) -> float    alıcının ödediği kargo (Dolap eşikleri)
  max_affordable_price(items, budget)      p + buyer_shipping(items, p) <= budget olan en yüksek p
"""
import importlib

from schemas import Listing


def _policy():
    try:
        return importlib.import_module("policy")
    except ImportError as exc:
        raise ImportError(
            "Kökte policy.py bulunamadı (ortak kargo/indirim kuralları). "
            "Depo kökünden çalıştırdığından ve policy.py'nin yüklendiğinden emin ol."
        ) from exc


def bundle_discount_rate(n_items: int) -> float:
    return _policy().bundle_discount_rate(n_items)


def bundle_floor(items: list[Listing]) -> float:
    return _policy().bundle_floor(items)


def package_shipping(items: list[Listing]) -> float:
    return _policy().package_shipping(items)


def buyer_shipping(items: list[Listing], price: float) -> float:
    return _policy().buyer_shipping(items, price)


def max_affordable_price(items: list[Listing], budget: float) -> float:
    return _policy().max_affordable_price(items, budget)
