import pytest


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Tüm testler API çağırmadan, şablon mesajlarla çalışır."""
    monkeypatch.setenv("USE_MOCK_LLM", "1")
