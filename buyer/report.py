"""Alıcıya gösterilecek kısa Türkçe sonuç özeti."""
from schemas import Listing, NegotiationResult

from .text_utils import format_tl


def buyer_report(result: NegotiationResult, listings: list[Listing]) -> str:
    by_id = {l.listing_id: l for l in listings}
    items = [by_id[i] for i in result.listing_ids if i in by_id]
    kind = "Paket pazarlığı" if result.mode == "bundle" else "Tek ürün pazarlığı"

    if not result.deal or result.final_price is None:
        names = ", ".join(l.title for l in items) or "-"
        return f"{kind}: {result.rounds} turda anlaşma sağlanamadı.\nİstenen ürünler: {names}"

    list_total = sum(l.list_price for l in items)
    lines = [f"{kind}: {result.rounds} turda anlaşıldı.", "Ürünler:"]
    lines += [f"- {l.title} (liste fiyatı {format_tl(l.list_price)})" for l in items]
    lines.append(f"Liste fiyatı toplamı: {format_tl(list_total)}")
    lines.append(f"Anlaşılan fiyat: {format_tl(result.final_price)} (kargo hariç)")
    if list_total > 0:
        discount = (list_total - result.final_price) / list_total * 100
        lines.append(f"İndirim: %{discount:.1f}".replace(".", ","))
    return "\n".join(lines)
