"""Cevrimdisi yazili sohbet - canli oturum (Gemini Live) yokken yerel modelle aracli sohbet.

HUD yazi kutusu normalde metni canli oturuma enjekte eder; oturum yoksa (internet yok /
Live koptu) `BrainEngine.inject_bridge_message` metni buraya verir. Yerel model
(`core/local_llm.py`) yalnizca internetsiz calisan ARAC ALT KUMESIYLE konusur:
100+ aracin semasi 7B modelin baglamini tasirir ve onu yavaslatir.
Araclar motorun kendi `ToolRunner`'i ile calisir -> onay kapilari aynen gecerli.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from google.genai import types
from loguru import logger

from core.local_llm import LocalLLM, LocalLLMError

# Internetsiz calisan araclar (web / e-posta / telefon / Spotify YOK)
OFFLINE_TOOLS: tuple[str, ...] = (
    "get_current_datetime", "get_system_status", "list_directory", "read_text_file",
    "write_text_file", "remember_note", "recall_notes", "open_application", "open_path",
    "close_application", "window_action", "media_control", "list_processes", "calculate",
    "clipboard_get", "clipboard_set", "set_reminder", "list_reminders", "cancel_reminder",
    "okul_status", "okul_next_exams", "okul_today_tasks", "okul_schedule", "memory_search",
)
MAX_STEPS = 5
MAX_TURNS = 12  # gecmiste tutulan kullanici turu
PREFIX = "(yerel) "

SYSTEM_PROMPT = (
    "Sen JARVIS'sin; Sezai'nin Turkce konusan kisisel asistanisin. Su an CEVRIMDISI "
    "moddasin: internet yok, yerel bir model olarak calisiyorsun. Yalnizca sana verilen "
    "araclari kullan; web aramasi, e-posta, telefon ve muzik servisleri YOK - istenirse "
    "internet gelince yapilabilecegini soyle. Kisa ve net yanit ver, 'efendim' diye hitap "
    "edebilirsin. Bilmedigin bir seyi (guncel haber, skor, hava) asla uydurma."
)


def offline_declarations(names: tuple[str, ...] = OFFLINE_TOOLS) -> list[types.FunctionDeclaration]:
    from tools.tool_declarations import get_tools

    wanted = set(names)
    found = [
        fd for tool in get_tools() for fd in (tool.function_declarations or [])
        if fd.name in wanted
    ]
    missing = wanted - {fd.name for fd in found}
    if missing:
        logger.debug(f"Cevrimdisi sohbet: deklarasyonu olmayan araclar atlandi: {sorted(missing)}")
    return found


class OfflineChat:
    def __init__(
        self,
        tool_runner: Any,
        local: LocalLLM,
        *,
        notify: Callable[..., None] = lambda *a: None,
        log_conversation: Callable[[str, str], None] = lambda role, text: None,
        declarations: list[types.FunctionDeclaration] | None = None,
    ) -> None:
        self.tool_runner = tool_runner
        self.local = local
        self._notify = notify
        self._log = log_conversation
        decls = offline_declarations() if declarations is None else declarations
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.4,
            tools=[types.Tool(function_declarations=decls)] if decls else None,
        )
        self.history: list[types.Content] = []
        self._lock = asyncio.Lock()

    async def reply(self, text: str) -> str:
        """Kullanici metnine yerel modelle (gerekirse arac kullanarak) yanit verir ve yayinlar."""
        text = (text or "").strip()
        if not text:
            return ""
        async with self._lock:
            answer = await self._run(text)
        self._notify("on_assistant_transcript", PREFIX + answer, True)
        self._log("user", text)
        self._log("jarvis", PREFIX + answer)
        return answer

    async def _run(self, text: str) -> str:
        turn: list[types.Content] = [types.Content(role="user", parts=[types.Part(text=text)])]
        for _ in range(MAX_STEPS):
            try:
                response, _model = await self.local.generate([*self.history, *turn], self.config)
            except LocalLLMError as exc:
                logger.warning(f"Cevrimdisi sohbet: {exc}")
                return "Yerel model su an yanit veremiyor (Ollama acik mi?)."
            content = response.candidates[0].content
            calls = [p.function_call for p in content.parts or [] if p.function_call]
            if not calls:
                answer = (response.text or "").strip() or "(bos yanit)"
                turn.append(types.Content(role="model", parts=[types.Part(text=answer)]))
                self._remember(turn)
                return answer
            turn.append(content)
            turn.append(types.Content(role="user", parts=await self._run_tools(calls)))
        self._remember(turn)
        return "Bu istegi yerel modelle tamamlayamadim (adim siniri asildi)."

    async def _run_tools(self, calls: list[types.FunctionCall]) -> list[types.Part]:
        self._notify("on_tool_call", [c.name for c in calls])
        parts: list[types.Part] = []
        for call in calls:
            if call.name not in OFFLINE_TOOLS:  # model listede olmayan bir arac uydurdu
                resp = types.FunctionResponse(
                    name=call.name, response={"error": "Bu arac cevrimdisi modda yok."}
                )
            else:
                resp = await self.tool_runner.dispatch(call)
            payload = resp.response or {}
            ok = "error" not in payload
            self._notify("on_tool_result", call.name or "?", ok,
                         str(payload.get("error") if not ok else payload)[:200])
            parts.append(types.Part(function_response=resp))
        return parts

    def _remember(self, turn: list[types.Content]) -> None:
        self.history.extend(turn)
        # en eski kullanici turlarini (ara arac adimlariyla birlikte) at
        starts = [
            i for i, c in enumerate(self.history)
            if c.role == "user" and any(p.text for p in c.parts or [])
        ]
        if len(starts) > MAX_TURNS:
            self.history = self.history[starts[-MAX_TURNS]:]
