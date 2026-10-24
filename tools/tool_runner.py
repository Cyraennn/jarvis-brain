"""Arac calistirici (Dispatcher).

Model bir `tool_call` gonderdiginde ilgili implementasyon burada bulunur ve
`asyncio.to_thread` uzerinde (event loop'u tikamadan) calistirilir. Sonuc her
zaman gecerli bir `types.FunctionResponse` olarak doner; hata durumunda bile.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from google.genai import types
from loguru import logger

from config.settings import APP_DIR
from tools.adb_tool import (
    adb_connect_wifi,
    adb_disconnect_wifi,
    adb_enable_wifi,
    adb_list_devices,
    adb_open,
    adb_pair_wifi,
    adb_play_media,
    adb_set_unlock_pin,
    adb_shell,
    adb_unlock_device,
)
from tools.app_launcher import (  # noqa: F401 - open_console_app: uzak modda vekillenir (el_tools)
    open_application,
    open_console_app,
    open_gesture_hud,
    open_path,
    open_website,
)
from tools.basic_tools import (
    get_current_datetime,
    get_system_status,
    list_directory,
    read_text_file,
    recall_notes,
    remember_note,
    write_text_file,
)
from tools.email_tools import check_email, read_email, search_email, send_email
from tools.keyboard_input import (
    clear_field,
    click_at,
    close_active_tab,
    close_window,
    describe_window,
    drag_select,
    erase_chars,
    find_close_target,
    is_close_combo,
    move_mouse,
    press_keys,
    scroll,
    select_line,
    select_word,
    type_in_browser,
    type_in_search,
    type_text,
)
from tools.window_control import close_application as _close_app
from tools.window_control import exe_for, is_protected_exe, resolve_close_target

# --- yeni yetenek modulleri ---
from tools.code_tools import git_command, git_is_write, run_python, run_shell
from tools.file_ops import (
    copy_path,
    find_files,
    make_folder,
    move_path,
    rename_path,
    zip_paths,
)
from tools.gbrain_tools import kb_ask, kb_recent, kb_search, kb_write, summarize_document
from tools.vault_search import memory_search
from tools.maintenance import (
    cleanup_run,
    cleanup_scan,
    describe_plan,
    empty_recycle_bin,
    plan_cleanup,
)
from tools.panel_tools import (
    close_panel,
    show_document,
    map_control,
    show_info,
    show_map,
    show_route,
    show_market,
    show_news,
    show_spotify,
    show_video,
    show_weather,
    show_website,
    show_wikipedia,
)
from tools.okul_tool import (
    okul_add_exam,
    okul_add_task,
    okul_gpa,
    okul_next_exams,
    okul_schedule,
    okul_search_notes,
    okul_status,
    okul_today_tasks,
)
from tools.keyboard_input import media_control, window_action
from tools.spotify_tool import (
    spotify_control,
    spotify_devices,
    spotify_now_playing,
    spotify_play,
    spotify_queue,
    spotify_volume,
)
from tools.quick_tools import (
    calculate,
    clipboard_get,
    clipboard_set,
    convert_currency,
    get_weather,
    translate,
    web_search,
)
from tools.scheduler_tools import (
    add_routine,
    cancel_reminder,
    list_reminders,
    list_routines,
    remove_routine,
    schedule_task,
    set_reminder,
)
from tools.system_tools import kill_process, list_processes
from tools.vision_tools import ocr_image, ocr_screen, record_screen, save_screenshot

# --- haberlesme + ulasim ---
from tools.gmail_tool import create_email_draft, generate_auto_reply_draft, get_unread_emails
from tools.telegram_tool import (
    get_latest_telegram_updates,
    reply_to_telegram_message,
    send_telegram_message,
)
from tools.phone_tools import (
    open_phone_app,
    phone_call,
    phone_location,
    phone_status,
    ring_phone,
    send_file_to_phone,
    send_sms,
    set_alarm,
    set_timer,
)
from tools.transit_tool import (
    eshot_approaching_buses,
    eshot_find_stop,
    eshot_line_info,
    eshot_nearby_stops,
    izmirim_kart_balance,
    plan_route,
)

# --- MCP gecidi + tarayici ajani ---
from tools.browser_tool import browser_open
from tools.mcp_hub import get_hub, mcp_list_tools, mcp_servers

# Tek bir arac cagrisinin ust siniri (sn); asilirsa modele hata doner, beyin bloklanmaz.
# Onay penceresi beklemeleri (uzak onay 120 sn) ve 120 sn'lik ekran kaydi sigacak kadar genis.
TOOL_TIMEOUT_S = 300.0

ConfirmFn = Callable[[str], bool]
ExitFn = Callable[[], None]
TypingFn = Callable[[bool], None]
ScreenFn = Callable[[], None]
# Icerik paneli: arayuz gosterebildiyse True doner (bkz. core/events.py::on_panel)
PanelFn = Callable[[dict[str, Any]], bool]

BRIDGE_INBOX = APP_DIR / "bridge" / "inbox.txt"

ToolFn = Callable[..., Any] | Callable[..., Awaitable[Any]]


def _dispatch_to_agent(agent: str, task: str) -> dict[str, Any]:
    """Bir gorevi cok-ajanli sisteme (orkestratore) iletir."""
    agent = (agent or "").strip() or "auto"
    task = (task or "").strip()
    if not task:
        return {"error": "'task' zorunludur."}
    BRIDGE_INBOX.parent.mkdir(parents=True, exist_ok=True)
    task_id = uuid.uuid4().hex[:12]
    payload = json.dumps(
        {
            "id": task_id,
            "agent": agent,
            "task": task,
            "source": "cyraen",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        ensure_ascii=False,
    )
    with BRIDGE_INBOX.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
    return {"status": "kuyruga alindi", "agent": agent, "task_id": task_id}


# --------------------------------------------------------------------- runner

# Telefon uygulamasi bagliyken ADB'nin "telefonda ac" araclari yerine uygulama araclari kullanilir:
# model "telefonumda haritayi ac" deyince ADB'ye gitmesin (adb_shell gibi acik ADB istekleri serbest).
_PHONE_APP_ALTERNATIVES = {
    "adb_open": "open_phone_app (uygulama) ya da show_map / show_* (panel telefonda da acilir)",
    "adb_list_devices": "telefon uygulamasi zaten bagli; phone_status ile pil/ag durumuna bakilabilir",
    "adb_play_media": "open_phone_app ya da Spotify araclari",
    "adb_unlock_device": "telefon uygulamasi bagliyken kilit acmaya gerek yok",
}


def _phone_app_redirect(name: str) -> "dict[str, Any] | None":
    if name not in _PHONE_APP_ALTERNATIVES:
        return None
    from web.phone_link import PHONE

    if not PHONE.connected:
        return None
    return {"error": f"Telefon uygulamasi bagli; ADB yerine bunu kullan: {_PHONE_APP_ALTERNATIVES[name]}. "
                      "Kullanici acikca USB/ADB isterse adb_shell kullanilabilir."}


class ToolRunner:
    def __init__(
        self,
        confirm: ConfirmFn | None = None,
        on_exit: ExitFn | None = None,
        on_typing: TypingFn | None = None,
        on_look_at_screen: ScreenFn | None = None,
        on_panel: PanelFn | None = None,
        disabled_groups: "set[str] | None" = None,
    ) -> None:
        from tools.tool_declarations import disabled_tool_names

        # CYRAEN_TOOLS_OFF ile kapatilan gruplar: model bunlari gormez; yine de cagrilirsa calistirilmaz
        self._disabled: set[str] = disabled_tool_names(disabled_groups)
        # Onay geri cagrimi: kapatma gibi geri alinamaz islemler icin kullanilir.
        self._confirm: ConfirmFn = confirm or (lambda _prompt: True)
        self._on_exit: ExitFn = on_exit or (lambda: None)
        # Baska pencereye yazarken arayuzun cekilmesi icin bildirim.
        self._on_typing: TypingFn = on_typing or (lambda _active: None)
        self._on_look_at_screen: ScreenFn = on_look_at_screen or (lambda: None)
        # Dogrulanmis icerigi (video, Wikipedia, belge...) arayuzdeki panele iletir.
        self._on_panel: PanelFn = on_panel or (lambda _payload: False)
        # En son kapatilan pencere (`describe_window` ciktisi) - "geri ac" icin.
        self._last_closed: dict[str, Any] = {}
        self._registry: dict[str, ToolFn] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register("get_current_datetime", get_current_datetime)
        self.register("get_system_status", get_system_status)
        self.register("list_directory", list_directory)
        self.register("read_text_file", read_text_file)
        self.register("write_text_file", write_text_file)
        self.register("remember_note", remember_note)
        self.register("recall_notes", recall_notes)
        self.register("dispatch_to_agent", _dispatch_to_agent)
        self.register("open_application", lambda **kw: self._retracted(open_application, **kw))
        self.register("open_website", lambda **kw: self._retracted(open_website, **kw))
        self.register("open_path", open_path)
        self.register("open_gesture_hud", open_gesture_hud)
        from tools import el_tools

        for name in ("el_kontrolu_ac", "el_kontrolu_kapat", "el_gezegen", "kitaplik_listele",
                     "kitaplik_tara", "kitaplik_ekle", "kitap_adlandir", "kitap_not_ekle",
                     "kitap_durum", "kitap_defter_doldur", "kitap_ozetle", "calibre_esitle", "kitap_ac", "kitap_tani"):
            self.register(name, getattr(el_tools, name))
        self.register("type_in_search", lambda **kw: self._retracted(type_in_search, **kw))
        self.register("type_in_browser", type_in_browser)
        self.register("type_text", self._tool_type_text)
        self.register("click_at", lambda **kw: self._retracted(click_at, **kw))
        self.register("drag_select", lambda **kw: self._retracted(drag_select, **kw))
        self.register("select_word", lambda **kw: self._retracted(select_word, **kw))
        self.register("select_line", lambda **kw: self._retracted(select_line, **kw))
        self.register("clear_field", lambda **kw: self._retracted(clear_field, **kw))
        self.register("erase_chars", erase_chars)
        self.register("move_mouse", move_mouse)
        self.register("scroll", scroll)
        self.register("press_keys", self._tool_press_keys)
        self.register("close_application", self._tool_close_application)
        self.register("close_active_tab", self._tool_close_active_tab)
        self.register("reopen_last_closed", self._tool_reopen_last_closed)
        self.register("exit_application", self._tool_exit_application)
        self.register("look_at_screen", self._tool_look_at_screen)
        self.register("check_email", check_email)
        self.register("read_email", read_email)
        self.register("search_email", search_email)
        self.register("send_email", self._tool_send_email)

        # --- proaktif: hatirlatici + rutinler ---
        self.register("set_reminder", set_reminder)
        self.register("schedule_task", schedule_task)
        self.register("list_reminders", list_reminders)
        self.register("cancel_reminder", cancel_reminder)
        self.register("add_routine", add_routine)
        self.register("list_routines", list_routines)
        self.register("remove_routine", remove_routine)

        # --- hizli araclar ---
        self.register("web_search", web_search)
        self.register("get_weather", get_weather)
        self.register("calculate", calculate)
        self.register("convert_currency", convert_currency)
        self.register("translate", translate)
        self.register("clipboard_get", clipboard_get)
        self.register("clipboard_set", clipboard_set)

        # --- PC guc kullanicisi ---
        self.register("media_control", media_control)
        self.register("spotify_play", self._tool_spotify_play)
        self.register("spotify_control", spotify_control)
        self.register("spotify_now_playing", spotify_now_playing)
        self.register("spotify_queue", spotify_queue)
        self.register("spotify_volume", spotify_volume)
        self.register("spotify_devices", spotify_devices)
        self.register("window_action", window_action)
        self.register("list_processes", list_processes)
        self.register("kill_process", self._tool_kill_process)
        self.register("copy_path", copy_path)
        self.register("rename_path", rename_path)
        self.register("make_folder", make_folder)
        self.register("zip_paths", zip_paths)
        self.register("find_files", find_files)
        self.register("move_path", self._tool_move_path)
        # --- disk bakimi (tarama onaysiz; silme onayli) ---
        self.register("cleanup_scan", cleanup_scan)
        self.register("cleanup_run", self._tool_cleanup_run)
        self.register("empty_recycle_bin", self._tool_empty_recycle_bin)

        # --- vision ---
        self.register("save_screenshot", save_screenshot)
        self.register("ocr_screen", ocr_screen)
        self.register("ocr_image", ocr_image)
        self.register("record_screen", record_screen)

        # --- kod calistirma (onayli) ---
        self.register("run_python", self._tool_run_python)
        self.register("run_shell", self._tool_run_shell)
        self.register("git_command", self._tool_git_command)

        # --- Android ADB (Ultron modulu) ---
        self.register("adb_list_devices", adb_list_devices)
        self.register("adb_connect_wifi", adb_connect_wifi)
        self.register("adb_pair_wifi", adb_pair_wifi)
        self.register("adb_enable_wifi", adb_enable_wifi)
        self.register("adb_disconnect_wifi", adb_disconnect_wifi)
        self.register("adb_set_unlock_pin", adb_set_unlock_pin)
        self.register("adb_unlock_device", adb_unlock_device)
        self.register("adb_open", adb_open)
        self.register("adb_play_media", adb_play_media)
        self.register("adb_shell", adb_shell)

        # --- okul (BOTE Ders Merkezi) koprusu ---
        self.register("okul_status", okul_status)
        self.register("okul_next_exams", okul_next_exams)
        self.register("okul_today_tasks", okul_today_tasks)
        self.register("okul_schedule", okul_schedule)
        self.register("okul_gpa", okul_gpa)
        self.register("okul_search_notes", okul_search_notes)
        self.register("okul_add_task", okul_add_task)
        self.register("okul_add_exam", okul_add_exam)

        # --- GBrain ---
        self.register("kb_write", kb_write)
        self.register("kb_search", kb_search)
        self.register("kb_ask", kb_ask)
        self.register("kb_recent", kb_recent)
        self.register("summarize_document", summarize_document)
        self.register("memory_search", memory_search)

        # --- haberlesme: Gmail (OAuth) + Telegram ---
        self.register("get_unread_emails", get_unread_emails)
        self.register("create_email_draft", create_email_draft)
        self.register("generate_auto_reply_draft", generate_auto_reply_draft)
        self.register("get_latest_telegram_updates", get_latest_telegram_updates)
        self.register("send_telegram_message", self._tool_send_telegram)
        self.register("reply_to_telegram_message", self._tool_reply_telegram)

        # --- ulasim (Izmir) ---
        self.register("eshot_find_stop", eshot_find_stop)
        self.register("eshot_nearby_stops", eshot_nearby_stops)
        self.register("eshot_line_info", eshot_line_info)
        self.register("eshot_approaching_buses", eshot_approaching_buses)
        self.register("plan_route", lambda **kw: self._retracted(plan_route, **kw))
        self.register("izmirim_kart_balance", izmirim_kart_balance)

        # --- telefon uygulamasi (web/phone_link.py) ---
        for fn in (phone_call, send_sms, set_alarm, set_timer, open_phone_app, phone_location,
                   phone_status, ring_phone, send_file_to_phone):
            self.register(fn.__name__, fn)

        # --- MCP gecidi + tarayici ajani ---
        self.register("mcp_servers", mcp_servers)
        self.register("mcp_list_tools", mcp_list_tools)
        self.register("mcp_call", self._tool_mcp_call)
        self.register("browser_task", self._tool_browser_task)
        self.register("browser_open", browser_open)

        # --- icerik paneli: CYRAEN arayuzunun icinde acilir ---
        self.register("show_video", lambda **kw: self._panel(show_video, **kw))
        self.register("show_wikipedia", lambda **kw: self._panel(show_wikipedia, **kw))
        self.register("show_document", lambda **kw: self._panel(show_document, **kw))
        self.register("show_website", lambda **kw: self._panel(show_website, **kw))
        self.register("show_spotify", lambda **kw: self._panel(show_spotify, **kw))
        self.register("show_news", lambda **kw: self._panel(show_news, **kw))
        self.register("show_market", lambda **kw: self._panel(show_market, **kw))
        self.register("show_weather", lambda **kw: self._panel(show_weather, **kw))
        self.register("show_map", lambda **kw: self._panel(show_map, **kw))
        self.register("show_route", lambda **kw: self._panel(show_route, **kw))
        self.register("map_control", lambda **kw: self._panel(map_control, **kw))
        self.register("show_info", lambda **kw: self._panel(show_info, **kw))
        self.register("close_panel", lambda **kw: self._panel(close_panel, **kw))

    # --- onay gerektiren araclar -----------------------------------------
    @staticmethod
    def _window_label(win: dict[str, Any]) -> str:
        return f"{win.get('title') or '(basliksiz pencere)'}\n({win.get('exe') or 'bilinmeyen uygulama'})"

    def _tool_close_application(self, name: str) -> dict[str, Any]:
        target = resolve_close_target(name)
        if not target.get("ok"):
            return {"error": target.get("error", "Hedef cozulemedi.")}
        win = find_close_target(name, exe_for(name))
        if win and is_protected_exe(win.get("exe", "")):
            return {"error": f"'{win.get('title')}' korumali bir pencere, kapatilamaz."}
        siblings = win.get("siblings") or []
        by_exe = bool(win) and win.get("exe") == target["exe"].lower()
        if win and not (by_exe and siblings):
            # tek bir pencere: yalniz onu kapat (ayni uygulamanin baska isleri etkilenmesin)
            prompt = f"Su pencere kapatilacak:\n\n{self._window_label(win)}\n\nOnayliyor musun?"
            if not self._confirm(prompt):
                return {"status": "iptal edildi", "reason": "kullanici onay vermedi"}
            result = close_window(win["hwnd"])
            if "error" not in result:
                self._last_closed = win
                result["window"] = win.get("title", "")
            return result
        if win:
            titles = "\n".join(f"- {t}" for t in [win.get("title", ""), *siblings][:6])
            prompt = (f"'{target['label']}' uygulamasinin TUM pencereleri "
                      f"({len(siblings) + 1}) kapatilacak:\n\n{titles}\n\nOnayliyor musun?")
        else:
            prompt = (f"'{target['label']}' icin acik bir pencere goremiyorum. "
                      f"'{target['exe']}' surecinin tamami kapatilsin mi?")
        if not self._confirm(prompt):
            return {"status": "iptal edildi", "reason": "kullanici onay vermedi"}
        result = _close_app(target)
        if win and "error" not in result:
            self._last_closed = win
        return result

    def _tool_close_active_tab(self) -> dict[str, Any]:
        # onay diyalogu odagi calabilir -> mevcut on plan penceresini simdi yakala
        win = describe_window()
        if not win:
            return {"error": "Odakta bir pencere yok."}
        if is_protected_exe(win.get("exe", "")):
            return {"error": f"Odaktaki pencere ('{win.get('title')}') korumali; sekme kapatilmadi."}
        prompt = f"Su penceredeki aktif sekme kapatilacak:\n\n{self._window_label(win)}\n\nOnayliyor musun?"
        if not self._confirm(prompt):
            return {"status": "iptal edildi", "reason": "kullanici onay vermedi"}
        return close_active_tab(restore_hwnd=win["hwnd"])

    def _tool_press_keys(self, keys: str = "") -> dict[str, Any]:
        if not is_close_combo(keys):
            return press_keys(keys)
        # Kapatma kisayolu o an odakta ne varsa ona gider: hedefi goster, onay al.
        win = describe_window()
        if not win:
            return {"error": "Odakta bir pencere yok; kisayol gonderilmedi."}
        if is_protected_exe(win.get("exe", "")):
            return {"error": (f"Odaktaki pencere ('{win.get('title')}') korumali; '{keys}' "
                              "gonderilmedi. Bir uygulamayi kapatmak icin close_application kullan.")}
        prompt = (f"'{keys}' kisayolu su pencereyi (ya da aktif sekmesini) kapatacak:\n\n"
                  f"{self._window_label(win)}\n\nOnayliyor musun?")
        if not self._confirm(prompt):
            return {"status": "iptal edildi", "reason": "kullanici onay vermedi",
                    "window": win.get("title", "")}
        result = press_keys(keys, hwnd=win["hwnd"])  # onay diyalogu odagi calmis olabilir
        if "error" not in result:
            self._last_closed = win
            result["window"] = win.get("title", "")
        return result

    def _tool_reopen_last_closed(self) -> dict[str, Any]:
        win = self._last_closed
        if not win:
            return {"error": "Bu oturumda kapattigim bir pencere yok."}
        note = "Uygulama yeniden acildi; icindeki oturum/sekme/kaydedilmemis is geri gelmeyebilir."
        if win.get("exe") == "applicationframehost.exe" or not win.get("exe_path"):
            # Magaza uygulamasi: exe yolu ortak kapsayiciyi gosterir -> adiyla ac
            result = self._retracted(open_application, name=win.get("title", ""))
        else:
            result = open_path(win["exe_path"])
        if "error" not in result:
            result = {**result, "window": win.get("title", ""), "note": note}
        return result

    def _retracted(self, fn: Callable[..., Any], **kwargs: Any) -> Any:
        """Ekranla etkilesen bir araci, CYRAEN penceresi gecici olarak cekilmisken calistirir."""
        self._on_typing(True)
        try:
            time.sleep(0.7)  # pencerenin kuculmesini / odagi birakmasini bekle
            return fn(**kwargs)
        finally:
            time.sleep(0.2)
            self._on_typing(False)

    def _tool_type_text(
        self,
        text: str = "",
        app: str | None = None,
        submit: bool = False,
        x: float | None = None,
        y: float | None = None,
    ) -> dict[str, Any]:
        exe_hint = exe_for(app) if app else ""
        return self._retracted(
            type_text,
            text=text,
            app=app,
            submit=bool(submit),
            exe_hint=exe_hint,
            x=x,
            y=y,
        )

    def _tool_look_at_screen(self) -> dict[str, Any]:
        try:
            self._on_look_at_screen()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Ekran gorusu acilamadi: {exc}"}
        return {
            "status": "ekran gorusu acik",
            "note": (
                "Birkac saniye icinde ekran goruntusu gelecek. Bir alana yazman "
                "gerekiyorsa: alani 0-1000 normalize koordinatla belirle -> click_at "
                "ile tikla -> type_text (app olmadan) ile yaz."
            ),
        }

    def _tool_kill_process(self, name: str) -> dict[str, Any]:
        if not self._confirm(f"'{name}' surecini kapatayim mi?"):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return kill_process(name)

    def _tool_cleanup_run(self, categories: str = "", ids: str = "") -> dict[str, Any]:
        plan = plan_cleanup(categories, ids)
        if "error" in plan:
            return plan
        if not plan["cache"] and not plan["files"]:
            return {"status": "temizlenecek bir sey yok"}
        if not self._confirm(describe_plan(plan) + "\n\nDevam edeyim mi?"):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return cleanup_run(categories, ids)

    def _tool_empty_recycle_bin(self) -> dict[str, Any]:
        if not self._confirm("GERI DONUSUM KUTUSU BOSALTILSIN MI?\n\nBu islem GERI ALINAMAZ."):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return empty_recycle_bin()

    def _tool_move_path(
        self, source: str = "", destination: str = "", overwrite: bool = False
    ) -> dict[str, Any]:
        if overwrite and not self._confirm(
            f"'{destination}' uzerine yazilacak (mevcut icerik silinir). Devam edeyim mi?"
        ):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return move_path(source, destination, overwrite=bool(overwrite))

    def _tool_run_python(self, code: str = "") -> dict[str, Any]:
        if not self._confirm(f"Su Python kodunu calistirayim mi?\n\n{code[:800]}"):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return run_python(code)

    def _tool_run_shell(self, command: str = "") -> dict[str, Any]:
        if not self._confirm(f"Su kabuk komutunu calistirayim mi?\n\n{command}"):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return run_shell(command)

    def _tool_git_command(self, subcommand: str = "", repo: str = "") -> dict[str, Any]:
        if git_is_write(subcommand) and not self._confirm(f"git {subcommand} calistirayim mi?"):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return git_command(subcommand, repo)

    def _tool_send_email(
        self, to: str = "", subject: str = "", body: str = "", cc: str = "", in_reply_to: str = ""
    ) -> dict[str, Any]:
        to = (to or "").strip()
        if not to or not body:
            return {"error": "'to' ve 'body' zorunlu."}
        preview = (
            f"E-POSTA GONDERILSIN MI?\n\n"
            f"Kime : {to}{(' | CC: ' + cc) if cc else ''}\n"
            f"Konu : {subject or '(konu yok)'}\n\n"
            f"{body[:600]}{' …' if len(body) > 600 else ''}"
        )
        if not self._confirm(preview):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return send_email(to=to, subject=subject, body=body, cc=cc, in_reply_to=in_reply_to)

    # Sesli komutla yapilan Telegram gonderimleri: onay kapisi + kopru aynasi YOK
    # (sonuc zaten arac yanitiyla modele doner; aynalamak ayni mesaji tekrar okutur).
    def _tool_send_telegram(self, text: str = "", chat_id: str = "") -> dict[str, Any]:
        if not (text or "").strip():
            return {"error": "'text' bos olamaz."}
        target = chat_id or "varsayilan sohbet"
        if not self._confirm(f"TELEGRAM MESAJI GONDERILSIN MI?\n\nKime: {target}\n\n{text[:600]}"):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return send_telegram_message(text=text, chat_id=chat_id, mirror=False)

    def _tool_reply_telegram(
        self, chat_id: str = "", message_id: int = 0, text: str = ""
    ) -> dict[str, Any]:
        if not (text or "").strip():
            return {"error": "'text' bos olamaz."}
        if not self._confirm(f"TELEGRAM YANITI GONDERILSIN MI?\n\nSohbet: {chat_id}\n\n{text[:600]}"):
            return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return reply_to_telegram_message(chat_id=chat_id, message_id=message_id, text=text,
                                         mirror=False)

    def _tool_mcp_call(self, server: str = "", tool: str = "", arguments_json: str = "") -> dict[str, Any]:
        hub = get_hub()
        if (err := hub.ensure_connected(server)) is not None:
            return err
        if hub.needs_confirm(server.strip(), (tool or "").strip()):
            preview = (f"MCP ISLEMI CALISTIRILSIN MI?\n\nSunucu: {server}\nArac : {tool}\n\n"
                       f"{(arguments_json or '{}')[:600]}")
            if not self._confirm(preview):
                return {"status": "iptal edildi", "reason": "kullanici onaylamadi"}
        return hub.call(server, tool, arguments_json)

    @staticmethod
    def _tool_browser_task(goal: str = "", start_url: str = "") -> dict[str, Any]:
        goal = (goal or "").strip()
        if not goal:
            return {"error": "'goal' zorunlu."}
        start_url = (start_url or "").strip()
        task = f"Baslangic adresi: {start_url}\n{goal}" if start_url else goal
        return _dispatch_to_agent("web_operatoru", task)

    # --- icerik paneli ----------------------------------------------------
    def _panel(self, fn: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        """Panel aracini calistirir; dogrulanmis "panel" yukunu arayuze iletir ve modele
        giden yanittan cikarir. Arayuz paneli yoksa icerik varsayilan uygulamada acilir."""
        result = fn(**kwargs)
        if not isinstance(result, dict):
            return result
        payload = result.pop("panel", None)
        if not payload or "error" in result:
            return result
        try:
            shown = bool(self._on_panel(payload))
        except Exception:  # noqa: BLE001 - arayuz hatasi araci cokertemez
            logger.exception("Icerik paneli gosterilemedi")
            shown = False
        # Yalnizca harici karsiligi olan turler tarayiciya/uygulamaya duser; haber, grafik, hava ve
        # bilgi kartinin verisi zaten yanitta: arayuz yoksa model onu sesli aktarir.
        if not shown and payload.get("kind") in ("video", "wiki", "web", "doc"):
            target = payload.get("path") or payload.get("url") or ""
            opened = open_path(target) if payload.get("path") else open_website(target)
            if "error" in opened:
                return {"error": f"Arayuz paneli yok ve harici acilamadi: {opened['error']}"}
            result["status"] = "arayuz paneli yok; varsayilan uygulamada acildi"
        elif not shown:
            result["status"] = "arayuz paneli yok (arayuzsuz mod)"
        return result

    def _tool_spotify_play(self, query: str = "", kind: str = "track", device: str = "") -> dict[str, Any]:
        result = spotify_play(query=query, kind=kind, device=device)
        if isinstance(result, dict) and result.get("ok"):
            try:  # calan sarki arayuzdeki Spotify kartinda gorunsun
                self._on_panel({"kind": "spotify", "title": "Spotify", "subtitle": str(result.get("device") or "")})
            except Exception:  # noqa: BLE001
                logger.exception("Spotify karti gosterilemedi")
        return result

    def _tool_exit_application(self) -> dict[str, Any]:
        if not self._confirm("CYRAEN uygulamasini tamamen kapatayim mi?"):
            return {"status": "iptal edildi", "reason": "kullanici onay vermedi"}
        try:
            self._on_exit()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Kapatilamadi: {exc}"}
        return {"status": "CYRAEN kapatiliyor"}

    def register(self, name: str, fn: ToolFn) -> None:
        self._registry[name] = fn

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._registry)

    async def dispatch(self, call: types.FunctionCall) -> types.FunctionResponse:
        name = call.name or ""
        args: dict[str, Any] = dict(call.args or {})
        fn = self._registry.get(name)

        if fn is None or name in self._disabled:
            return self._response(call, {"error": f"Bilinmeyen arac: {name}"})
        redirect = _phone_app_redirect(name)
        if redirect is not None:
            return self._response(call, redirect)

        started = time.monotonic()
        try:
            if inspect.iscoroutinefunction(fn):
                result = await asyncio.wait_for(fn(**args), timeout=TOOL_TIMEOUT_S)
            else:
                # to_thread'deki is iptal edilemez ama beyin beklemeyi birakir
                result = await asyncio.wait_for(_run_sync(fn, args), timeout=TOOL_TIMEOUT_S)
        except TypeError as exc:
            logger.warning(f"Arac argumani hatasi [{name}]: {exc}")
            return self._response(call, {"error": f"Gecersiz argumanlar: {exc}"})
        except asyncio.TimeoutError:
            logger.bind(event="tool_call", tool=name, ok=False).error(
                f"Arac zaman asimi [{name}] ({TOOL_TIMEOUT_S:.0f} sn)"
            )
            return self._response(call, {"error": f"Arac {TOOL_TIMEOUT_S:.0f} sn icinde yanit vermedi."})
        except Exception as exc:  # noqa: BLE001 - araclar beyni cokertemez
            logger.exception(f"Arac calistirma hatasi [{name}]")
            return self._response(call, {"error": f"{type(exc).__name__}: {exc}"})

        if not isinstance(result, dict):
            result = {"result": result}
        elapsed = int((time.monotonic() - started) * 1000)
        logger.bind(event="tool_call", tool=name, ok="error" not in result, ms=elapsed).debug(
            f"Arac tamamlandi [{name}] ({elapsed} ms) -> {str(result)[:300]}"
        )
        return self._response(call, result)

    @staticmethod
    def _response(call: types.FunctionCall, payload: dict[str, Any]) -> types.FunctionResponse:
        return types.FunctionResponse(id=call.id, name=call.name, response=payload)


async def _run_sync(fn: Callable[..., Any], args: dict[str, Any]) -> Any:
    return await asyncio.to_thread(lambda: fn(**args))
