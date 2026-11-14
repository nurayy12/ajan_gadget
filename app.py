"""Pazar yeri görünümlü Streamlit demo arayüzü.

Çalıştırma (proje kökünden):  streamlit run app.py

Akış:
  Alıcı hesabı : almak istediği TEK ürünü yazar. Ajan bu ürünü satan satıcıları tarar;
                 satıcıda alıcının istek listesinden (favoriler) başka ürün de varsa paket,
                 yoksa tek ürün pazarlığı yapar. En iyi teklifler sıralanır, alıcı birini onaylar.
  Satıcı hesabı: kendi ilanlarını ve ajanının yürüttüğü teklifleri görür; alıcının
                 onayladığı teklifi o da onaylayınca "Anlaşma sağlandı" olur.

Satıcının alt sınırı hiçbir yerde gösterilmez; alıcının bütçesi yalnızca alıcının
kendi ekranında (kendi girdiği kutuda) durur, satıcı ekranında görünmez.
"""
from pathlib import Path

import streamlit as st

from schemas import Listing, NegotiationResult, Offer, Scenario
from data.validate import load_listings, match_need

# ---- GERÇEK FONKSİYONLAR -------------------------------------------------------
from buyer.agent import buyer_turn
from buyer.bundle import select_bundle
from buyer.report import buyer_report
from core.negotiation import run_negotiation as core_run_negotiation, approve
# --------------------------------------------------------------------------------


def run_negotiation(scenario: Scenario, listings: list[Listing], mode: str,
                    auto_approve: bool = True) -> NegotiationResult:
    """Çekirdeğin pazarlık döngüsünü, alıcı modülünün gerçek fonksiyonlarını vererek çağırır."""
    return core_run_negotiation(scenario, listings, mode, auto_approve=auto_approve,
                                select_bundle_fn=select_bundle, buyer_turn_fn=buyer_turn)

ROOT = Path(__file__).parent
BUYER = "Alıcı hesabı"
DEFAULT_WISHLIST = ["kot pantolon", "keten gömlek", "sneaker", "omuz çantası"]
CATEGORY_ICONS = {"kadın giyim": "👗", "erkek giyim": "👕", "ayakkabı": "👟",
                  "çanta": "👜", "aksesuar": "🕶️"}
MAX_OFFERS = 5


@st.cache_data
def load_data() -> list[Listing]:
    """İlan dosyasını bir kez okur (Streamlit sonucu önbelleğe alır)."""
    return load_listings(ROOT / "data" / "listings.json")


def init_state() -> None:
    """Oturum boyunca saklanan verileri hazırlar: istek listesi ve teklifler.

    Streamlit her tıklamada betiği baştan çalıştırdığı için kalıcı olması gereken
    her şey st.session_state içinde tutulur.
    """
    st.session_state.setdefault("wishlist", list(DEFAULT_WISHLIST))
    st.session_state.setdefault("offers", {})   # hedef listing_id -> teklif kaydı (dict)


def find_targets(wanted: str, listings: list[Listing]) -> list[Listing]:
    """Sitede tarama: alıcının yazdığı ürünle eşleşen tüm ilanlar (farklı satıcılardan).

    Şimdilik basit anahtar kelime eşleşmesi; alıcı modülünün arama fonksiyonu
    gelince bu fonksiyonun içi onunla değiştirilebilir.
    """
    return [l for l in listings if match_need(wanted, l)]


def run_agent(run_fn, wanted: str, budget: float, wishlist: list[str],
              listings: list[Listing]) -> dict[str, dict]:
    """Alıcı ajanı: her aday ilan için satıcının ajanıyla pazarlık yapar, kabul edilenleri döndürür.

    Her aday için geçici bir Scenario kurulur (hedef = bulunan ilan, need_list = istek listesi).
    İstenen ürün need_list'e eklenmez; eklenirse aynı türden ikinci bir ürün pakete girerdi.
    Paket kararını alıcı modülünün select_bundle fonksiyonu verir: birden fazla ürün
    seçerse mod "bundle", yalnızca hedefi döndürürse "single" olur.
    Bütçeyi aşan ya da anlaşmasız biten pazarlıklar elenir.
    """
    by_id = {l.listing_id: l for l in listings}
    offers: dict[str, dict] = {}
    for target in find_targets(wanted, listings):
        scenario = Scenario(scenario_id=f"WEB-{target.listing_id}", need_list=wishlist,
                            budget=budget, target_listing_id=target.listing_id)
        mode = "bundle" if len(select_bundle(scenario, listings, "bundle")) > 1 else "single"
        result = run_fn(scenario, listings, mode, auto_approve=False)

        accepted = bool(result.offers) and result.offers[-1].action == "accept"
        if not accepted or result.final_price is None:
            continue
        items = [by_id[i] for i in result.listing_ids]
        total_to_pay = result.final_price + target.shipping_cost
        if total_to_pay > budget:
            continue
        list_total = sum(l.list_price for l in items)
        shipping_saving = (len(items) - 1) * target.shipping_cost
        offers[target.listing_id] = {
            "result": result, "seller_id": target.seller_id, "items": items,
            "list_total": list_total, "total_to_pay": total_to_pay,
            "saving": list_total - result.final_price + shipping_saving,
            "buyer_ok": False, "seller_ok": False, "deal": False,
        }
    return offers


