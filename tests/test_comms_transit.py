"""Haberlesme (Gmail/Telegram) + ulasim araclari + OpenRouter arac dongusu - agsiz testler."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agents.agent_tools import build_callables, known_capabilities
from tools.tool_declarations import build_declarations
from tools.tool_runner import ToolRunner

NEW_TOOLS = {
    "get_unread_emails", "create_email_draft", "generate_auto_reply_draft",
    "send_telegram_message", "get_latest_telegram_updates", "reply_to_telegram_message",
    "eshot_find_stop", "eshot_nearby_stops", "eshot_line_info", "eshot_approaching_buses",
    "plan_route", "izmirim_kart_balance",
}


# ------------------------------------------------------------------ kayit tutarliligi
def test_declarations_and_registry_match():
    declared = {d.name for d in build_declarations()}
    registered = set(ToolRunner().tool_names)
    assert NEW_TOOLS <= declared
    assert declared == registered


def test_new_capabilities_exist_and_agents_cannot_send_email():
    assert {"gmail", "telegram", "transit"} <= set(known_capabilities())
    names = {f.__name__ for f in build_callables(["gmail", "telegram", "transit"])}
    assert "send_email" not in names and "reply_to_telegram_message" not in names
    assert {"generate_auto_reply_draft", "notify_owner_telegram", "transit_route"} <= names


def test_agents_json_new_agents_load():
    from pathlib import Path

    from agents.registry import load_agents

    agents = load_agents(Path("agents/agents.json"))
    assert agents["ulasim"].capabilities == ["transit"]
    assert "gmail" in agents["sekreter"].capabilities


# ------------------------------------------------------------------ e-posta arka ucu
def test_email_tools_prefers_gmail_then_imap(monkeypatch):
    from tools import email_tools, gmail_tool

    monkeypatch.setattr(gmail_tool, "gmail_enabled", lambda: True)
    monkeypatch.setattr(gmail_tool, "list_emails", lambda **kw: {"backend": "gmail_api", **kw})
    assert email_tools.check_email(limit=3)["backend"] == "gmail_api"

    imap = SimpleNamespace(list_recent=lambda **kw: {"backend": "imap"}, enabled=True)
    monkeypatch.setattr(gmail_tool, "gmail_enabled", lambda: False)
    monkeypatch.setattr(email_tools, "_client", lambda: imap)
    assert email_tools.check_email()["backend"] == "imap"


def test_gmail_tools_report_unconfigured(monkeypatch):
    from tools import gmail_tool

    monkeypatch.setattr(gmail_tool, "gmail_enabled", lambda: False)
    for result in (gmail_tool.get_unread_emails(), gmail_tool.generate_auto_reply_draft("x"),
                   gmail_tool.create_email_draft("a@b.c", "s", "b")):
        assert "error" in result


def test_gmail_body_prefers_plain_text():
    import base64

    from tools.gmail_tool import _body_text

    enc = lambda t: base64.urlsafe_b64encode(t.encode()).decode()  # noqa: E731
    payload = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/html", "body": {"data": enc("<p>html</p>")}},
        {"mimeType": "text/plain", "body": {"data": enc("Merhaba Sezai")}},
    ]}
    assert _body_text(payload) == "Merhaba Sezai"


# ------------------------------------------------------------------ telegram
@pytest.fixture
def tg_settings(monkeypatch, tmp_path):
    from config import settings as settings_mod

    base = settings_mod.get_settings()
    fake = base.model_copy(update={
        "telegram_bot_token": "123:abc", "telegram_default_chat_id": "42",
        "telegram_allowed_chat_ids": [], "telegram_auto_reply": True,
        "data_dir": tmp_path, "bridge_outbox_path": tmp_path / "outbox.txt",
    })
    monkeypatch.setattr("tools.telegram_tool.get_settings", lambda: fake)
    monkeypatch.setattr("config.settings.get_settings", lambda: fake)
    return fake


def _update(uid: int, chat: int, text: str) -> dict:
    return {"update_id": uid, "message": {"message_id": uid * 10, "text": text, "date": 0,
                                         "chat": {"id": chat, "type": "private"},
                                         "from": {"first_name": "Ali"}}}


def test_telegram_record_updates_advances_offset(tg_settings):
    from tools import telegram_tool as tg

    fresh = tg.record_updates([_update(5, 42, "selam"), {"update_id": 6}])
    assert [m["text"] for m in fresh] == ["selam"]
    assert tg.load_state()["offset"] == 7


def test_telegram_auto_reply_only_for_allowed_chats(tg_settings):
    from core.telegram_handler import TelegramHandler

    handler = TelegramHandler(tg_settings)
    assert handler.allowed == {"42"}
    assert handler.should_auto_reply({"chat_id": "42", "text": "naber"})
    assert not handler.should_auto_reply({"chat_id": "99", "text": "naber"})
    assert not handler.should_auto_reply({"chat_id": "42", "text": "/start"})


def test_telegram_unknown_chat_is_only_mirrored(tg_settings):
    from core.telegram_handler import TelegramHandler

    handler = TelegramHandler(tg_settings)
    posts: list[str] = []

    class Client:
        async def post(self, url, json):  # noqa: A002, ANN001
            posts.append(url)
            return SimpleNamespace(status_code=200)

    item = {"chat_id": "99", "sender": "Yabanci", "text": "merhaba", "message_id": 1}
    asyncio.run(handler._handle(Client(), item))
    assert posts == []  # yanit gonderilmedi
    assert "[TELEGRAM] Yabanci: merhaba" in tg_settings.bridge_outbox_path.read_text(encoding="utf-8")


def test_voice_telegram_send_requires_confirmation(tg_settings, monkeypatch):
    runner = ToolRunner(confirm=lambda _p: False)
    called = []
    monkeypatch.setattr("tools.tool_runner.send_telegram_message",
                        lambda **kw: called.append(kw) or {"status": "gonderildi"})
    assert runner._tool_send_telegram(text="selam")["status"] == "iptal edildi"
    assert called == []


# ------------------------------------------------------------------ ulasim
STOPS = [
    {"DURAK_ID": "10030", "DURAK_ADI": "Konak", "ENLEM": "38.4162", "BOYLAM": "27.1263",
     "DURAKTAN_GECEN_HATLAR": "303-304"},
    {"DURAK_ID": "20001", "DURAK_ADI": "Üçkuyular İskele", "ENLEM": "38.4040", "BOYLAM": "27.0700",
     "DURAKTAN_GECEN_HATLAR": "5"},
]
LINES = [{"HAT_NO": "5", "HAT_ADI": "NARLIDERE - ÜÇKUYULAR", "GUZERGAH_ACIKLAMA": "",
          "ACIKLAMA": "", "HAT_BASLANGIC": "NARLIDERE", "HAT_BITIS": "ÜÇKUYULAR"}]
SCHEDULE = [
    {"HAT_NO": "5", "TARIFE_ID": "3", "GIDIS_SAATI": "06:00", "DONUS_SAATI": "06:45"},
    {"HAT_NO": "5", "TARIFE_ID": "3", "GIDIS_SAATI": "07:00", "DONUS_SAATI": "07:45"},
    {"HAT_NO": "5", "TARIFE_ID": "1", "GIDIS_SAATI": "05:30", "DONUS_SAATI": "06:10"},
]


@pytest.fixture
def transit_data(monkeypatch):
    from tools import transit_tool

    data = {"stops": STOPS, "lines": LINES, "schedule": SCHEDULE}
    monkeypatch.setattr(transit_tool, "_dataset", lambda name: data[name])
    return transit_tool


def test_find_stop_is_turkish_insensitive(transit_data):
    res = transit_data.eshot_find_stop("uckuyular")
    assert res["count"] == 1 and res["stops"][0]["stop_id"] == "20001"


def test_nearby_stops_sorted_by_distance(transit_data):
    res = transit_data.eshot_nearby_stops(38.4165, 27.1265, radius_m=1000)
    assert [s["stop_id"] for s in res["stops"]] == ["10030"]
    assert res["stops"][0]["distance_m"] < 100


def test_line_info_uses_day_tariff(transit_data):
    res = transit_data.eshot_line_info("5", day="pazar")
    assert res["next_from_start"] == ["06:00", "07:00"] and res["daily_trips"] == 2
    assert "error" in transit_data.eshot_line_info("999")


def test_live_buses_without_token_is_explicit_error(transit_data, monkeypatch):
    from config import settings as settings_mod

    fake = settings_mod.get_settings().model_copy(update={"izmir_openapi_token": ""})
    monkeypatch.setattr(transit_data, "get_settings", lambda: fake)
    assert "IZMIR_OPENAPI_TOKEN" in transit_data.eshot_approaching_buses("10030")["error"]


def test_plan_route_builds_transit_url(transit_data):
    res = transit_data.plan_route("", "Konak", open_browser=False)
    assert "travelmode=transit" in res["maps_url"] and res["destination_stops"]


# ------------------------------------------------------------------ OpenRouter arac dongusu
def test_openrouter_agent_tool_loop():
    from agents.agent import Agent
    from agents.schemas import AgentSpec

    def eshot_line_info(line_no: str, day: str = "") -> dict:
        """Hat bilgisi."""
        return {"line_no": line_no, "next_from_start": ["06:00"]}

    call = SimpleNamespace(id="c1", function=SimpleNamespace(
        name="eshot_line_info", arguments=json.dumps({"line_no": "5"})))
    replies = [SimpleNamespace(content="", tool_calls=[call]),
               SimpleNamespace(content="5 numara 06:00'da kalkiyor.", tool_calls=None)]
    seen: list[list] = []

    class FakeRouter:
        available = True

        async def chat(self, messages, model, fallback_models=None, info=None, **kw):  # noqa: ANN001
            seen.append([dict(m) for m in messages])
            assert kw["tools"][0]["function"]["name"] == "eshot_line_info"
            info.update(model=model, fallback=False)
            return replies.pop(0)

    spec = AgentSpec(name="ulasim", title="U", description="d", model="openrouter/free")
    agent = Agent(spec, None, default_models=["gemini-x"], default_max_steps=3, openrouter=FakeRouter())
    agent._callables = [eshot_line_info]
    agent._by_name = {"eshot_line_info": eshot_line_info}

    result = asyncio.run(agent.run("5 ne zaman kalkar"))
    assert result.ok and result.tool_calls == ["eshot_line_info"]
    assert "06:00" in result.text and result.model == "openrouter/free"
    tool_msg = seen[1][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["line_no"] == "5"


def test_default_chain_uses_channel_models(monkeypatch):
    from core import openrouter_client

    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setattr(openrouter_client, "_channel_models", lambda ch: ["x/special"])
    chain = openrouter_client.default_chain("gmail_draft")
    assert chain[0] == "x/special" and chain[-1] == openrouter_client.DEFAULT_CHAIN[-1]
