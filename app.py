"""Pazar yeri görünümlü Streamlit demo arayüzü ("Askı", kurgusal bir ikinci el moda sitesi).

Çalıştırma (proje kökünden):  streamlit run app.py

Akış:
  Alıcı görünümü : ilanlara göz atar, favorilerine (istek listesi) ürün ekler ve bir ilanda
                   "Ajanım pazarlık etsin" der ya da aradığı ürünü yazıp ajanı tüm satıcılarda
                   gezdirir. Satıcıda favorilerinden başka ürün varsa ajan paket ister.
                   Ajanın getirdiği teklifler sohbet ve sipariş özetiyle gösterilir; alıcı onaylar.
  Satıcı görünümü: satıcı kendi ilanlarını ve ajanının yürüttüğü teklifleri görür; alıcının
                   onayladığı teklifi o da onaylayınca "Anlaşma sağlandı" olur.

Gizlilik: satıcının alt sınırı ve kârı yalnızca satıcı görünümünde, alıcının bütçesi yalnızca
alıcı görünümünde görünür. Üstteki görünüm seçici gerçek bir giriş sistemi değildir; gerçek
uygulamada iki taraf ayrı cihazlardadır.
"""
import html
import time
from pathlib import Path

import streamlit as st

from schemas import Listing, NegotiationResult, Offer, Scenario
from data.generate import SHIPPING_TARIFF
from data.validate import load_listings, match_need
from policy import bundle_discount_rate, bundle_floor, buyer_shipping, package_shipping

# ---- GERÇEK FONKSİYONLAR -------------------------------------------------------
from buyer.agent import buyer_turn
from buyer.bundle import select_bundle
from buyer.report import buyer_report
from buyer.text_utils import format_tl
from core.negotiation import run_negotiation as core_run_negotiation, approve
# --------------------------------------------------------------------------------


def run_negotiation(scenario: Scenario, listings: list[Listing], mode: str,
                    auto_approve: bool = True) -> NegotiationResult:
    """Çekirdeğin pazarlık döngüsünü, alıcı modülünün gerçek fonksiyonlarını vererek çağırır."""
    return core_run_negotiation(scenario, listings, mode, auto_approve=auto_approve,
                                select_bundle_fn=select_bundle, buyer_turn_fn=buyer_turn)


ROOT = Path(__file__).parent
BUYER_VIEW = "Alıcı"
SELLER_VIEW = "Satıcı"
DEFAULT_WISHLIST = ["kot pantolon", "keten gömlek", "sneaker", "omuz çantası"]
CATEGORY_STYLE = {  # kategori -> (simge, kart zemini)
    "kadın giyim": ("👗", "#E8E3F3"),
    "erkek giyim": ("👕", "#DDE7F2"),
    "ayakkabı": ("👟", "#E4EEE6"),
    "çanta": ("👜", "#F3E6DC"),
    "aksesuar": ("🕶️", "#EEF0E2"),
}
CONDITION_STYLE = {  # durum -> (yazı rengi, zemin)
    "yeni etiketli": ("#1F6B4F", "#DDF1E7"),
    "yeni gibi": ("#2F4B9A", "#E1E8F7"),
    "az kullanılmış": ("#6A4A12", "#F6EBCF"),
    "iyi": ("#4A5161", "#E8EAEE"),
}
ITEM_ICONS = [  # başlıkta geçen kelime -> simge (ilk eşleşen kullanılır)
    ("sırt çanta", "🎒"), ("valiz", "🧳"), ("çanta", "👜"), ("cüzdan", "👛"),
    ("ceket", "🧥"), ("mont", "🧥"), ("kaban", "🧥"), ("trençkot", "🧥"), ("hırka", "🧥"),
    ("polar", "🧥"), ("eşofman altı", "👖"), ("jogger", "👖"), ("eşofman", "🧥"), ("tayt", "👖"),
    ("elbise", "👗"), ("etek", "👗"), ("pantolon", "👖"), ("jean", "👖"), ("şort", "🩳"),
    ("gömlek", "👔"), ("tişört", "👕"), ("t-shirt", "👕"), ("atlet", "🎽"), ("kazak", "🧶"),
    ("sweat", "👕"), ("bluz", "👚"), ("pijama", "👕"), ("kravat", "👔"),
    ("ayakkab", "👟"), ("sneaker", "👟"), ("babet", "🥿"), ("loafer", "🥿"), ("bot", "🥾"),
    ("çizme", "👢"), ("topuklu", "👠"), ("sandalet", "🩴"), ("terlik", "🩴"), ("çorap", "🧦"),
    ("gözl", "🕶️"), ("bere", "🧢"), ("şapka", "👒"), ("kemer", "🪢"), ("saat", "⌚"), ("toka", "🎀"),
    ("atkı", "🧣"), ("şal", "🧣"), ("fular", "🧣"), ("mendil", "🧣"), ("eldiven", "🧤"),
    ("kolye", "📿"), ("bileklik", "📿"), ("küpe", "💍"), ("yüzük", "💍"), ("kartlık", "👛"),
]
MAX_OFFERS = 5
GRID_COLUMNS = 4
PACKAGE_NAMES = {fee: name for name, fee in SHIPPING_TARIFF.items()}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,800&display=swap');
:root {
  --ink: #1D2433; --muted: #6B7385; --line: #DCE1E8; --bg: #F3F5F7;
  --denim: #2F4B9A; --denim-dark: #22376F; --tag: #F2B705; --sage: #3E8E6B;
}
html, body, [class*="css"], .stMarkdown, .stButton button, input, textarea {
  font-family: 'Bricolage Grotesque', system-ui, sans-serif !important;
}
.stApp { background: var(--bg); color: var(--ink); }
.block-container { padding-top: 1.2rem; max-width: 1180px; }
header[data-testid="stHeader"] { background: transparent; }

