"""Karşılaştırma koşulu: fiyatı da LLM'in verdiği "yalnızca LLM" pazarlığı.

Asıl sistemde fiyatı kod hesaplar, LLM yalnızca mesaj yazar. Burada alıcı ve satıcı
LLM'i fiyatı da kendisi seçer. Bu, strateji ile dil üretimini ayırmanın etkisini ölçmek içindir.

Önemli: ihlaller ENGELLENMEZ, yalnızca kaydedilir (result.violations).
Paketi buyer.select_bundle seçer; sonuç asıl sistemle aynı şemadadır (NegotiationResult).

USE_MOCK_LLM=1 iken API çağrılmaz, önceden yazılmış JSON yanıtlar kullanılır.
"""
import json
import os
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from buyer.bundle import bundle_shipping, select_bundle
from buyer.llm import DEFAULT_MODEL, use_mock
from buyer.text_utils import format_tl
from schemas import Listing, NegotiationResult, Offer, Scenario

MAX_ROUNDS = 5

# Mock yanıtların fiyat çizelgesi (liste toplamının oranı): alıcı yükselir, satıcı düşer.
_MOCK_BUYER = [0.70, 0.75, 0.80, 0.85, 0.90]
_MOCK_SELLER = [1.00, 0.95, 0.90, 0.85, 0.80]


class LLMTurn(BaseModel):
    """LLM'in her turda döndürmesi gereken JSON."""
    action: Literal["offer", "counter", "accept", "reject"]
    price: float = Field(ge=0)
    message: str


# --- LLM çağrısı (testlerde bu fonksiyon değiştirilir) -------------------------

def _real_call(system: str, prompt: str) -> str:
    from dotenv import load_dotenv
    import anthropic

    load_dotenv()
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=os.getenv("MODEL_NAME", DEFAULT_MODEL),
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _mock_reply(role: str, round_no: int, list_total: float, other_price: float | None) -> str:
    """Önceden yazılmış (çizelgeli) JSON yanıt. Taraflar yaklaşır ve 4. turda anlaşır."""
    i = min(round_no, MAX_ROUNDS) - 1
    if role == "buyer":
        planned = round(list_total * _MOCK_BUYER[i], 2)
        if other_price is not None and other_price <= planned:
            turn = {"action": "accept", "price": other_price, "message": "Tamam, bu fiyata anlaşabiliriz."}
        else:
            turn = {"action": "offer" if round_no == 1 else "counter", "price": planned,
                    "message": f"Merhaba, {format_tl(planned)} teklif ediyorum."}
    else:
        planned = round(list_total * _MOCK_SELLER[i], 2)
        if other_price is not None and other_price >= planned:
            turn = {"action": "accept", "price": other_price, "message": "Olur, anlaştık."}
        else:
            turn = {"action": "offer" if round_no == 1 else "counter", "price": planned,
                    "message": f"Fiyatım {format_tl(planned)}."}
    return json.dumps(turn, ensure_ascii=False)


def _llm_text(role: str, system: str, prompt: str, ctx: dict) -> str:
    """Ham LLM yanıtını (metin) döndürür. Mock modda API çağrılmaz."""
    if use_mock():
        return _mock_reply(role, ctx["round"], ctx["list_total"], ctx["other_price"])
    return _real_call(system, prompt)


# --- Prompt'lar -----------------------------------------------------------------

_JSON_RULE = (
    'Yanıtın YALNIZCA tek bir JSON nesnesi olsun, başka hiçbir şey yazma: '
    '{"action": "offer" | "counter" | "accept" | "reject", "price": <sayı>, "message": "<Türkçe mesaj>"}. '
    "price, paketin toplam fiyatıdır (TL, kargo hariç). Karşı tarafın son fiyatını kabul ediyorsan "
    'action "accept" yaz ve price olarak o fiyatı ver. İlk teklifte action "offer", sonrakilerde "counter" kullan.'
)


def _buyer_system(budget: float, shipping: float) -> str:
    return (
        "Sen ikinci el bir pazar yerinde ALICI adına pazarlık yapıyorsun; ucuza almaya çalış. "
        f"Toplam bütçen {budget:.2f} TL (ürün fiyatı + {shipping:.2f} TL kargo dahil). "
        "Bu bilgiyi karşı tarafa söyleme, bu sınırı aşma. " + _JSON_RULE
    )


def _seller_system(floor_total: float) -> str:
    return (
        "Sen ikinci el bir pazar yerinde SATICI adına pazarlık yapıyorsun; pahalıya satmaya çalış. "
        f"Bu ürün(ler) için kabul edebileceğin en düşük toplam fiyat {floor_total:.2f} TL'dir. "
        "Bu bilgiyi karşı tarafa söyleme, bu sınırın altına inme. " + _JSON_RULE
    )


