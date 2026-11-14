"""Tek sayfalık Streamlit demo arayüzü.

Çalıştırma (proje kökünden):  streamlit run app.py
Satıcının alt sınırı ve alıcının bütçesi ekranda hiçbir yerde gösterilmez.
"""
from pathlib import Path

import streamlit as st

from schemas import Listing, Offer, Scenario
from data.validate import load_listings, load_scenarios

# GERÇEK FONKSİYONLARA GEÇİŞ: yalnızca aşağıdaki import'u değiştir, örn.
#   from core.negotiation import run_negotiation, approve, buyer_report
from eval.fake import (fake_run_negotiation as run_negotiation,
                       fake_approve as approve,
                       fake_buyer_report as buyer_report)

ROOT = Path(__file__).parent
MODE_OPTIONS = {"Tek ürün": "single", "Paket": "bundle"}


@st.cache_data
def load_data() -> tuple[list[Listing], list[Scenario]]:
    """İlan ve senaryo dosyalarını bir kez okur (Streamlit sonucu önbelleğe alır)."""
    return (load_listings(ROOT / "data" / "listings.json"),
            load_scenarios(ROOT / "data" / "scenarios.json"))


def render_chat(offers: list[Offer]) -> None:
    """Teklifleri sohbet balonu olarak gösterir: alıcı ve satıcı ayrı avatarla."""
    for offer in offers:
        is_buyer = offer.sender == "buyer"
        with st.chat_message("user" if is_buyer else "assistant", avatar="🛍️" if is_buyer else "🏷️"):
            st.markdown(f"**{'Alıcı' if is_buyer else 'Satıcı'}** · {offer.round}. tur")
            st.write(offer.message)
            st.caption(f"Teklif: {offer.price:.0f} TL")


def main(run_fn, approve_fn, report_fn) -> None:
    """Sayfayı çizer. Pazarlık fonksiyonları parametre olarak gelir (sahte ya da gerçek).

    Streamlit her tıklamada betiği baştan çalıştırdığı için pazarlık sonucu ve
    onay durumları st.session_state içinde saklanır.
    """
    st.set_page_config(page_title="Pazarlık Ajanları", page_icon="🤝")
    st.title("İkinci el pazarlık ajanları")
    listings, scenarios = load_data()
    by_id = {l.listing_id: l for l in listings}

    def label(s: Scenario) -> str:
        return f"{s.scenario_id} · {by_id[s.target_listing_id].title}"

    scenario = st.selectbox("Senaryo", scenarios, format_func=label)
    mode_label = st.radio("Pazarlık türü", list(MODE_OPTIONS), horizontal=True)

    target = by_id[scenario.target_listing_id]
    st.markdown(f"**Hedef ilan:** {target.title} · liste fiyatı {target.list_price:.0f} TL "
                f"· kargo {target.shipping_cost:.2f} TL")
    st.markdown("**İhtiyaç listesi:** " + ", ".join(scenario.need_list))

    if st.button("Pazarlığı başlat", type="primary"):
        st.session_state.result = run_fn(scenario, listings, MODE_OPTIONS[mode_label],
                                         auto_approve=False)
        st.session_state.buyer_ok = False
        st.session_state.seller_ok = False

    result = st.session_state.get("result")
    if result is None:
        return

    st.divider()
    render_chat(result.offers)
    st.subheader("Alıcı raporu")
    st.text(report_fn(result, listings))

    # Onay butonları yalnızca pazarlık kabulle bittiyse gösterilir.
    if not result.offers or result.offers[-1].action != "accept":
        st.warning("Pazarlık anlaşmasız sonuçlandı.")
        return

    col_buyer, col_seller = st.columns(2)
    if col_buyer.button("Alıcı onaylıyor", disabled=st.session_state.buyer_ok):
        st.session_state.buyer_ok = True
        st.rerun()
    if col_seller.button("Satıcı onaylıyor", disabled=st.session_state.seller_ok):
        st.session_state.seller_ok = True
        st.rerun()

    if st.session_state.buyer_ok and st.session_state.seller_ok:
        final = approve_fn(result, True, True)
        if final.deal:
            st.success("Anlaşma sağlandı")
        else:
            st.error("Onay verildi ama anlaşma kesinleşmedi.")
    else:
        waiting = [name for name, ok in (("alıcı", st.session_state.buyer_ok),
                                         ("satıcı", st.session_state.seller_ok)) if not ok]
        st.info("Onay bekleniyor: " + ", ".join(waiting))


main(run_negotiation, approve, buyer_report)
