"""Alıcı mesajlarını yazan LLM katmanı.

LLM yalnızca Türkçe mesaj yazar; fiyatı kod hesaplar. LLM fiyatın yerine {FIYAT}
yer tutucusunu yazar, gerçek fiyatı agent.py koyar. Bütçe LLM'e hiç verilmez.

USE_MOCK_LLM=1 ise API çağrılmaz, şablon mesaj döner.
Model adı MODEL_NAME ortam değişkeninden okunur (varsayılan claude-haiku-5-5);
API anahtarı .env dosyasındaki ANTHROPIC_API_KEY'den gelir.
"""
import os
import warnings

from schemas import Offer

from .text_utils import format_tl

PLACEHOLDER = "{FIYAT}"
DEFAULT_MODEL = "claude-haiku-5-5"

_SYSTEM = (
    "Sen ikinci el bir pazar yerinde alıcı adına pazarlık yapan bir asistansın. "
    "Satıcıya kısa (en çok 3 cümle), kibar ve doğal bir Türkçe mesaj yaz. "
    "Fiyatı mesajda tam olarak {FIYAT} şeklinde yaz; başka hiçbir fiyat ya da büyük sayı yazma. "
    "Ne kadar ödemeye hazır olduğun ya da bütçen hakkında hiçbir şey söyleme. "
    "Yalnızca mesajın kendisini yaz."
)


def use_mock() -> bool:
    return os.getenv("USE_MOCK_LLM") == "1"


def template_message(is_bundle: bool, round_no: int) -> str:
    """Şablon mesaj (mock modu ve LLM hatasında yedek). Fiyat yerine {FIYAT} içerir."""
    if round_no == 1:
        if is_bundle:
            return ("Merhaba, ilanlarınızdaki ürünleri birlikte almak istiyorum. "
                    "Toplu alım yaptığım için paket fiyatı olarak {FIYAT} teklif ediyorum. Uygun olur mu?")
        return "Merhaba, ilanınızdaki ürün için {FIYAT} teklif ediyorum. Uygun olur mu?"
    if is_bundle:
        return ("Teşekkürler. Ürünleri paket olarak aldığım için {FIYAT} fiyatına "
                "yaklaşabilirsek hemen anlaşabiliriz.")
    return "Teşekkürler. {FIYAT} fiyatına yaklaşabilirsek hemen anlaşabiliriz."


def _real_message(titles: list[str], is_bundle: bool, round_no: int, history: list[Offer]) -> str:
    from dotenv import load_dotenv
    import anthropic

    load_dotenv()
    client = anthropic.Anthropic()
    model = os.getenv("MODEL_NAME", DEFAULT_MODEL)

    lines = [
        f"{'Alıcı' if o.sender == 'buyer' else 'Satıcı'} (tur {o.round}): "
        f"{o.message} [fiyat: {format_tl(o.price)}]"
        for o in history
    ]
    prompt = (
        f"Ürünler: {', '.join(titles)}\n"
        f"Toplu alım mı: {'evet, birden çok ürün birlikte alınıyor; toplu alım gerekçesini belirt' if is_bundle else 'hayır, tek ürün'}\n"
        f"Tur: {round_no}\n"
        f"Şimdiye kadarki konuşma:\n{chr(10).join(lines) if lines else '(henüz konuşma yok)'}\n\n"
        "Bu tur için satıcıya yazacağın mesajı yaz."
    )
    response = client.messages.create(
        model=model,
        max_tokens=250,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def write_message(titles: list[str], is_bundle: bool, round_no: int, history: list[Offer]) -> str:
    """Fiyat yerine {FIYAT} içeren Türkçe mesaj döndürür."""
    if use_mock():
        return template_message(is_bundle, round_no)
    try:
        return _real_message(titles, is_bundle, round_no, history)
    except Exception as exc:  # ağ, anahtar, kota vb.: pazarlık durmasın
        warnings.warn(f"LLM çağrısı başarısız, şablon mesaj kullanıldı: {exc}")
        return template_message(is_bundle, round_no)