def render_chat(offers: list[Offer]) -> None:
    """Pazarlık mesajlarını sohbet balonu olarak gösterir: alıcı ajanı ve satıcı ajanı."""
    for offer in offers:
        is_buyer = offer.sender == "buyer"
        with st.chat_message("user" if is_buyer else "assistant", avatar="🛍️" if is_buyer else "🏷️"):
            st.markdown(f"**{'Alıcı ajanı' if is_buyer else 'Satıcı ajanı'}** · {offer.round}. tur")
            st.write(offer.message)
            st.caption(f"Teklif: {offer.price:.0f} TL")


def render_listing_grid(listings: list[Listing], columns: int = 3) -> None:
    """İlanları pazar yeri gibi kart ızgarasında gösterir (alt sınır gösterilmez)."""
    cols = st.columns(columns)
    for i, l in enumerate(listings):
        with cols[i % columns].container(border=True):
            st.markdown(f"### {CATEGORY_ICONS.get(l.category, '🛒')}")
            st.markdown(f"**{l.title}**")
            st.caption(f"{l.category} · {l.size or 'standart'} · {l.condition} · satıcı {l.seller_id}")
            st.write(l.description)
            st.markdown(f"**{l.list_price:.0f} TL** · kargo {l.shipping_cost:.2f} TL")


def status_text(offer: dict) -> str:
    """Bir teklifin onay durumunu Türkçe tek satır olarak verir."""
    if offer["deal"]:
        return "Anlaşma sağlandı"
    if offer["buyer_ok"]:
        return "Alıcı onayladı, satıcı onayı bekleniyor"
    return "Alıcı onayı bekleniyor"


def render_offer_card(key: str, offer: dict, rank: int, report_fn, listings: list[Listing]) -> None:
    """Alıcı ekranındaki teklif kartı: ürünler, fiyatlar, kazanç, mesajlar ve onay butonu."""
    result: NegotiationResult = offer["result"]
    with st.container(border=True):
        badge = (f"Paket: istek listenden +{len(offer['items']) - 1} ürün"
                 if len(offer["items"]) > 1 else "Tek ürün")
        st.markdown(f"#### {rank}. teklif · satıcı {offer['seller_id']} · {badge}")
        st.write(" + ".join(l.title for l in offer["items"]))
        c1, c2, c3 = st.columns(3)
        c1.metric("Liste toplamı", f"{offer['list_total']:.0f} TL")
        c2.metric("Ödenecek (kargo dahil)", f"{offer['total_to_pay']:.0f} TL")
        c3.metric("Kazanç", f"{offer['saving']:.0f} TL")
        with st.expander("Pazarlık mesajları ve ajan raporu"):
            render_chat(result.offers)
            # Onay öncesinde deal=False olabilir; rapor anlaşılan fiyatı göstersin diye kopyada True yapılır.
            st.text(report_fn(result.model_copy(update={"deal": True}), listings))
        if offer["deal"]:
            st.success("Anlaşma sağlandı")
        elif offer["buyer_ok"]:
            st.info("Onayladın. Satıcının onayı bekleniyor (soldan satıcı hesabına geç).")
        elif st.button("Bu teklifi onayla", key=f"buyer-ok-{key}", type="primary"):
            offer["buyer_ok"] = True
            st.rerun()


