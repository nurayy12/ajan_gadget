"""Türkçe metin yardımcıları: küçük harf, tokenizasyon, TL biçimlendirme."""
import re

from . import config

_TOKEN_RE = re.compile(r"[0-9a-zçğıöşü]+")


def tr_lower(text: str) -> str:
    """Türkçe küçük harf: İ -> i, I -> ı (Python'un varsayılanı bunu yanlış yapar)."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def tokenize(text: str) -> list[str]:
    """Küçük harfe çevirir, harf/rakam öbeklerine böler, istenirse kelime başını alır."""
    tokens = _TOKEN_RE.findall(tr_lower(text))
    if config.STEM_PREFIX > 0:
        tokens = [t[: config.STEM_PREFIX] for t in tokens]
    return tokens


def format_tl(amount: float) -> str:
    """1250.5 -> '1.250,50 TL', 900.0 -> '900 TL'."""
    if abs(amount - round(amount)) < 0.005:
        s = f"{round(amount):,}"
    else:
        s = f"{amount:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " TL"
