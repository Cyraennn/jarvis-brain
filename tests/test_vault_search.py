"""Kisisel hafiza aramasi (tools/vault_search) + GBrain yeniden gomme testleri.

Gercek e5 modeli yuklenmez: sahte bir `search.py` (ayni arayuz) gecici klasore yazilir.
"""

from __future__ import annotations

import asyncio
import json
import textwrap

import pytest

FAKE_SEARCH = textwrap.dedent('''
    import json
    from pathlib import Path
    import numpy as np

    INDEX_DIR = Path(__file__).parent / "index"
    CALLS = {"update": 0}
    WORDS = ["okul", "whatsapp", "disk", "jarvis"]

    def _vec(text):
        v = np.array([text.lower().count(w) for w in WORDS], dtype=np.float32) + 0.01
        return v / np.linalg.norm(v)

    class Embedder:
        def embed(self, texts):
            return np.vstack([_vec(t) for t in texts])

    CHUNKS = [
        {"key": "A::okul.md", "vault": "Notlarim", "path": "C:/v/okul.md", "rel": "okul.md",
         "heading": "Sinavlar", "text": "okul okul sinav takvimi"},
        {"key": "B::wa.md", "vault": "JARVIS Hafiza", "path": "C:/v/wa.md", "rel": "wa.md",
         "heading": "WhatsApp", "text": "whatsapp kolu kurallari"},
        {"key": "B::wa.md", "vault": "JARVIS Hafiza", "path": "C:/v/wa.md", "rel": "wa.md",
         "heading": "WhatsApp", "text": "whatsapp ikinci parca"},
    ]

    def update_index(box, full=False):
        CALLS["update"] += 1
        return None, None, 0

    def load_index():
        return {"files": {}, "chunks": CHUNKS}, Embedder().embed([c["text"] for c in CHUNKS])
''')


@pytest.fixture()
def vs(tmp_path, monkeypatch):
    (tmp_path / "search.py").write_text(FAKE_SEARCH, encoding="utf-8")
    monkeypatch.setenv("JARVIS_VAULT_SEARCH_DIR", str(tmp_path))
    import tools.vault_search as mod

    monkeypatch.setattr(mod, "_module", None)
    monkeypatch.setattr(mod, "_embedder_box", [None])
    monkeypatch.setattr(mod, "_last_update", 0.0)
    return mod


def test_memory_search_ranks_and_dedupes(vs):
    r = vs.memory_search("whatsapp kurallari", k=5)
    assert r["count"] == 2  # ayni not+baslik iki parca -> tek sonuc
    assert r["results"][0]["note"] == "wa.md"
    assert r["results"][0]["vault"] == "JARVIS Hafiza"
    assert {"Notlarim", "JARVIS Hafiza"} == set(r["vaults"])


def test_memory_search_vault_filter(vs):
    r = vs.memory_search("whatsapp", vault="notlarim")
    assert [x["note"] for x in r["results"]] == ["okul.md"]


def test_index_update_is_throttled(vs):
    vs.memory_search("okul")
    vs.memory_search("okul")
    assert vs._module.CALLS["update"] == 1


def test_update_skipped_when_locked(vs):
    mod = vs._load_module()
    with vs._index_lock(mod.INDEX_DIR) as first:
        assert first
        r = vs.memory_search("okul")  # ayni surecte ikinci kilit -> alinamaz
    assert r["count"] >= 1
    assert mod.CALLS["update"] == 0


def test_missing_tool_returns_error(tmp_path, monkeypatch):
    import tools.vault_search as mod

    monkeypatch.setenv("JARVIS_VAULT_SEARCH_DIR", str(tmp_path / "yok"))
    monkeypatch.setattr(mod, "_module", None)
    assert "error" in mod.memory_search("x")
    assert "error" in mod.memory_search("  ")


def test_registered_for_brain_and_agents():
    from agents.agent_tools import CAPABILITIES
    from remote.protocol import CLIENT_FUNCTIONS
    from tools.tool_runner import ToolRunner

    assert "memory_search" in ToolRunner().tool_names
    assert CAPABILITIES["vault"][0].__name__ == "memory_search"
    assert "tools.vault_search.memory_search" in CLIENT_FUNCTIONS


# ------------------------------------------------------------------ GBrain

def test_gbrain_reembeds_stale_records(tmp_path, monkeypatch):
    import agents.gbrain.store as store

    notes = tmp_path / "notes.jsonl"
    notes.write_text(
        json.dumps({"id": "a", "title": "eski", "content": "bos gomme", "embedding": []}) + "\n"
        + json.dumps({"id": "b", "title": "yeni", "content": "tamam", "embedding": [1.0, 0.0, 0.0]}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "_DIR", tmp_path)
    monkeypatch.setattr(store, "_NOTES", notes)
    g = store.GBrain()

    async def fake_embed(text):
        return [0.0, 1.0, 0.0] if "bos" in text or "eski" in text else [1.0, 0.0, 0.0]

    monkeypatch.setattr(g, "_embed", fake_embed)
    hits = asyncio.run(g.search("eski bos", k=2))
    assert hits[0]["id"] == "a" and hits[0]["score"] > 0.9
    saved = [json.loads(line) for line in notes.read_text(encoding="utf-8").splitlines()]
    assert all(len(n["embedding"]) == 3 for n in saved)


def test_gbrain_embed_failure_keeps_keyword_fallback(tmp_path, monkeypatch):
    import agents.gbrain.store as store

    notes = tmp_path / "notes.jsonl"
    notes.write_text(json.dumps({"id": "a", "title": "kedi", "content": "kedi mama",
                                 "embedding": []}) + "\n", encoding="utf-8")
    monkeypatch.setattr(store, "_DIR", tmp_path)
    monkeypatch.setattr(store, "_NOTES", notes)
    g = store.GBrain()

    async def no_embed(text):
        return []

    monkeypatch.setattr(g, "_embed", no_embed)
    assert asyncio.run(g.search("kedi"))[0]["id"] == "a"
