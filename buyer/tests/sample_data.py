"""10 ilanlık örnek veri. s1 satıcısının 3 ilanı var (paket pazarlığı için)."""
from schemas import Listing, Scenario


def _l(listing_id, seller_id, title, description, category, size, condition,
       list_price, floor_price, shipping_cost) -> Listing:
    return Listing(
        listing_id=listing_id, seller_id=seller_id, title=title, description=description,
        category=category, size=size, condition=condition,
        list_price=list_price, floor_price=floor_price, shipping_cost=shipping_cost,
    )


LISTINGS = [
    _l("L1", "s1", "Mavi kot pantolon", "Az kullanılmış, rahat kalıp.", "Giyim", "32", "iyi", 400, 300, 50),
    _l("L2", "s1", "Siyah deri ceket", "Gerçek deri, kışlık, temiz.", "Giyim", "M", "çok iyi", 900, 700, 60),
    _l("L3", "s1", "Sırt çantası", "Okul ve gezi için geniş, sağlam.", "Çanta", None, "iyi", 300, 200, 40),
    _l("L4", "s2", "Siyah kot pantolon", "Dar kesim, bir kez giyildi.", "Giyim", "34", "çok iyi", 350, 250, 45),
    _l("L5", "s2", "Spor ayakkabı", "Koşu için hafif, az yıpranmış.", "Ayakkabı", "42", "iyi", 500, 400, 55),
    _l("L6", "s3", "Kırmızı elbise", "Yazlık, hiç giyilmedi.", "Giyim", "S", "yeni", 250, 180, 45),
    _l("L7", "s3", "Yün kazak", "Sıcak tutar, boy uzun.", "Giyim", "L", "iyi", 200, 120, 45),
    _l("L8", "s4", "Fotoğraf makinesi", "Lens dahil, kutusu mevcut.", "Elektronik", None, "iyi", 3000, 2500, 80),
    _l("L9", "s5", "Roman seti", "On kitaplık takım, ciltli.", "Kitap", None, "iyi", 150, 100, 30),
    _l("L10", "s6", "Bisiklet kaskı", "Yol bisikleti için, çatlak yok.", "Spor", "M", "iyi", 350, 250, 60),
]

NEEDS = ["kot pantolon", "deri ceket", "sırt çantası"]


def make_scenario(budget: float, target_listing_id: str = "L1", need_list=None,
                  scenario_id: str = "sc1") -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        need_list=list(NEEDS if need_list is None else need_list),
        budget=budget,
        target_listing_id=target_listing_id,
    )
