"""WhatsApp kolu - DOM sinirini taklit eden simulasyon (gercek WhatsApp'a DOKUNMAZ).

Gercek kod: rol/mod/cooldown/kara liste/yonetici komutu/hafiza/insan gonderimi.
Sahte: sohbet kimligi, gelen balonlar, yazma kutusu, gonder dugmesi, bildirim, kopru dosyasi.
"""
import asyncio
import sys

import pytest

from config.settings import get_settings
from core import whatsapp_handler as wh
from core.whatsapp_handler import Mode, Role, WhatsAppConfig, WhatsAppHandler


@pytest.fixture(autouse=True)
def _no_openrouter_env(monkeypatch):
    """Gercek .env'deki OpenRouter anahtari testleri etkilemesin."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)


class FakeBox:
    def __init__(self):
        self.typed: list[tuple[str, int]] = []   # (metin, delay_ms)
        self.filled: list[str] = []

    async def press_sequentially(self, text, delay=0):
        self.typed.append((text, delay))

    async def fill(self, text):
        self.filled.append(text)

    async def press(self, key):
        self.typed.append((f"<{key}>", 0))


class FakePage:
    async def wait_for_timeout(self, ms):
        return None


class FakeNotifier:
    def __init__(self):
        self.sent = []

    async def notify(self, title, message, **kw):
        self.sent.append((title, message))


def make_handler(tmp_path, monkeypatch, **cfg_kw):
    cfg = WhatsAppConfig(
        enabled=True,
        user_data_dir=tmp_path / "sess",
        download_dir=tmp_path / "media",
        admin_numbers=["+90 555 111 22 33"],
        allowed_contacts=["Anne", "+90 532 999 88 77"],
        cooldown_seconds=8.0,
        **cfg_kw,
    )
    h = WhatsAppHandler(get_settings(), cfg, notifier=FakeNotifier())
    h._bridge_path = tmp_path / "outbox.txt"   # gercek kopruyu kirletme
    h.box = FakeBox()
    h.sent_clicks = 0
    h.replies_requested: list[list[str]] = []
    h.contact = "Anne"
    h.msgs: list[dict] = []
    h.group = False
    h.reply_text = "Tamam, yarin gorusuruz."
    h.sleeps: list[float] = []

    async def _identity(page):
        return h.contact

    async def _is_group(page):
        return h.group

    async def _batch(page, cap=12):
        return list(h.msgs)

    async def _resolve(page, m):
        return m["text"]

    async def _focus(page):
        return h.box

    async def _click(page, box):
        h.sent_clicks += 1

    async def _gen(contact, user_messages):
        h.replies_requested.append(list(user_messages))
        return h.reply_text

    monkeypatch.setattr(h, "_chat_identity", _identity)
    monkeypatch.setattr(h, "_is_group", _is_group)
    monkeypatch.setattr(h, "_read_incoming_batch", _batch)
    monkeypatch.setattr(h, "_resolve_message_text", _resolve)
    monkeypatch.setattr(h, "_focus_input", _focus)
    monkeypatch.setattr(h, "_click_send", _click)
    monkeypatch.setattr(h, "_generate_reply", _gen)

    real_sleep = asyncio.sleep

    async def _sleep(secs, *a, **k):
        h.sleeps.append(secs)
        await real_sleep(0)

    monkeypatch.setattr(wh.asyncio, "sleep", _sleep)
    return h


def text(t):
    return {"kind": "text", "text": t, "bubble": None}


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ roller
@pytest.mark.parametrize(
    "contact,role",
    [
        ("+90 555 111 22 33", Role.ADMIN),
        ("+905551112233", Role.ADMIN),
        ("0555 111 22 33", Role.ADMIN),          # basinda 0 olan yerel format
        ("Anne", Role.WHITELIST),
        ("Anne (is)", Role.WHITELIST),          # ad icinde gecen
        ("+90 532 999 88 77", Role.WHITELIST),
        ("Bilinmeyen Kisi", Role.OTHER),
        ("+90 555 111 22 34", Role.OTHER),      # bir hane farkli
    ],
)
def test_role_matching(tmp_path, monkeypatch, contact, role):
    h = make_handler(tmp_path, monkeypatch)
    assert h._role_for(contact) is role


def test_unauthorised_contact_gets_no_reply_and_is_not_reopened(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.contact = "Yabanci"
    h.msgs = [text("selam")]
    run(h._process_open_chat(FakePage()))
    assert h.box.typed == [] and h.replies_requested == []
    assert "Yabanci" in h._ignored


def test_group_chats_ignored_by_default(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.group = True
    h.msgs = [text("herkese selam")]
    run(h._process_open_chat(FakePage()))
    assert h.box.typed == [] and h.replies_requested == []


# ------------------------------------------------------------------ yanit akisi
def test_multiple_incoming_messages_get_one_reply_addressing_all(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.msgs = [text("naber"), text("aksam bos musun"), text("film izleyelim mi")]
    run(h._process_open_chat(FakePage()))
    assert h.replies_requested == [["naber", "aksam bos musun", "film izleyelim mi"]]
    assert h.sent_clicks == 1
    assert "".join(t for t, _ in h.box.typed) == h.reply_text


def test_no_incoming_means_no_reply(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.msgs = []      # son balon bizden
    run(h._process_open_chat(FakePage()))
    assert h.replies_requested == [] and h.box.typed == []


def test_memory_is_recorded_and_bounded(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch, history_size=4)
    for i in range(5):
        h._last_reply_at.clear()           # cooldown'u atla
        h.msgs = [text(f"mesaj {i}")]
        run(h._process_open_chat(FakePage()))
    hist = h._memory.history("Anne")
    assert len(hist) == 4 and hist[-1]["role"] == "assistant"
    assert hist[-2]["text"] == "mesaj 4"


def test_cooldown_delays_second_reply_for_non_admin(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.msgs = [text("bir")]
    run(h._process_open_chat(FakePage()))
    h.msgs = [text("iki")]
    run(h._process_open_chat(FakePage()))
    assert len(h.replies_requested) == 1        # ikincisi cooldown'da


def test_failed_generation_sets_retry_backoff(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.reply_text = ""
    h.msgs = [text("selam")]
    run(h._process_open_chat(FakePage()))
    assert h.box.typed == [] and h._retry_after.get("Anne", 0) > 0
    run(h._process_open_chat(FakePage()))       # backoff icinde: tekrar denemez
    assert len(h.replies_requested) == 1


# ------------------------------------------------------------------ modlar / kara liste
def test_silent_mode_never_replies(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.mode = Mode.SILENT
    h.msgs = [text("selam")]
    run(h._process_open_chat(FakePage()))
    assert h.box.typed == [] and h.replies_requested == []


def test_manual_mode_notifies_admin_instead_of_replying(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.mode = Mode.MANUAL
    h.msgs = [text("acil bir sey var")]
    run(h._process_open_chat(FakePage()))
    assert h.box.typed == []
    assert h._notifier.sent and "acil bir sey var" in h._notifier.sent[0][1]


def test_blacklisted_word_blocks_reply_and_notifies(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch, blacklisted_words=["kripto", "reklam"])
    h.msgs = [text("merhaba"), text("bu KRIPTO firsatini kacirma")]
    run(h._process_open_chat(FakePage()))
    assert h.box.typed == [] and h.replies_requested == []
    assert h._notifier.sent


def test_blacklist_matches_whole_words_only(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch, blacklisted_words=["ad"])
    h.msgs = [text("adam gibi adamsin")]      # 'ad' kelime degil, 'adam' icinde
    run(h._process_open_chat(FakePage()))
    assert len(h.replies_requested) == 1


# ------------------------------------------------------------------ yonetici komutlari
def test_admin_command_mode_change_and_plain_send(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.contact = "+90 555 111 22 33"
    h.msgs = [text("JARVIS modu sessiz")]
    run(h._process_open_chat(FakePage()))
    assert h.mode is Mode.SILENT
    assert h.box.filled, "komut yaniti hizli (fill) gonderilmeli"
    assert h.replies_requested == []          # LLM'e gitmemeli


def test_non_admin_cannot_run_admin_commands(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.contact = "Anne"
    h.msgs = [text("JARVIS modu sessiz")]
    run(h._process_open_chat(FakePage()))
    assert h.mode is Mode.AUTO
    assert h.box.filled == []


# ------------------------------------------------------------------ insan simulasyonu
def test_human_send_thinks_then_types_gradually(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    msg = "Aksam bos sayilirim, film izleyebiliriz."
    run(h._human_send(FakePage(), msg))
    assert h.sleeps, "dusunme beklemesi olmali"
    assert 2.0 * 0.8 <= h.sleeps[0] <= 6.0 * 1.2
    (typed, delay), = h.box.typed
    assert typed == msg and 28 <= delay <= 65     # harf harf, 28-65 ms/karakter
    assert h.sent_clicks == 1


def test_think_time_grows_with_length_and_is_capped(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    run(h._think_pause(10))
    run(h._think_pause(400))
    short, long_ = h.sleeps
    assert long_ > short
    assert long_ <= 6.0 * 1.2 + 1e-9


def test_typing_delay_can_be_disabled(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch, typing_delay_enabled=False)
    run(h._think_pause(100))
    assert h.sleeps == []


def test_long_reply_types_head_visibly_then_pastes_rest(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    msg = "x" * 300
    run(h._human_send(FakePage(), msg))
    (head, d1), (rest, d2) = h.box.typed
    assert len(head) == 60 and d1 > 0 and rest == "x" * 240 and d2 == 0


def test_no_input_box_means_no_send(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)

    async def none(page):
        return None

    monkeypatch.setattr(h, "_focus_input", none)
    run(h._human_send(FakePage(), "merhaba"))
    assert h.sent_clicks == 0


# ------------------------------------------------------------------ kopru aynasi
def test_conversation_is_mirrored_to_bridge(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.msgs = [text("selam")]
    run(h._process_open_chat(FakePage()))
    lines = (tmp_path / "outbox.txt").read_text(encoding="utf-8").splitlines()
    assert any(l.startswith("[WHATSAPP] Anne: selam") for l in lines)
    assert any("(JARVIS->Anne)" in l for l in lines)


# ------------------------------------------------------------------ tek mesaj birlestirme
def test_merge_messages_joins_lines_and_skips_blanks():
    assert WhatsAppHandler._merge_messages(["naber", "  ", "aksam bos musun ", ""]) == "naber\naksam bos musun"


def test_three_incoming_messages_are_stored_as_one_user_turn(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.msgs = [text("naber"), text("aksam bos musun"), text("film izleyelim mi")]
    run(h._process_open_chat(FakePage()))
    hist = h._memory.history("Anne")
    assert [x["role"] for x in hist] == ["user", "assistant"]          # 3 degil, 1 kullanici turu
    assert hist[0]["text"] == "naber\naksam bos musun\nfilm izleyelim mi"
    assert h.sent_clicks == 1 and len(h.box.typed) == 1                 # tek gonderim


def test_generate_reply_sends_one_user_content_and_one_line_answer(tmp_path, monkeypatch):
    """Gercek _generate_reply: modele TEK 'user' turu gider, yanit tek satira indirilir."""
    import agents.genai_util as gu

    h = _real_handler(tmp_path)     # gercek _generate_reply (stub yok); OpenRouter anahtari autouse ile temiz
    seen = {}

    class R:
        text = "iyiyim\n\nyemek yedim\ncumartesi bakariz"

    async def fake_generate(client, *, model, contents, config, **kw):
        seen["contents"] = contents
        return R()

    monkeypatch.setattr(gu, "generate_with_retry", fake_generate)
    out = run(h._generate_reply("Anne", ["naber", "yemek yedin mi", "cumartesi gelir misin"]))
    user_turns = [c for c in seen["contents"] if c.role == "user"]
    assert len(user_turns) == 1
    assert user_turns[0].parts[0].text == "naber\nyemek yedin mi\ncumartesi gelir misin"
    assert "\n" not in out and out == "iyiyim yemek yedim cumartesi bakariz"


def test_system_prompt_asks_for_a_single_message():
    assert "TEK bir mesaj" in WhatsAppConfig().system_prompt


# ------------------------------------------------------------------ arama destekli yanit
def _real_handler(tmp_path, **kw):
    return WhatsAppHandler(get_settings(), WhatsAppConfig(
        enabled=True, user_data_dir=tmp_path / "s", download_dir=tmp_path / "m", **kw),
        notifier=FakeNotifier())


def test_system_instruction_has_date_and_search_guidance(tmp_path):
    h = _real_handler(tmp_path)
    si = h._system_instruction()
    assert "Su an:" in si and "Google aramasiyla" in si
    h2 = _real_handler(tmp_path, web_search_enabled=False)
    assert "Google aramasiyla" not in h2._system_instruction()


def test_reply_uses_search_tool_and_falls_back_without_it(tmp_path, monkeypatch):
    import agents.genai_util as gu

    h = _real_handler(tmp_path)
    calls = []

    class R:
        text = "Fener 2-1 kazandi"

    async def fake(client, *, model, contents, config, **kw):
        calls.append(bool(getattr(config, "tools", None)))
        if len(calls) == 1:
            raise RuntimeError("400 INVALID_ARGUMENT: Tool use is not supported for this model")
        return R()

    monkeypatch.setattr(gu, "generate_with_retry", fake)
    out = run(h._generate_reply("Anne", ["Fener dun kac kac bitti"]))
    assert calls == [True, False]           # once aramali, hata olunca aramasiz
    assert out == "Fener 2-1 kazandi"


def test_search_disabled_never_sends_tools(tmp_path, monkeypatch):
    import agents.genai_util as gu

    h = _real_handler(tmp_path, web_search_enabled=False)
    seen = []

    class R:
        text = "tamam"

    async def fake(client, *, model, contents, config, **kw):
        seen.append(getattr(config, "tools", None))
        return R()

    monkeypatch.setattr(gu, "generate_with_retry", fake)
    run(h._generate_reply("Anne", ["selam"]))
    assert seen == [None]


def test_quota_error_does_not_trigger_slow_no_tools_retry(tmp_path, monkeypatch):
    import agents.genai_util as gu

    h = _real_handler(tmp_path)
    calls = []

    async def fake(client, *, model, contents, config, **kw):
        calls.append(bool(getattr(config, "tools", None)))
        raise RuntimeError("429 RESOURCE_EXHAUSTED. You exceeded your current quota")

    monkeypatch.setattr(gu, "generate_with_retry", fake)
    assert run(h._generate_reply("Anne", ["selam"])) == ""     # bos -> handler 60 sn bekler
    assert calls == [True]                                       # ikinci (aramasiz) deneme YOK


def test_reply_generation_is_time_bounded(tmp_path, monkeypatch):
    import agents.genai_util as gu

    h = _real_handler(tmp_path)
    monkeypatch.setattr(WhatsAppHandler, "REPLY_TIMEOUT_S", 0.2)

    async def slow(client, *, model, contents, config, **kw):
        await asyncio.sleep(5)

    monkeypatch.setattr(gu, "generate_with_retry", slow)
    assert run(h._generate_reply("Anne", ["selam"])) == ""


def test_dead_model_removed_from_default_chain():
    from config.settings import get_settings

    assert "gemini-2.5-flash" not in get_settings().agent_model_chain


# ------------------------------------------------------------------ durustluk / kisisel sorular
@pytest.mark.parametrize("msg", [
    "nerdesin", "Neredesin?", "NERDESİN", "nerdesin lan", "napıyorsun", "ne yapıyosun",
    "müsait misin", "uygun musun", "bugün gelecek misin", "ne zaman gelirsin", "kiminlesin",
])
def test_personal_question_detected(msg):
    assert WhatsAppHandler._is_personal_question(msg)


@pytest.mark.parametrize("msg", [
    "ders notlarini atar misin", "naber", "yarin hava nasil", "fener kac kac bitti",
    "nerede yapiliyor mac", "nerdeymis o kitap",
])
def test_ordinary_questions_not_flagged(msg):
    assert not WhatsAppHandler._is_personal_question(msg)


@pytest.mark.parametrize("msg", ["nerde", "Nerede?", "nerde\nacil", "naber\nnerde?"])
def test_bare_where_is_personal(msg):
    assert WhatsAppHandler._is_personal_question(msg)


def test_honesty_rules_always_appended_even_with_custom_prompt(tmp_path):
    h = _real_handler(tmp_path, system_prompt="Ozel prompt")
    si = h._system_instruction()
    assert si.startswith("Ozel prompt")
    assert "ASLA insan oldugunu soyleme" in si and "UYDURMA" in si


def test_personal_context_added_only_when_flagged(tmp_path):
    h = _real_handler(tmp_path)
    assert "KISISEL DURUM SORUSU" not in h._system_instruction()
    assert "KISISEL DURUM SORUSU" in h._system_instruction(personal=True)


def test_status_unknown_when_no_schedule(tmp_path, monkeypatch):
    import tools.okul_tool as ot

    monkeypatch.setattr(ot, "_load", lambda: None)
    assert "BILINMIYOR" in _real_handler(tmp_path)._status_context()


def test_status_uses_real_class_schedule(tmp_path, monkeypatch):
    import tools.okul_tool as ot
    from datetime import datetime as real_dt

    now = real_dt.now()
    data = {"schedule": [{"name": "Matematik", "day": now.weekday(),
                          "start": max(0, now.hour - 1), "end": now.hour + 1,     # 24 de gecerli (gece yarisi kenari)
                          "room": "B12", "instructor": "X"}]}
    monkeypatch.setattr(ot, "_load", lambda: data)
    ctx = _real_handler(tmp_path)._status_context()
    assert "Matematik" in ctx and "B12" in ctx and "dersinde" in ctx


def test_status_reports_next_class_without_claiming_location(tmp_path, monkeypatch):
    import tools.okul_tool as ot
    from datetime import datetime as real_dt

    now = real_dt.now()
    if now.hour >= 22:
        pytest.skip("gunun sonu: sonraki ders saati olusturulamiyor")
    data = {"schedule": [{"name": "Fizik", "day": now.weekday(),
                          "start": now.hour + 1, "end": now.hour + 2, "room": "", "instructor": ""}]}
    monkeypatch.setattr(ot, "_load", lambda: data)
    ctx = _real_handler(tmp_path)._status_context()
    assert "Fizik" in ctx and "BILINMIYOR" in ctx


def test_personal_question_notifies_admin_and_reply_is_sent(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.msgs = [text("nerdesin")]
    run(h._process_open_chat(FakePage()))
    assert h.sent_clicks == 1
    assert h._notifier.sent and "nerdesin" in h._notifier.sent[0][1]
    assert "seni soruyorlar" in h._notifier.sent[0][0]


def test_ordinary_message_does_not_notify_admin(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.msgs = [text("naber")]
    run(h._process_open_chat(FakePage()))
    assert h._notifier.sent == []


def test_personal_notification_can_be_disabled(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch, notify_personal_questions=False)
    h.msgs = [text("nerdesin")]
    run(h._process_open_chat(FakePage()))
    assert h._notifier.sent == []


def test_admin_own_question_is_not_treated_as_personal(tmp_path, monkeypatch):
    h = make_handler(tmp_path, monkeypatch)
    h.contact = "+90 555 111 22 33"
    h.msgs = [text("nerdesin")]
    run(h._process_open_chat(FakePage()))
    assert h._notifier.sent == []


def test_generate_reply_passes_personal_context_to_model(tmp_path, monkeypatch):
    import agents.genai_util as gu
    import tools.okul_tool as ot

    monkeypatch.setattr(ot, "_load", lambda: None)
    h = _real_handler(tmp_path, admin_numbers=["+900000000000"])
    seen = {}

    class R:
        text = "Sezai'ye ilettim, musait olunca doner."

    async def fake(client, *, model, contents, config, **kw):
        seen["system"] = config.system_instruction
        return R()

    monkeypatch.setattr(gu, "generate_with_retry", fake)
    run(h._generate_reply("Kadir", ["nerdesin"]))
    assert "KISISEL DURUM SORUSU" in seen["system"] and "BILINMIYOR" in seen["system"]
    run(h._generate_reply("Kadir", ["naber"]))
    assert "KISISEL DURUM SORUSU" not in seen["system"]


# ------------------------------------------------------------------ OpenRouter saglayicisi
def _or_handler(tmp_path, monkeypatch, **kw):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    kw.setdefault("openrouter_model", "vendor/model-a:free")
    return _real_handler(tmp_path, **kw)


def test_provider_order(tmp_path, monkeypatch):
    assert _real_handler(tmp_path)._provider_order() == ["gemini"]               # anahtar yok
    h = _or_handler(tmp_path, monkeypatch)
    assert h._provider_order() == ["openrouter", "gemini"]
    assert _or_handler(tmp_path, monkeypatch, reply_provider="gemini")._provider_order() == ["gemini"]
    assert _or_handler(tmp_path, monkeypatch, reply_provider="openrouter")._provider_order() == ["openrouter"]
    assert _real_handler(tmp_path, reply_provider="openrouter")._provider_order() == []   # anahtar yok


def test_model_from_env_overrides_config_and_dedupes(tmp_path, monkeypatch):
    h = _or_handler(tmp_path, monkeypatch, openrouter_fallback_models=["b:free", "vendor/model-a:free", "b:free"])
    monkeypatch.setenv("OPENROUTER_MODEL", "env/model:free")
    assert h._openrouter_models() == ["env/model:free", "b:free", "vendor/model-a:free"]


def test_openrouter_is_used_first_and_gemini_not_called(tmp_path, monkeypatch):
    import agents.genai_util as gu

    h = _or_handler(tmp_path, monkeypatch)
    seen = {}

    async def chat(model, messages):
        seen["model"], seen["messages"] = model, messages
        return "Sezai su an cevap veremiyor, ilettim."

    async def boom(*a, **k):
        raise AssertionError("Gemini cagrilmamali")

    monkeypatch.setattr(h, "_openrouter_chat", chat)
    monkeypatch.setattr(gu, "generate_with_retry", boom)
    h._memory.add("Kadir", "user", "selam")
    h._memory.add("Kadir", "assistant", "selam, nasilsin")
    out = run(h._generate_reply("Kadir", ["nerdesin"]))
    assert out == "Sezai su an cevap veremiyor, ilettim."
    roles = [m["role"] for m in seen["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert seen["messages"][-1]["content"] == "nerdesin"
    assert "KISISEL DURUM SORUSU" in seen["messages"][0]["content"]
    assert "ASLA insan oldugunu soyleme" in seen["messages"][0]["content"]
    assert "Internete erisemiyorsun" in seen["messages"][0]["content"]     # arama yok yonergesi


def test_openrouter_empty_reply_tries_next_model(tmp_path, monkeypatch):
    h = _or_handler(tmp_path, monkeypatch, openrouter_fallback_models=["vendor/model-b:free"])
    tried = []

    async def chat(model, messages):
        tried.append(model)
        return "" if model.endswith("model-a:free") else "tamam, bakiyorum"

    monkeypatch.setattr(h, "_openrouter_chat", chat)
    assert run(h._generate_reply("Kadir", ["merhaba"])) == "tamam, bakiyorum"
    assert tried == ["vendor/model-a:free", "vendor/model-b:free"]


def test_system_role_unsupported_folds_instruction_into_user_message(tmp_path, monkeypatch):
    h = _or_handler(tmp_path, monkeypatch)
    payloads = []

    async def chat(model, messages):
        payloads.append(messages)
        if len(payloads) == 1:
            raise RuntimeError("Error code: 400 - Developer instruction is not enabled for this model")
        return "olur"

    monkeypatch.setattr(h, "_openrouter_chat", chat)
    assert run(h._generate_reply("Kadir", ["gelir misin"])) == "olur"
    assert payloads[0][0]["role"] == "system"
    assert all(m["role"] != "system" for m in payloads[1])
    assert "[TALIMAT]" in payloads[1][0]["content"] and "gelir misin" in payloads[1][0]["content"]


def test_all_openrouter_failures_fall_back_to_gemini(tmp_path, monkeypatch):
    import agents.genai_util as gu

    h = _or_handler(tmp_path, monkeypatch)

    async def chat(model, messages):
        raise RuntimeError("429 Rate limit exceeded: free-models-per-day")

    class R:
        text = "gemini yedegi cevap verdi"

    async def gem(client, *, model, contents, config, **kw):
        return R()

    monkeypatch.setattr(h, "_openrouter_chat", chat)
    monkeypatch.setattr(gu, "generate_with_retry", gem)
    assert run(h._generate_reply("Kadir", ["naber"])) == "gemini yedegi cevap verdi"


def test_openrouter_only_mode_does_not_use_gemini(tmp_path, monkeypatch):
    import agents.genai_util as gu

    h = _or_handler(tmp_path, monkeypatch, reply_provider="openrouter")

    async def chat(model, messages):
        raise RuntimeError("429")

    async def boom(*a, **k):
        raise AssertionError("Gemini cagrilmamali")

    monkeypatch.setattr(h, "_openrouter_chat", chat)
    monkeypatch.setattr(gu, "generate_with_retry", boom)
    assert run(h._generate_reply("Kadir", ["naber"])) == ""


def test_reasoning_tags_stripped_and_flattened():
    out = WhatsAppHandler._clean_reply("<think>once dusunuyorum\nuzun</think>\nIyiyim\n\nsen nasilsin")
    assert out == "Iyiyim sen nasilsin"


def test_fold_system_helper():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    folded = WhatsAppHandler._fold_system(msgs)
    assert folded == [{"role": "user", "content": "[TALIMAT]\nS\n\n[MESAJ]\nU"}]


def test_api_key_never_appears_in_logs(tmp_path, monkeypatch):
    from loguru import logger

    h = _or_handler(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-SECRET-DEGER-123")
    lines = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")

    async def chat(model, messages):
        raise RuntimeError("429 Rate limit")

    monkeypatch.setattr(h, "_openrouter_chat", chat)
    try:
        run(h._generate_reply("Kadir", ["naber"]))
    except Exception:
        pass
    finally:
        logger.remove(sink)
    assert not any("SECRET-DEGER" in l for l in lines)