.brand { display: flex; align-items: baseline; gap: .6rem; }
.brand-name { font-size: 2.1rem; font-weight: 800; letter-spacing: -.03em; color: var(--denim); }
.brand-hook { width: 18px; height: 18px; border: 3px solid var(--denim); border-bottom: none;
  border-radius: 10px 10px 0 0; display: inline-block; transform: translateY(-4px); }
.brand-sub { color: var(--muted); font-size: .95rem; }

.hero { background: var(--denim); color: #fff; border-radius: 18px; padding: 1.6rem 1.8rem 1.2rem;
  margin: .6rem 0 1rem; }
.hero h1 { color: #fff; font-size: 2rem; font-weight: 800; letter-spacing: -.02em; margin: 0 0 .3rem;
  line-height: 1.15; }
.hero p { color: #D6DEF3; margin: 0; max-width: 60ch; }

.card { background: #fff; border: 1px solid var(--line); border-radius: 14px; overflow: hidden;
  margin-bottom: .4rem; }
.card-img { height: 150px; display: flex; align-items: center; justify-content: center;
  font-size: 3.6rem; position: relative; }
.card-body { padding: .7rem .8rem .8rem; }
.card-title { font-weight: 600; font-size: .98rem; line-height: 1.25; min-height: 2.5em; }
.card-meta { color: var(--muted); font-size: .82rem; margin-top: .2rem; }
.chip { display: inline-block; font-size: .74rem; font-weight: 600; padding: .12rem .5rem;
  border-radius: 999px; }
.card-img .chip { position: absolute; left: .6rem; top: .6rem; }
.fav { position: absolute; right: .6rem; top: .45rem; font-size: 1.2rem; color: var(--denim); }

/* fiyat etiketi: sitenin imzası */
.tag { display: inline-flex; align-items: center; gap: .45rem; background: var(--tag); color: var(--ink);
  font-weight: 800; padding: .22rem .7rem .22rem .55rem; margin-top: .5rem;
  clip-path: polygon(12px 0, 100% 0, 100% 100%, 12px 100%, 0 50%); padding-left: 1.1rem; }
.tag::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--bg);
  margin-left: -.55rem; }
