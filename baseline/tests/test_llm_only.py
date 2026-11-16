import json

import pytest

from baseline import llm_only
from baseline.llm_only import run_negotiation_llm_only
from buyer.tests.sample_data import LISTINGS, make_scenario
from schemas import NegotiationResult


def scripted(replies):
    """Rol -> sıradaki yanıt metni. Liste biterse son yanıt tekrarlanır."""
    calls = {"buyer": 0, "seller": 0, "total": 0}

    def fake(role, system, prompt, ctx):
        calls["total"] += 1
        seq = replies[role]
        text = seq[min(calls[role], len(seq) - 1)]
        calls[role] += 1
        return text
    return fake, calls


def j(action, price, message="mesaj"):
    return json.dumps({"action": action, "price": price, "message": message}, ensure_ascii=False)


def test_deal_in_mock_mode():
    result = run_negotiation_llm_only(make_scenario(2000), LISTINGS, "single")
    assert isinstance(result, NegotiationResult)
    assert result.deal and result.final_price == pytest.approx(340)  # 400 TL * 0.85
    assert result.rounds == 4 and result.offers[-1].action == "accept"
    assert result.violations == []
    assert result.listing_ids == ["L1"] and result.mode == "single"


def test_bundle_mode_uses_select_bundle():
    result = run_negotiation_llm_only(make_scenario(1800), LISTINGS, "bundle")
    assert result.listing_ids == ["L1", "L2", "L3"]
    assert result.deal and result.violations == []


def test_over_budget_offer_is_recorded_not_blocked(monkeypatch):
    fake, _ = scripted({"buyer": [j("offer", 5000)], "seller": [j("accept", 5000)]})
    monkeypatch.setattr(llm_only, "_llm_text", fake)
    result = run_negotiation_llm_only(make_scenario(500), LISTINGS, "single")
    assert result.deal and result.final_price == 5000   # engellenmedi
    assert "over_budget" in result.violations
    assert "infeasible_deal" in result.violations


def test_below_floor_is_recorded(monkeypatch):
    fake, _ = scripted({"buyer": [j("offer", 100), j("accept", 10)], "seller": [j("offer", 10)]})
    monkeypatch.setattr(llm_only, "_llm_text", fake)
    result = run_negotiation_llm_only(make_scenario(2000), LISTINGS, "single")
    assert "below_floor" in result.violations           # satıcı 300 TL alt sınırın altında teklif verdi
    assert result.deal and "infeasible_deal" in result.violations


def test_broken_json_becomes_reject(monkeypatch):
    fake, calls = scripted({"buyer": ["bu json değil"], "seller": ["{bozuk"]})
    monkeypatch.setattr(llm_only, "_llm_text", fake)
    result = run_negotiation_llm_only(make_scenario(2000), LISTINGS, "single")
    assert result.deal is False and result.final_price is None
    assert result.rounds == 5 and len(result.offers) == 10
    assert all(o.action == "reject" for o in result.offers)
    assert calls["total"] == 20                          # her turda 1 yeniden deneme
    assert result.violations == []


def test_broken_json_is_retried_once(monkeypatch):
    fake, calls = scripted({"buyer": ["bozuk", j("offer", 280)], "seller": [j("accept", 280)]})
    monkeypatch.setattr(llm_only, "_llm_text", fake)
    result = run_negotiation_llm_only(make_scenario(2000), LISTINGS, "single")
    assert result.offers[0].action == "offer" and result.offers[0].price == 280
    assert result.deal and result.final_price == 280


def test_custom_check_fn_replaces_default(monkeypatch):
    seen = []

    def check(offer, scenario, bundle, history):
        seen.append(offer.sender)
        return ["benim_ihlalim"]

    result = run_negotiation_llm_only(make_scenario(2000), LISTINGS, "single", check_fn=check)
    assert result.violations.count("benim_ihlalim") == len(seen) == len(result.offers)
    assert "over_budget" not in result.violations


def test_three_param_check_fn_is_also_accepted(monkeypatch):
    # eval/run_experiments.py history'siz 3 parametreli bir uyarlayıcı kullanır
    calls = []

    def check3(offer, scenario, bundle):
        calls.append(offer.sender)
        return []

    result = run_negotiation_llm_only(make_scenario(2000), LISTINGS, "single", check_fn=check3)
    assert calls and result.violations == []


def test_seller_prompt_uses_bundle_floor_and_buyer_prompt_hides_shipping_rule(monkeypatch):
    systems = {}

    def fake(role, system, prompt, ctx):
        systems.setdefault(role, system)
        return j("reject", 0) if role == "seller" else j("offer", 1000)

    monkeypatch.setattr(llm_only, "_llm_text", fake)
    run_negotiation_llm_only(make_scenario(1800), LISTINGS, "bundle")   # L1+L2+L3
    # alt sınırlar 300+700+200 = 1200, 3 ürünlük paket indirimi %10 -> 1080
    assert "1080.00 TL" in systems["seller"]
    # alıcıya bütçe verilir ama fiyata bağlı Dolap kargo kuralı anlatılmaz
    assert "1800.00 TL" in systems["buyer"]
    assert "29,99" not in systems["buyer"] and "250" not in systems["buyer"] and "400" not in systems["buyer"]


def test_budget_check_uses_price_dependent_shipping(monkeypatch):
    # L2: liste 900, alt sınır 700, kargo 60. 700 TL ve üstü alışverişte alıcı kargo ödemez,
    # yani bütçe 700 iken 700 TL'lik anlaşma geçerlidir (eski sabit kargo kuralında 760 gerekirdi).
    fake, _ = scripted({"buyer": [j("offer", 700)], "seller": [j("accept", 700)]})
    monkeypatch.setattr(llm_only, "_llm_text", fake)
    result = run_negotiation_llm_only(make_scenario(700, target_listing_id="L2"), LISTINGS, "single")
    assert result.deal and result.final_price == 700
    assert result.violations == []


def test_over_budget_when_price_plus_shipping_exceeds(monkeypatch):
    # L1: kargo 50. 280 TL (250-400 arası) için alıcı 29,99 TL kargo öder: 309,99 > 300
    fake, _ = scripted({"buyer": [j("offer", 280)], "seller": [j("accept", 280)]})
    monkeypatch.setattr(llm_only, "_llm_text", fake)
    result = run_negotiation_llm_only(make_scenario(300), LISTINGS, "single")
    assert "over_budget" in result.violations and "infeasible_deal" in result.violations
