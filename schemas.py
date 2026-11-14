from typing import Literal
from pydantic import BaseModel

class Listing(BaseModel):
    listing_id: str
    seller_id: str
    title: str
    description: str
    category: str
    size: str | None
    condition: str
    list_price: float
    floor_price: float      # satıcının gizli alt sınırı
    shipping_cost: float

class Scenario(BaseModel):
    scenario_id: str
    need_list: list[str]    # alıcının aradığı ürünler, serbest metin
    budget: float           # ürün fiyatı + kargo dahil üst sınır
    target_listing_id: str  # asıl istenen ilan

class Offer(BaseModel):
    sender: Literal["buyer", "seller"]
    round: int              # 1..5
    action: Literal["offer", "counter", "accept", "reject"]
    listing_ids: list[str]
    price: float            # paketin toplam fiyatı, kargo hariç
    message: str            # Türkçe pazarlık mesajı

class NegotiationResult(BaseModel):
    scenario_id: str
    mode: Literal["single", "bundle"]
    deal: bool
    final_price: float | None
    listing_ids: list[str]
    rounds: int
    violations: list[str]
    offers: list[Offer]
