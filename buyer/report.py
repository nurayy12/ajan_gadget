"""Alıcıya gösterilecek kısa Türkçe sonuç özeti."""
from schemas import Listing, NegotiationResult

from ._policy import bundle_discount_rate, buyer_shipping, package_shipping
from .text_utils import format_tl


def _shipping_line(items: list[Listing], price: float) -> tuple[str, float]:
    """Kargoyu kimin ödediği (Dolap eşikleri policy'de; burada karşılaştırarak anlaşılır)."""
    paid = buyer_shipping(items, price)
    full = package_shipping(items)
    if paid <= 0:
        return "Kargo: satıcı öder (alıcıya ücretsiz).", 0.0
    if paid >= full - 1e-9:
        return f"Kargo: alıcı öder ({format_tl(paid)}).", paid
    return (f"Kargo: alıcı {format_tl(paid)} öder, kalanı ({format_tl(full - paid)}) satıcıya aittir.", paid)


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

    if len(items) > 1:
        tier = bundle_discount_rate(len(items)) * 100
        lines.append(f"Paket indirim kademesi: %{tier:g} ({len(items)} ürün)".replace(".", ","))
    shipping_text, shipping = _shipping_line(items, result.final_price)
    lines.append(shipping_text)
    paid_total = result.final_price + shipping
    lines.append(f"Toplam ödeme (kargo dahil): {format_tl(paid_total)}")
    if len(items) > 1:
        # Ayrı ayrı alma: her ürün liste fiyatından, kendi kargosuyla.
        separate = sum(l.list_price + buyer_shipping([l], l.list_price) for l in items)
        lines.append(f"Ürünleri ayrı ayrı alsaydın: {format_tl(separate)} (liste fiyatından, her biri kendi kargosuyla)")
        saving = separate - paid_total
        lines.append(f"Toplam tasarruf: {format_tl(saving)}" if saving > 0.005 else "Toplam tasarruf: yok")
    return "\n".join(lines)