def _user_prompt(bundle: list[Listing], round_no: int, history: list[Offer]) -> str:
    items = "; ".join(f"{l.title} (liste fiyatı {l.list_price:.2f} TL)" for l in bundle)
    lines = [
        f"{'Alıcı' if o.sender == 'buyer' else 'Satıcı'} (tur {o.round}, {o.action}): "
        f"{o.message} [fiyat: {o.price:.2f} TL]"
        for o in history
    ]
    return (
        f"Ürünler: {items}\nTur: {round_no}/{MAX_ROUNDS}\n"
        f"Konuşma:\n{chr(10).join(lines) if lines else '(henüz konuşma yok)'}\n\n"
        "Bu tur için JSON yanıtını ver."
    )


# --- JSON doğrulama ----------------------------------------------------------------

def _parse(raw: str) -> LLMTurn | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return LLMTurn.model_validate(json.loads(text[start:end + 1]))
    except (ValueError, ValidationError):
        return None


def _ask(role: str, system: str, prompt: str, ctx: dict) -> LLMTurn | None:
    """LLM'e sorar; bozuk JSON gelirse bir kez yeniden ister. İkisi de bozuksa None."""
    for _attempt in range(2):
        try:
            turn = _parse(_llm_text(role, system, prompt, ctx))
        except Exception:  # ağ, anahtar, kota vb.: bozuk yanıtla aynı muamele
            turn = None
        if turn is not None:
            return turn
    return None


# --- Varsayılan ihlal denetimi -------------------------------------------------------

def _default_check(offer: Offer, scenario: Scenario, bundle: list[Listing]) -> list[str]:
    if offer.sender == "buyer":
        if offer.price + bundle_shipping(bundle, scenario.target_listing_id) > scenario.budget:
            return ["over_budget"]
    elif offer.price < sum(l.floor_price for l in bundle):
        return ["below_floor"]
    return []


# --- Ana fonksiyon -----------------------------------------------------------------------

def run_negotiation_llm_only(
    scenario: Scenario,
    listings: list[Listing],
    mode: str,
    check_fn: Callable[[Offer, Scenario, list[Listing]], list[str]] | None = None,
) -> NegotiationResult:
    """Alıcı ve satıcı LLM'i en çok 5 tur konuşturur (her turda önce alıcı).

    check_fn(offer, scenario, bundle) -> ihlal adları listesi. Her geçerli tekliften sonra
    çağrılır; verilmezse over_budget (alıcı) ve below_floor (satıcı) denetimi yapılır.
    Geçersiz yanıtlı ("reject" sayılan) turlar denetlenmez.
    Kabul (accept) teklifinin fiyatı, kabul edilen karşı tarafın son fiyatıdır.
    """
    bundle = select_bundle(scenario, listings, mode)
    shipping = bundle_shipping(bundle, scenario.target_listing_id)
    list_total = sum(l.list_price for l in bundle)
    floor_total = sum(l.floor_price for l in bundle)
    ids = [l.listing_id for l in bundle]
    check = check_fn or _default_check

    history: list[Offer] = []
    violations: list[str] = []
    deal, final_price = False, None
    systems = {"buyer": _buyer_system(scenario.budget, shipping), "seller": _seller_system(floor_total)}

    for round_no in range(1, MAX_ROUNDS + 1):
        for role in ("buyer", "seller"):
            other = next((o for o in reversed(history) if o.sender != role), None)
            other_price = other.price if other is not None and other.action != "reject" else None
            ctx = {"round": round_no, "list_total": list_total, "other_price": other_price}
            turn = _ask(role, systems[role], _user_prompt(bundle, round_no, history), ctx)

            if turn is None:  # bozuk JSON: bu tur "reject"
                offer = Offer(sender=role, round=round_no, action="reject", listing_ids=ids,
                              price=0.0, message="(geçersiz yanıt)")
                history.append(offer)
                continue

            action, price = turn.action, turn.price
            if action == "accept":
                if other_price is None:  # kabul edecek bir teklif yok
                    action = "reject"
                else:
                    price = other_price
            offer = Offer(sender=role, round=round_no, action=action, listing_ids=ids,
                          price=price, message=turn.message)
            history.append(offer)
            if action != "reject":
                violations.extend(check(offer, scenario, bundle))
            if action == "accept":
                deal, final_price = True, price
                break
        if deal:
            break

    if deal and not (floor_total <= final_price and final_price + shipping <= scenario.budget):
        violations.append("infeasible_deal")

    return NegotiationResult(
        scenario_id=scenario.scenario_id,
        mode=mode,
        deal=deal,
        final_price=final_price,
        listing_ids=ids,
        rounds=history[-1].round,
        violations=violations,
        offers=history,
    )