.tag.big { font-size: 1.5rem; padding: .35rem 1rem .35rem 1.5rem; }
.tag.old { background: #E8EAEE; color: var(--muted); text-decoration: line-through; font-weight: 600; }

.chat { display: flex; flex-direction: column; gap: .5rem; padding: .4rem .3rem .4rem 0;
  max-height: 460px; overflow-y: auto; }
.bubble { max-width: 78%; padding: .6rem .8rem; border-radius: 14px; line-height: 1.4; font-size: .95rem; }
.bubble .who { font-size: .76rem; color: var(--muted); margin-bottom: .15rem; }
.bubble.buyer { align-self: flex-end; background: var(--denim); color: #fff; border-bottom-right-radius: 4px; }
.bubble.buyer .who { color: #C9D3EE; }
.bubble.seller { align-self: flex-start; background: #fff; border: 1px solid var(--line);
  border-bottom-left-radius: 4px; }
.bubble .price { display: inline-block; margin-top: .35rem; font-weight: 800; font-size: .85rem;
  background: var(--tag); color: var(--ink); padding: .05rem .5rem; border-radius: 6px; }
.bubble.accept { border: 2px solid var(--sage); }

.receipt { background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 1rem 1.1rem; }
.receipt h4 { margin: 0 0 .6rem; font-size: 1.05rem; }
.row { display: flex; justify-content: space-between; gap: 1rem; padding: .22rem 0; font-size: .93rem; }
.row .lbl { color: var(--muted); }
.row span:last-child { white-space: nowrap; text-align: right; }
.row.item .lbl { color: var(--ink); }
.row.good span:last-child { color: var(--sage); font-weight: 600; }
.row.total { border-top: 1px dashed var(--line); margin-top: .4rem; padding-top: .55rem;
  font-weight: 800; font-size: 1.08rem; }
.note { color: var(--muted); font-size: .82rem; margin-top: .45rem; }

.offer-head { display: flex; justify-content: space-between; align-items: center; gap: 1rem;
  margin-bottom: .3rem; }
.offer-head h3 { margin: 0; font-size: 1.15rem; }
.seller-pill { display: inline-flex; align-items: center; gap: .4rem; color: var(--muted); font-size: .88rem; }
.avatar { width: 26px; height: 26px; border-radius: 50%; background: var(--denim); color: #fff;
  display: inline-flex; align-items: center; justify-content: center; font-size: .72rem; font-weight: 700; }
.status { font-size: .85rem; font-weight: 600; padding: .25rem .7rem; border-radius: 999px; }
.status.wait { background: #F6EBCF; color: #6A4A12; }
.status.done { background: #DDF1E7; color: #1F6B4F; }

.stButton button { border-radius: 10px; font-weight: 600; }
.stButton button[kind="primary"] { background: var(--denim); border-color: var(--denim); }
.stButton button[kind="primary"]:hover { background: var(--denim-dark); border-color: var(--denim-dark); }
button:focus-visible { outline: 3px solid var(--tag) !important; outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
"""


# ---- veri ve oturum --------------------------------------------------------------

@st.cache_data
def load_data() -> list[Listing]:
    """İlan dosyasını bir kez okur (Streamlit sonucu önbelleğe alır)."""
    return load_listings(ROOT / "data" / "listings.json")


def init_state() -> None:
    """Oturum boyunca saklanan verileri hazırlar.

    Streamlit her tıklamada betiği baştan çalıştırdığı için kalıcı olması gereken
    her şey st.session_state içinde tutulur.
    """
    st.session_state.setdefault("wishlist", list(DEFAULT_WISHLIST))
    st.session_state.setdefault("offers", {})        # hedef listing_id -> teklif kaydı (dict)
    st.session_state.setdefault("budget", 3000)
    st.session_state.setdefault("animate", set())    # sohbeti akarak gösterilecek teklifler


# ---- pazarlık mantığı (görünümden bağımsız) ---------------------------------------

def find_targets(wanted: str, listings: list[Listing]) -> list[Listing]:
    """Sitede tarama: alıcının yazdığı ürünle eşleşen tüm ilanlar (farklı satıcılardan)."""
    return [l for l in listings if match_need(wanted, l)]


def run_agent(run_fn, targets: list[Listing], budget: float, wishlist: list[str],
              listings: list[Listing]) -> dict[str, dict]:
    """Alıcı ajanı: her hedef ilan için satıcının ajanıyla pazarlık yapar, kabul edilenleri döndürür.

    Her hedef için geçici bir Scenario kurulur (hedef = ilan, need_list = istek listesi).
    Paket kararını alıcı modülünün select_bundle fonksiyonu verir: birden fazla ürün
    seçerse mod "bundle", yalnızca hedefi döndürürse "single" olur.
    Bütçeyi aşan ya da anlaşmasız biten pazarlıklar elenir.
    """
    by_id = {l.listing_id: l for l in listings}
    offers: dict[str, dict] = {}
    for target in targets:
        scenario = Scenario(scenario_id=f"WEB-{target.listing_id}", need_list=wishlist,
                            budget=budget, target_listing_id=target.listing_id)
        mode = "bundle" if len(select_bundle(scenario, listings, "bundle")) > 1 else "single"
        result = run_fn(scenario, listings, mode, auto_approve=False)

        accepted = bool(result.offers) and result.offers[-1].action == "accept"
        if not accepted or result.final_price is None:
            continue
        items = [by_id[i] for i in result.listing_ids]
        shipping = buyer_shipping(items, result.final_price)
        total_to_pay = result.final_price + shipping
        if total_to_pay > budget:
            continue
        list_total = sum(l.list_price for l in items)
        shipping_saving = separate_shipping(items, result.final_price) - shipping
        offers[target.listing_id] = {
            "result": result, "seller_id": target.seller_id, "items": items,
            "list_total": list_total, "total_to_pay": total_to_pay, "shipping": shipping,
            "shipping_text": offer_shipping_text(items, result.final_price),
            "shipping_saving": shipping_saving,
            "saving": list_total - result.final_price + shipping_saving,
            "buyer_ok": False, "seller_ok": False, "deal": False,
        }
    return offers


def separate_shipping(items: list[Listing], price: float) -> float:
    """Ürünler ayrı ayrı alınsaydı ödenecek toplam kargo (paket fiyatı liste fiyatlarıyla orantılı bölünür).

    eval/metrics.shipping_saving ile aynı varsayım; Dolap kuralı her parçaya ayrı uygulanır.
    """
    list_total = sum(l.list_price for l in items)
    return sum(buyer_shipping([l], price * l.list_price / list_total) for l in items)


def offer_shipping_text(items: list[Listing], price: float) -> str:
    """Kargoyu kimin ödediğini Dolap kuralıyla anlatır (250 TL altı alıcı, 250-399 paylaşımlı, 400+ satıcı)."""
    fee = buyer_shipping(items, price)
    if fee == 0:
        return "Kargo satıcıdan (sepet 400 TL ve üzeri)"
    if price >= 250:
        return f"Kargo: {format_tl(fee)} (alıcı ile satıcı paylaşıyor)"
    return f"Kargo: {format_tl(fee)} (sepet 250 TL altı, alıcı öder)"


def seller_shipping_text(items: list[Listing], price: float) -> str:
    """Satıcının gözünden kargo (Dolap kuralı): kim öder, satıcıya düşen pay ne kadar."""
    full = package_shipping(items)
    paid_by_buyer = buyer_shipping(items, price)
    if paid_by_buyer == 0:
        return f"Kargoyu sen ödüyorsun: {format_tl(full)} (sepet 400 TL ve üzeri)"
    if price >= 250:
        return f"Kargo paylaşımlı: alıcı {format_tl(paid_by_buyer)} öder, kalanı sende"
    return "Kargoyu alıcı öder (sepet 250 TL altı)"


def bundle_badge(items: list[Listing], whose: str = "favorilerinden") -> str:
    """Paket rozeti: ürün sayısı ve satıcının paketteki pazarlık esnekliği.

    Kademe (2 ürün %5, 3+ ürün %10) satıcının alt sınırındaki esnekliktir; alıcıya doğrudan
    uygulanan bir indirim değildir. Gerçek indirim pazarlıkla belirlenir.
    """
    if len(items) < 2:
        return "Tek ürün"
    return (f"Sepet teklifi: {len(items)} ürün ({whose} +{len(items) - 1}), "
            f"satıcının paket esnekliği %{100 * bundle_discount_rate(len(items)):.0f}")


def status_text(offer: dict) -> str:
    """Bir teklifin onay durumunu Türkçe tek satır olarak verir."""
    if offer["deal"]:
        return "Anlaşma sağlandı"
    if offer["buyer_ok"]:
        return "Alıcı onayladı, satıcı onayı bekleniyor"
    return "Alıcı onayı bekleniyor"


def wish_key(listing: Listing) -> str:
    """Bir ilanı favorilere eklerken kullanılan ifade (ilan başlığı küçük harfle)."""
    return listing.title.lower()


# ---- görünüm parçaları -----------------------------------------------------------

def esc(text: str) -> str:
    """Kullanıcıya ya da LLM'e ait metni HTML'e güvenle koymak için kaçışlar."""
    return html.escape(str(text))


def tag_html(price: float, big: bool = False, old: bool = False) -> str:
    """Fiyat etiketi (sitenin imzası: askı deliği olan sarı etiket)."""
    cls = "tag" + (" big" if big else "") + (" old" if old else "")
    return f'<span class="{cls}">{esc(format_tl(price))}</span>'


def avatar_html(seller_id: str) -> str:
    """Satıcının baş harf yuvarlağı ve kullanıcı adı."""
    return (f'<span class="seller-pill"><span class="avatar">{esc(seller_id[-2:])}</span>'
            f'@{esc(seller_id)}</span>')


def card_html(l: Listing, favored: bool) -> str:
    """Ürün kartı: kategori zemini, durum etiketi, favori kalbi, başlık, beden ve fiyat etiketi."""
    icon, bg = CATEGORY_STYLE.get(l.category, ("🛒", "#E8EAEE"))
    title = l.title.lower()
    icon = next((ic for word, ic in ITEM_ICONS if word in title), icon)
    fg, cbg = CONDITION_STYLE.get(l.condition, ("#4A5161", "#E8EAEE"))
    meta = ", ".join(x for x in [l.size and f"Beden {l.size}", l.category] if x)
    return (
        f'<div class="card"><div class="card-img" style="background:{bg}">'
        f'<span class="chip" style="color:{fg};background:{cbg}">{esc(l.condition)}</span>'
        f'<span class="fav">{"♥" if favored else "♡"}</span>{icon}</div>'
        f'<div class="card-body"><div class="card-title">{esc(l.title)}</div>'
        f'<div class="card-meta">{esc(meta)}</div>'
        f'<div class="card-meta">{avatar_html(l.seller_id)}</div>'
        f'{tag_html(l.list_price)}</div></div>'
    )


def render_grid(listings: list[Listing], key_prefix: str, buyer_actions: bool) -> None:
    """İlanları kart ızgarasında gösterir; alıcı görünümünde favori ve pazarlık düğmeleri ekler."""
    wishlist = st.session_state.wishlist
    for start in range(0, len(listings), GRID_COLUMNS):
        cols = st.columns(GRID_COLUMNS)
        for col, l in zip(cols, listings[start:start + GRID_COLUMNS]):
            favored = wish_key(l) in wishlist
            with col:
                st.markdown(card_html(l, favored), unsafe_allow_html=True)
                if not buyer_actions:
                    continue
                b1, b2 = st.columns([1, 2])
                if b1.button("♥" if favored else "♡", key=f"{key_prefix}-fav-{l.listing_id}",
                             help="Favorilerden çıkar" if favored else "Favorilere ekle",
                             use_container_width=True):
                    if favored:
                        wishlist.remove(wish_key(l))
                    else:
                        wishlist.append(wish_key(l))
                    st.rerun()
                if b2.button("Ajanım pazarlık etsin", key=f"{key_prefix}-deal-{l.listing_id}",
                             use_container_width=True):
                    st.session_state.pending_targets = [l.listing_id]
                    st.session_state.pending_label = l.title
                    st.rerun()


def bubble_html(offer: Offer) -> str:
    """Tek bir pazarlık mesajı: alıcı ajanı sağda (lacivert), satıcı ajanı solda (beyaz)."""
    side = "buyer" if offer.sender == "buyer" else "seller"
    who = "Alıcı ajanı" if side == "buyer" else "Satıcı ajanı"
    label = "kabul etti" if offer.action == "accept" else f"{offer.round}. tur"
    accept = " accept" if offer.action == "accept" else ""
    return (f'<div class="bubble {side}{accept}"><div class="who">{who}, {label}</div>'
            f'{esc(offer.message)}<br><span class="price">{esc(format_tl(offer.price))}</span></div>')


def render_chat(offers: list[Offer], animate: bool = False) -> None:
    """Pazarlık mesajlarını sohbet balonları olarak gösterir; ilk gösterimde mesajlar tek tek gelir."""
    if not animate:
        st.markdown('<div class="chat">' + "".join(bubble_html(o) for o in offers) + "</div>",
                    unsafe_allow_html=True)
        return
    slot = st.empty()
    shown = ""
    for o in offers:
        shown += bubble_html(o)
        slot.markdown(f'<div class="chat">{shown}</div>', unsafe_allow_html=True)
        time.sleep(0.45)


def receipt_html(offer: dict) -> str:
    """Alıcının sipariş özeti: ürünler, indirim, kargo ve ödenecek tutar (alt sınır içermez)."""
    result: NegotiationResult = offer["result"]
    items = offer["items"]
    discount = offer["list_total"] - result.final_price
    rows = "".join(f'<div class="row item"><span class="lbl">{esc(l.title)}</span>'
                   f'<span>{esc(format_tl(l.list_price))}</span></div>' for l in items)
    pct = f"%{100 * discount / offer['list_total']:.1f}".replace(".", ",")
    ship = "Satıcı öder" if offer["shipping"] == 0 else format_tl(offer["shipping"])
    saving_note = ""
    if offer["shipping_saving"] > 0.005:
        saving_note = (f'<div class="row good"><span class="lbl">Tek kargo sayesinde tasarruf</span>'
                       f'<span>{esc(format_tl(offer["shipping_saving"]))}</span></div>')
    return (
        f'<div class="receipt"><h4>Sipariş özeti</h4>{rows}'
        f'<div class="row good"><span class="lbl">Pazarlık indirimi ({pct})</span>'
        f'<span>−{esc(format_tl(discount))}</span></div>'
        f'<div class="row"><span class="lbl">Kargo</span><span>{esc(ship)}</span></div>{saving_note}'
        f'<div class="row total"><span>Ödenecek</span><span>{esc(format_tl(offer["total_to_pay"]))}</span></div>'
        f'<div class="note">{esc(offer["shipping_text"])}</div></div>'
    )


def status_html(offer: dict) -> str:
    """Teklif durum rozeti."""
    cls = "done" if offer["deal"] else "wait"
    return f'<span class="status {cls}">{esc(status_text(offer))}</span>'


def render_offer(key: str, offer: dict, report_fn, listings: list[Listing]) -> None:
    """Alıcı görünümündeki teklif: başlık, sohbet, sipariş özeti ve onay düğmesi."""
    result: NegotiationResult = offer["result"]
    title = " + ".join(l.title for l in offer["items"])
    with st.container(border=True):
        st.markdown(f'<div class="offer-head"><h3>{esc(title)}</h3>{status_html(offer)}</div>'
                    f'{avatar_html(offer["seller_id"])}&nbsp;&nbsp;'
                    f'<span class="card-meta">{esc(bundle_badge(offer["items"]))}</span>',
                    unsafe_allow_html=True)
        left, right = st.columns([3, 2], gap="large")
        with left:
            animate = key in st.session_state.animate
            render_chat(result.offers, animate=animate)
            st.session_state.animate.discard(key)
            with st.expander("Ajan raporu"):
                # Onay öncesinde deal=False olabilir; rapor anlaşılan fiyatı göstersin diye kopyada True yapılır.
                st.text(report_fn(result.model_copy(update={"deal": True}), listings))
        with right:
            st.markdown(f'{tag_html(offer["list_total"], old=True)} {tag_html(result.final_price, big=True)}',
                        unsafe_allow_html=True)
            st.markdown(receipt_html(offer), unsafe_allow_html=True)
            if offer["deal"]:
                st.success("Anlaşma sağlandı. Satıcı ürünleri kargoya hazırlıyor.")
            elif offer["buyer_ok"]:
                st.info("Onayladın. Satıcının onayı bekleniyor; üstten Satıcı görünümüne geçebilirsin.")
            elif st.button("Teklifi onayla", key=f"buyer-ok-{key}", type="primary",
                           use_container_width=True):
                offer["buyer_ok"] = True
                st.rerun()


def run_pending(run_fn, listings: list[Listing]) -> None:
    """Bekleyen bir ajan isteği varsa (ürün kartından ya da aramadan) pazarlığı yürütür."""
    ids = st.session_state.pop("pending_targets", None)
    if not ids:
        return
    label = st.session_state.pop("pending_label", "")
    by_id = {l.listing_id: l for l in listings}
    targets = [by_id[i] for i in ids]
    with st.spinner(f"Ajanın \"{label}\" için {len(targets)} ilanda satıcılarla pazarlık ediyor..."):
        new = run_agent(run_fn, targets, float(st.session_state.budget),
                        st.session_state.wishlist, listings)
    st.session_state.offers = new
    st.session_state.searched = label
    st.session_state.n_scanned = len(targets)
    st.session_state.animate = set(new)


# ---- sayfalar -------------------------------------------------------------------

def buyer_page(run_fn, report_fn, listings: list[Listing]) -> None:
    """Alıcı görünümü: ajan arama kutusu, teklifler, ilanlar ve favoriler."""
    st.markdown('<div class="hero"><h1>Ne arıyorsan yaz, pazarlığı ajanın yapsın.</h1>'
                '<p>Ajanın ürünü satan her satıcıyla senin adına pazarlık eder. Satıcıda favorilerinden '
                'başka ürün de varsa tek kargoda paket ister.</p></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([3, 1.3, 1.2], vertical_alignment="bottom")
    wanted = c1.text_input("Ne almak istiyorsun?", placeholder="örn. deri ceket")
    st.session_state.budget = c2.number_input("Bütçen, kargo dahil (TL)", min_value=100,
                                              value=int(st.session_state.budget), step=100)
    if c3.button("Ajanı gönder", type="primary", use_container_width=True):
        targets = find_targets(wanted.strip(), listings) if wanted.strip() else []
        if not wanted.strip():
            st.warning("Önce almak istediğin ürünü yaz.")
        elif not targets:
            st.warning(f"\"{wanted.strip()}\" ile eşleşen ilan yok. Daha kısa bir kelime dene, örneğin \"ceket\".")
        else:
            st.session_state.pending_targets = [l.listing_id for l in targets]
            st.session_state.pending_label = wanted.strip()

    run_pending(run_fn, listings)

    if "searched" in st.session_state:
        offers = st.session_state.offers
        h1, h2 = st.columns([5, 1], vertical_alignment="center")
        h1.subheader(f"Ajanın getirdiği teklifler: {len(offers)}")
        if h2.button("Temizle", use_container_width=True):
            for k in ("searched", "n_scanned"):
                st.session_state.pop(k, None)
            st.session_state.offers = {}
            st.rerun()
        st.caption(f"\"{st.session_state.searched}\" için {st.session_state.n_scanned} ilan tarandı, "
                   f"{len(offers)} satıcıyla anlaşma noktasına gelindi. En çok kazandıran teklif en üstte.")
        if not offers:
            st.warning("Bütçene uyan bir anlaşma çıkmadı. Bütçeyi artır ya da başka bir ürün dene.")
        ranked = sorted(offers.items(), key=lambda kv: kv[1]["saving"], reverse=True)
        for key, offer in ranked[:MAX_OFFERS]:
            render_offer(key, offer, report_fn, listings)

    tab_browse, tab_wish = st.tabs(["İlanlar", f"Favorilerim ({len(st.session_state.wishlist)})"])

    with tab_browse:
        query = st.text_input("İlanlarda ara", placeholder="örn. çanta", key="browse-q")
        cats = st.pills("Kategori", sorted(CATEGORY_STYLE), selection_mode="multi", key="browse-cat")
        shown = [l for l in listings
                 if (not query.strip() or match_need(query, l)) and (not cats or l.category in cats)]
        st.caption(f"{len(shown)} ilan")
        render_grid(shown, "browse", buyer_actions=True)

    with tab_wish:
        st.write("Ajanın, pazarlık ettiği satıcıda bunlardan birini bulursa paket ister.")
        for i, item in enumerate(st.session_state.wishlist):
            col_text, col_btn = st.columns([6, 1])
            col_text.markdown(f"♥ {esc(item)}")
            if col_btn.button("Çıkar", key=f"wish-del-{i}"):
                st.session_state.wishlist.pop(i)
                st.rerun()
        n1, n2 = st.columns([6, 1], vertical_alignment="bottom")
        new_item = n1.text_input("Favorilere ekle", placeholder="örn. güneş gözlüğü")
        if n2.button("Ekle") and new_item.strip():
            st.session_state.wishlist.append(new_item.strip())
            st.rerun()


def seller_page(seller_id: str, approve_fn, listings: list[Listing]) -> None:
    """Satıcı görünümü: gelen teklifler (onay düğmesiyle) ve satıcının kendi ilanları."""
    mine_listings = [l for l in listings if l.seller_id == seller_id]
    mine = {k: o for k, o in st.session_state.offers.items() if o["seller_id"] == seller_id}
    waiting = sum(1 for o in mine.values() if o["buyer_ok"] and not o["deal"])
    m1, m2, m3 = st.columns(3)
    m1.metric("Yayındaki ilan", len(mine_listings))
    m2.metric("Ajanının teklifleri", len(mine))
    m3.metric("Onayını bekleyen", waiting)

    tab_offers, tab_mine = st.tabs(["Gelen teklifler", "İlanlarım"])
    with tab_offers:
        if not mine:
            st.write("Ajanının yürüttüğü bir pazarlık yok. Alıcı görünümünde bu satıcının bir ürünü için "
                     "ajan gönderildiğinde teklif burada görünür.")
        for key, offer in mine.items():
            result: NegotiationResult = offer["result"]
            title = " + ".join(l.title for l in offer["items"])
            with st.container(border=True):
                st.markdown(f'<div class="offer-head"><h3>{esc(title)}</h3>{status_html(offer)}</div>'
                            f'<span class="card-meta">{esc(bundle_badge(offer["items"], "alıcının favorilerinden"))}</span>',
                            unsafe_allow_html=True)
                left, right = st.columns([3, 2], gap="large")
                with left:
                    render_chat(result.offers)
                with right:
                    # Satıcı kendi alt sınırını bilir; bu bilgi yalnızca satıcının kendi ekranında görünür.
                    floor = bundle_floor(offer["items"])
                    gain = result.final_price - floor
                    st.markdown(tag_html(result.final_price, big=True), unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="receipt"><h4>Senin hesabın</h4>'
                        f'<div class="row"><span class="lbl">Liste toplamı</span>'
                        f'<span>{esc(format_tl(offer["list_total"]))}</span></div>'
                        f'<div class="row"><span class="lbl">Ajanının anlaştığı fiyat</span>'
                        f'<span>{esc(format_tl(result.final_price))}</span></div>'
                        f'<div class="row"><span class="lbl">Senin alt sınırın (paket esnekliği dahil)</span>'
                        f'<span>{esc(format_tl(floor))}</span></div>'
                        f'<div class="row total"><span>Kazancın (alt sınırın üstü)</span>'
                        f'<span>{esc(format_tl(gain))}</span></div>'
                        f'<div class="note">{esc(seller_shipping_text(offer["items"], result.final_price))}. '
                        f'Platform komisyonu hesaba katılmadı.</div></div>',
                        unsafe_allow_html=True)
                    if offer["deal"]:
                        st.success("Anlaşma sağlandı. Ürünleri kargoya hazırla.")
                    elif not offer["buyer_ok"]:
                        st.info("Alıcı henüz onaylamadı.")
                    elif st.button("Satışı onayla", key=f"seller-ok-{key}", type="primary",
                                   use_container_width=True):
                        offer["seller_ok"] = True
                        final = approve_fn(result, offer["buyer_ok"], offer["seller_ok"])
                        offer["result"], offer["deal"] = final, final.deal
                        st.rerun()

    with tab_mine:
        render_grid(mine_listings, "mine", buyer_actions=False)


def main(run_fn, approve_fn, report_fn) -> None:
    """Sayfayı çizer. Pazarlık fonksiyonları parametre olarak gelir (sahte ya da gerçek)."""
    st.set_page_config(page_title="Askı · ikinci el moda", page_icon="🛍️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    listings = load_data()
    sellers = sorted({l.seller_id for l in listings})

    top_left, top_mid, top_right = st.columns([2.2, 1.3, 1.2], vertical_alignment="center")
    top_left.markdown('<div class="brand"><span class="brand-hook"></span><span class="brand-name">askı</span>'
                      '<span class="brand-sub">ikinci el moda, ajanla pazarlık</span></div>',
                      unsafe_allow_html=True)
    view = top_mid.segmented_control("Görünüm", [BUYER_VIEW, SELLER_VIEW], default=BUYER_VIEW,
                                     key="view", label_visibility="collapsed") or BUYER_VIEW
    seller_id = None
    if view == SELLER_VIEW:
        waiting = {o["seller_id"] for o in st.session_state.offers.values()
                   if o["buyer_ok"] and not o["deal"]}
        order = sorted(sellers, key=lambda s: (s not in waiting, s))
        seller_id = top_right.selectbox(
            "Satıcı hesabı", order, label_visibility="collapsed",
            format_func=lambda s: f"@{s}" + ("  (onay bekliyor)" if s in waiting else ""))
    else:
        top_right.markdown(f'<span class="card-meta">♥ {len(st.session_state.wishlist)} favori'
                           f'&nbsp;&nbsp;&nbsp;Bütçe {esc(format_tl(st.session_state.budget))}</span>',
                           unsafe_allow_html=True)

    if view == BUYER_VIEW:
        buyer_page(run_fn, report_fn, listings)
    else:
        seller_page(seller_id, approve_fn, listings)


main(run_negotiation, approve, buyer_report)
