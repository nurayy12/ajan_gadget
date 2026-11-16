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


@pytest.fixture
def no_buffer(monkeypatch):
    """Sızıntı payını (u) sıfırlar; tam sayı bekleyen testler için."""
    from buyer import config
    monkeypatch.setattr(config, "PRIVACY_BUFFER_MIN", 0.0)
    monkeypatch.setattr(config, "PRIVACY_BUFFER_MAX", 0.0)
