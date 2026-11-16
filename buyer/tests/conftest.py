import sys

import pytest

from buyer.tests import fake_policy


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Tüm testler API çağırmadan, şablon mesajlarla ve policy taklidiyle çalışır.

    Gerçek policy.py ile uyum test_policy_contract.py'de ayrıca kontrol edilir.
    """
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    monkeypatch.setitem(sys.modules, "policy", fake_policy)
