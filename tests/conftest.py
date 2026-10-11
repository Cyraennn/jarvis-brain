"""Tum testler icin ortak ayarlar."""
import pytest


@pytest.fixture(autouse=True)
def _no_local_llm(monkeypatch):
    """Testler makinedeki gercek Ollama'ya dusmesin; yerel yedegi isteyen test kendisi verir."""
    monkeypatch.setattr("agents.genai_util._get_local", lambda: None)

    async def _online() -> bool:
        return True

    monkeypatch.setattr("agents.genai_util._is_online", _online)


@pytest.fixture(autouse=True)
def _no_real_task_log(monkeypatch, tmp_path):
    """Sahte ajan gorevleri gercek data/task_logs.jsonl'e yazilmasin (gun sonu ozeti onu okur)."""
    monkeypatch.setattr("agents.integrations.supabase_sync.APP_DIR", tmp_path)
