"""Stark Ekibi: persona kaydi, saglayici yonlendirmesi, TTS dususu ve /ekip yollari."""
import asyncio
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from agents import stark_team
from web.console_server import ConsoleServer


# ------------------------------------------------------------------ kayit
def test_personas_are_unique_and_complete():
    assert len(stark_team.PERSONAS) == 12
    names = [p.name for p in stark_team.PERSONAS.values()]
    assert len(set(names)) == len(names)
    for p in stark_team.PERSONAS.values():
        assert p.provider == "live" or p.provider in stark_team._HANDLERS
        assert p.provider == "live" or p.voice, f"{p.name} sesi yok"
        assert "system_prompt" not in p.public()
    voiced = [(p.voice, p.pitch, p.rate) for p in stark_team.PERSONAS.values() if p.voice]
    assert len(set(voiced)) == len(voiced), "her persona ayirt edilebilir bir sese sahip olmali"


def test_history_is_validated_and_trimmed():
    hist = [{"role": "user", "text": f"m{i}"} for i in range(20)]
    hist += [{"role": "system", "text": "x"}, "bozuk", {"role": "assistant", "text": ""}]
    out = stark_team._clean_history(hist)
    assert len(out) == stark_team.MAX_HISTORY
    assert all(m["role"] in ("user", "assistant") for m in out)


# ------------------------------------------------------------------ yonlendirme
def test_ask_routes_to_provider_handler(monkeypatch):
    seen = {}

    async def fake(p, text, history):
        seen.update(name=p.name, text=text, history=history)
        return {"text": "tamam efendim", "model": p.model}

    monkeypatch.setitem(stark_team._HANDLERS, "openrouter", fake)
    out = asyncio.run(stark_team.ask("pepper", "  selam ", [{"role": "user", "text": "önce"}]))
    assert out == {"text": "tamam efendim", "model": "qwen/qwen3.8-27b:free", "error": None,
                   "consults": []}
    assert seen == {"name": "P.E.P.P.E.R.", "text": "selam",
                    "history": [{"role": "user", "text": "önce"}]}


def test_ask_reports_errors_without_silent_fallback(monkeypatch):
    async def boom(p, text, history):
        raise RuntimeError("429 kota")

    monkeypatch.setitem(stark_team._HANDLERS, "gemini", boom)
    out = asyncio.run(stark_team.ask("friday", "selam"))
    assert out["text"] == "" and "429" in out["error"] and out["model"] == "gemini-flash-lite-latest"


def test_ask_unknown_and_live_personas():
    assert "bilinmeyen" in asyncio.run(stark_team.ask("ultron", "x"))["error"]
    assert asyncio.run(stark_team.ask("jarvis", "x"))["error"]


def test_openrouter_handler_uses_only_persona_model(monkeypatch):
    calls = {}

    class Router:
        available = True

        async def chat(self, messages, model, fallback_models, info, **kw):
            calls.update(model=model, fallbacks=fallback_models, system=messages[0]["content"])
            info["model"] = model
            return SimpleNamespace(content="Merhaba.")

    monkeypatch.setattr(stark_team, "_router", Router())
    out = asyncio.run(stark_team.ask("karen", "nasılsın"))
    assert out["text"] == "Merhaba."
    assert calls["model"] == "nvidia/nemotron-3-super-120b-a12b:free" and calls["fallbacks"] == []
    assert "K.A.R.E.N." in calls["system"]


