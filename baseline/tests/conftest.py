import pytest


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Tüm testler API çağırmadan çalışır (USE_MOCK_LLM=1)."""
    monkeypatch.setenv("USE_MOCK_LLM", "1")
