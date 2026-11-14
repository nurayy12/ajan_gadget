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

    def check(offer, scenario, bundle):
        seen.append(offer.sender)
        return ["benim_ihlalim"]

    result = run_negotiation_llm_only(make_scenario(2000), LISTINGS, "single", check_fn=check)
    assert result.violations.count("benim_ihlalim") == len(seen) == len(result.offers)
    assert "over_budget" not in result.violations