def test_openrouter_falls_back_to_labeled_gemini(monkeypatch):
    from core.openrouter_client import OpenRouterQuotaError

    class Router:
        available = True

        async def chat(self, *a, **kw):
            raise OpenRouterQuotaError("kota dolu")

    seen = {}

    async def gemini(p, text, history, chain=None):
        seen.update(name=p.name, chain=chain)
        return {"text": "Gemini burada.", "model": "gemini-flash-lite-latest"}

    monkeypatch.setattr(stark_team, "_router", Router())
    monkeypatch.setattr(stark_team, "_ask_gemini", gemini)
    out = asyncio.run(stark_team.ask("homer", "özetle"))
    assert out["text"] == "Gemini burada." and out["error"] is None
    assert out["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free → YEDEK gemini-flash-lite-latest"
    assert seen["name"] == "H.O.M.E.R." and seen["chain"]  # persona kimligi korunur


def test_answer_audio_is_none_when_tts_fails(monkeypatch):
    async def fake(p, text, history):
        return {"text": "ses testi", "model": p.model}

    async def no_audio(*a, **k):
        return None

    async def mp3(*a, **k):
        return b"ID3"

    monkeypatch.setitem(stark_team._HANDLERS, "openrouter", fake)
    monkeypatch.setattr("core.tts.synthesize", no_audio)
    assert asyncio.run(stark_team.answer("homer", "x"))["audio"] is None
    monkeypatch.setattr("core.tts.synthesize", mp3)
    assert asyncio.run(stark_team.answer("homer", "x"))["audio"].startswith("data:audio/mpeg;base64,")
    assert asyncio.run(stark_team.answer("homer", "x", tts=False))["audio"] is None


def test_speakable_strips_markdown_and_links():
    from core.tts import speakable

    assert speakable("**Merhaba** [kaynak](https://x.com/a) # baslik") == "Merhaba kaynak baslik"
    assert "http" not in speakable("bak https://ornek.com/yol burada")
    assert "*" not in speakable("**kalin**")


# ------------------------------------------------------------------ ekip koprusu
def _scripted(monkeypatch, provider, replies, seen):
    """provider icin sirayla verilen yanitlari donduren sahte isleyici."""
    it = iter(replies)

    async def fake(p, text, history):
        seen.append((p.key, text, p.system_prompt))
        return {"text": next(it), "model": p.model}

    monkeypatch.setitem(stark_team._HANDLERS, provider, fake)


def test_resolve_names():
    assert stark_team.resolve("E.D.I.T.H.") == "edith"
    assert stark_team.resolve("iron legion") == "legion"
    assert stark_team.resolve("DUM-E") == "dume"
    assert stark_team.resolve("ultron") is None


def test_consult_asks_teammate_then_answers(monkeypatch):
    seen = []
    _scripted(monkeypatch, "openrouter", ["[DANIŞ: E.D.I.T.H.] İzmir hava durumu?",
                                          "Hava güneşli efendim, Kordon'a çıkın."], seen)
    _scripted(monkeypatch, "search", ["İzmir 24 derece ve güneşli."], seen)
    out = asyncio.run(stark_team.ask("pepper", "Bugün ne yapsam?", consult=True))
    assert out["text"] == "Hava güneşli efendim, Kordon'a çıkın."
    assert [(c["from"], c["to"], c["question"], c["text"]) for c in out["consults"]] == [
        ("pepper", "edith", "İzmir hava durumu?", "İzmir 24 derece ve güneşli.")]
    assert "EKİP KÖPRÜSÜ" in seen[0][2] and "veronica" not in seen[0][2]
    assert "İzmir 24 derece" in seen[2][1]  # pepper'in ikinci cagrisi edith'in yanitini gorur


def test_consult_off_and_paid_member_blocked(monkeypatch):
    seen = []
    _scripted(monkeypatch, "openrouter", ["[DANIŞ: veronica] kod yaz", "Kendim yanıtlıyorum."], seen)
    out = asyncio.run(stark_team.ask("karen", "plan yap", consult=True, allow_paid=False))
    assert out["text"] == "Kendim yanıtlıyorum."
    assert out["consults"][0]["error"] == "danisilamaz"
    assert "ücretli" in seen[1][1]

    seen.clear()
    _scripted(monkeypatch, "openrouter", ["düz yanıt"], seen)
    out = asyncio.run(stark_team.ask("karen", "x", consult=False))
    assert out["consults"] == [] and "EKİP KÖPRÜSÜ" not in seen[0][2]


def test_consult_limit_and_no_recursion(monkeypatch):
    seen = []
    _scripted(monkeypatch, "openrouter", ["[DANIŞ: homer] a", "[DANIŞ: homer] b",
                                          "[DANIŞ: homer] c Yine de cevabım bu."], seen)
    homer_calls = []

    async def homer(p, text, history):
        homer_calls.append(p.system_prompt)
        return {"text": "[DANIŞ: pepper] geri sor", "model": p.model}

    orig = stark_team._HANDLERS["openrouter"]

    async def route(p, text, history):
        return await (homer(p, text, history) if p.key == "homer" else orig(p, text, history))

    monkeypatch.setitem(stark_team._HANDLERS, "openrouter", route)
    out = asyncio.run(stark_team.ask("pepper", "soru", consult=True))
    assert len(out["consults"]) == stark_team.MAX_CONSULTS
    assert out["text"] == "" and "siniri" in out["error"]  # etiket sesli okunmaz
    assert all("EKİP KÖPRÜSÜ" not in sp for sp in homer_calls)  # danisilan uye danisamaz


def test_council_turn_sees_previous_speakers(monkeypatch):
    seen = []
    _scripted(monkeypatch, "openrouter", ["Pepper'a katılıyorum."], seen)
    out = asyncio.run(stark_team.council_turn(
        "homer", "Yazılım mı tasarım mı?",
        [{"persona": "pepper", "text": "Yazılım öğren."}, {"persona": "ultron", "text": "yok say"}],
        tts=False))
    assert out["text"] == "Pepper'a katılıyorum." and out["audio"] is None
    assert "P.E.P.P.E.R.: Yazılım öğren." in seen[0][1] and "yok say" not in seen[0][1]
    assert "Sıra sende" in seen[0][1]

    seen.clear()
    _scripted(monkeypatch, "gemini", ["Özet."], seen)
    asyncio.run(stark_team.council_turn("friday", "konu", [], final=True, tts=False))
    assert "KAPANIŞ" in seen[0][1]
    assert asyncio.run(stark_team.council_turn("jarvis", "konu", []))["error"]


# ------------------------------------------------------------------ HTTP
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path):
    port = _free_port()
    srv = ConsoleServer(outbox_path=tmp_path / "outbox.txt", inbox_path=tmp_path / "inbox.txt",
                        port=port, bind="127.0.0.1", token="tok", team_tts=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield srv, port, tmp_path
    srv.stop()


def _req(port, path, body=None, key="tok"):
    url = f"http://127.0.0.1:{port}{path}" + (f"?key={key}" if key else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_team_routes_require_key(server):
    _, port, _ = server
    assert _req(port, "/ekip", key="")[0] == 401
    assert _req(port, "/api/team", key="")[0] == 401
    assert _req(port, "/api/team/ask", {"persona": "pepper", "text": "x"}, key="")[0] == 401


def test_team_page_and_list(server):
    _, port, _ = server
    code, html = _req(port, "/ekip")
    assert code == 200 and "STARK" in html
    code, body = _req(port, "/api/team")
    data = json.loads(body)
    assert code == 200 and data["tts"] is False and len(data["personas"]) == 12
    assert all("system_prompt" not in p for p in data["personas"])


def test_team_ask_validation_and_answer(server, monkeypatch):
    _, port, _ = server
    assert _req(port, "/api/team/ask", {"persona": "ultron", "text": "x"})[0] == 400
    assert _req(port, "/api/team/ask", {"persona": "pepper", "text": "  "})[0] == 400

    async def fake_answer(key, text, history, *, tts, consult, allow_paid):
        return {"text": f"{key}:{text}", "model": "m", "error": None, "audio": None, "tts": tts,
                "consults": [], "flags": [consult, allow_paid]}

    monkeypatch.setattr(stark_team, "answer", fake_answer)
    code, body = _req(port, "/api/team/ask", {"persona": "pepper", "text": "selam"})
    data = json.loads(body)
    assert code == 200 and data["text"] == "pepper:selam" and data["tts"] is False
    assert data["flags"] == [True, False]  # kopru varsayilan acik, ucretli uye kapali


def test_council_turn_endpoint(server, monkeypatch):
    _, port, _ = server
    assert _req(port, "/api/team/council/turn", {"persona": "jarvis", "topic": "x"})[0] == 400
    assert _req(port, "/api/team/council/turn", {"persona": "homer", "topic": ""})[0] == 400

    async def fake_turn(key, topic, transcript, *, final, tts):
        return {"text": f"{key}:{len(transcript)}:{final}", "model": "m", "error": None, "audio": None}

    monkeypatch.setattr(stark_team, "council_turn", fake_turn)
    code, body = _req(port, "/api/team/council/turn",
                      {"persona": "homer", "topic": "t", "transcript": [{"persona": "pepper", "text": "a"}],
                       "final": True})
    assert code == 200 and json.loads(body)["text"] == "homer:1:True"


def test_jarvis_question_goes_to_live_brain(server):
    _, port, tmp = server
    code, body = _req(port, "/api/team/ask", {"persona": "jarvis", "text": "saat kaç"})
    assert code == 200 and json.loads(body)["via"] == "live"
    assert (tmp / "outbox.txt").read_text(encoding="utf-8").strip() == "[TELEFON] saat kaç"
