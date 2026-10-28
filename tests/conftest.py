"""Tum testler icin ortak ayarlar."""
import os
import sys

import pytest

# Mevcut testler eski yolu (Conductor LLM) dener; router gercek LLM'e ya da gercek
# data/logs/routing.jsonl'e dokunmasin. Ayarlar onbelleklenmeden ONCE kapatilir; router
# testleri kendi router'ini (sahte gomme + gecici log) acikca kurar.
os.environ["JARVIS_ROUTER_ENABLED"] = "false"


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



@pytest.fixture(autouse=True)
def _reset_active_router():
    """Bir testin etkin router'i digerine (orn. Stark ekibi testleri) sizmasin."""
    yield
    mod = sys.modules.get("router")
    if mod is not None:
        mod.set_active(None)
