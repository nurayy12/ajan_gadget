import sys

import pytest

from buyer.tests import fake_policy


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Tüm testler API çağırmadan (USE_MOCK_LLM=1) ve policy taklidiyle çalışır."""
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    monkeypatch.setitem(sys.modules, "policy", fake_policy)