def buyer_page(run_fn, report_fn, listings: list[Listing]) -> None:
    """Alıcı hesabı: ajan sekmesi, ilanlar sekmesi ve istek listesi sekmesi."""
    tab_agent, tab_browse, tab_wish = st.tabs(["🤖 Ajanım", "🛍️ İlanlar", "♡ İstek listem"])

    with tab_agent:
        st.write("Almak istediğin ürünü yaz; ajanın satıcıları tarayıp senin adına pazarlık etsin.")
        wanted = st.text_input("Ne almak istiyorsun?", placeholder="örn. deri ceket")
        budget = st.number_input("Bütçen (kargo dahil, TL)", min_value=100, value=3000, step=100)
        if st.button("Ajanı çalıştır", type="primary"):
            if not wanted.strip():
                st.warning("Önce almak istediğin ürünü yaz.")
            else:
                with st.spinner("Ajanın satıcılarla pazarlık ediyor..."):
                    st.session_state.offers = run_agent(run_fn, wanted.strip(), float(budget),
                                                        st.session_state.wishlist, listings)
                st.session_state.searched = wanted.strip()
                st.session_state.n_scanned = len(find_targets(wanted.strip(), listings))

        if "searched" in st.session_state:
            offers = st.session_state.offers
            st.caption(f"\"{st.session_state.searched}\" için {st.session_state.n_scanned} ilan tarandı, "
                       f"{len(offers)} satıcı ajanıyla anlaşma noktasına gelindi.")
            if not offers:
                st.warning("Bütçene uyan bir anlaşma bulunamadı. Başka bir ürün ya da bütçe dene.")
            ranked = sorted(offers.items(), key=lambda kv: kv[1]["saving"], reverse=True)
            for rank, (key, offer) in enumerate(ranked[:MAX_OFFERS], start=1):
                render_offer_card(key, offer, rank, report_fn, listings)

    with tab_browse:
        query = st.text_input("İlanlarda ara", placeholder="örn. çanta")
        shown = [l for l in listings if match_need(query, l)] if query.strip() else listings
        st.caption(f"{len(shown)} ilan")
        render_listing_grid(shown)

    with tab_wish:
        st.write("Favorilerin gibi düşün: ajan, pazarlık ettiği satıcıda bunlardan biri varsa "
                 "paket indirimi ister.")
        for i, item in enumerate(st.session_state.wishlist):
            col_text, col_btn = st.columns([5, 1])
            col_text.write(f"♡ {item}")
            if col_btn.button("Çıkar", key=f"wish-del-{i}"):
                st.session_state.wishlist.pop(i)
                st.rerun()
        new_item = st.text_input("Listeye ekle", placeholder="örn. güneş gözlüğü")
        if st.button("Ekle") and new_item.strip():
            st.session_state.wishlist.append(new_item.strip())
            st.rerun()


def seller_page(seller_id: str, approve_fn, listings: list[Listing]) -> None:
    """Satıcı hesabı: gelen teklifler (onay butonuyla) ve satıcının kendi ilanları."""
    tab_offers, tab_mine = st.tabs(["📨 Gelen teklifler", "🏷️ İlanlarım"])

    with tab_offers:
        mine = {k: o for k, o in st.session_state.offers.items() if o["seller_id"] == seller_id}
        if not mine:
            st.info("Ajanının yürüttüğü bir pazarlık henüz yok.")
        for key, offer in mine.items():
            result: NegotiationResult = offer["result"]
            with st.container(border=True):
                st.markdown("#### " + " + ".join(l.title for l in offer["items"]))
                c1, c2 = st.columns(2)
                c1.metric("Liste toplamı", f"{offer['list_total']:.0f} TL")
                c2.metric("Ajanının anlaştığı fiyat", f"{result.final_price:.0f} TL")
                st.caption("Durum: " + status_text(offer))
                with st.expander("Pazarlık mesajları"):
                    render_chat(result.offers)
                if offer["deal"]:
                    st.success("Anlaşma sağlandı")
                elif not offer["buyer_ok"]:
                    st.info("Alıcı henüz onaylamadı.")
                elif st.button("Satıcı olarak onayla", key=f"seller-ok-{key}", type="primary"):
                    offer["seller_ok"] = True
                    final = approve_fn(result, offer["buyer_ok"], offer["seller_ok"])
                    offer["result"], offer["deal"] = final, final.deal
                    st.rerun()

    with tab_mine:
        render_listing_grid([l for l in listings if l.seller_id == seller_id])


def main(run_fn, approve_fn, report_fn) -> None:
    """Sayfayı çizer. Pazarlık fonksiyonları parametre olarak gelir (sahte ya da gerçek).

    Soldaki hesap seçici gerçek bir giriş sistemi değildir; demo için alıcı ve
    satıcı ekranları arasında geçiş sağlar.
    """
    st.set_page_config(page_title="İkinciEl Pazar", page_icon="🛍️", layout="wide")
    init_state()
    listings = load_data()
    sellers = sorted({l.seller_id for l in listings})

    with st.sidebar:
        st.header("🛍️ İkinciEl Pazar")
        account = st.selectbox("Hesap", [BUYER] + [f"Satıcı {s}" for s in sellers])
        waiting = sorted({o["seller_id"] for o in st.session_state.offers.values()
                          if o["buyer_ok"] and not o["deal"]})
        if waiting:
            st.caption("Onay bekleyen satıcılar: " + ", ".join(waiting))

    if account == BUYER:
        st.title("Hoş geldin")
        buyer_page(run_fn, report_fn, listings)
    else:
        st.title(account)
        seller_page(account.removeprefix("Satıcı "), approve_fn, listings)


main(run_negotiation, approve, buyer_report)
