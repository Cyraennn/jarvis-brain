"""Ajanlara acilan arac setleri (google-genai otomatik fonksiyon cagirma icin
temiz imzali callable'lar).

Yetenek anahtari -> callable listesi. `AgentSpec.capabilities` bu anahtarlari kullanir.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tools.app_launcher import open_application, open_path, open_website
from tools.basic_tools import (
    get_current_datetime,
    get_system_status,
    list_directory,
    read_text_file,
    recall_notes,
    remember_note,
    write_text_file,
)
from tools.email_tools import check_email, read_email, search_email
from tools.gmail_tool import (
    create_email_draft,
    generate_auto_reply_draft,
    get_unread_emails,
    read_gmail,
)
from tools.telegram_tool import get_latest_telegram_updates, send_telegram_message
from tools.transit_tool import (
    eshot_approaching_buses,
    eshot_find_stop,
    eshot_line_info,
    eshot_nearby_stops,
    izmirim_kart_balance,
    plan_route,
)
from tools.keyboard_input import type_in_search, type_text
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
from tools.quick_tools import calculate, convert_currency, get_weather, web_research
from tools.spotify_tool import (
    spotify_control,
    spotify_devices,
    spotify_now_playing,
    spotify_play,
    spotify_queue,
    spotify_volume,
)
from tools.scheduler_tools import (
    add_routine,
    cancel_reminder,
    list_reminders,
    list_routines,
    schedule_task,
    set_reminder,
)
from tools.system_tools import list_processes
from tools.vault_search import memory_search
from tools.browser_tool import BROWSER_TOOLS
from tools.mcp_hub import mcp_call_readonly, mcp_list_tools, mcp_servers
from tools.maintenance import cleanup_scan


# --- ince, temiz imzali sarmalayicilar (model bunlarin semasini gorur) --------

def open_app(name: str) -> dict[str, Any]:
    """Bilgisayarda adiyla bir masaustu uygulamasi acar (orn. chrome, spotify, not defteri)."""
    return open_application(name)


def open_website_url(target: str) -> dict[str, Any]:
    """Varsayilan tarayicida bir web sitesi veya arama sorgusu acar."""
    return open_website(target)


def open_file_or_folder(path: str) -> dict[str, Any]:
    """Bir dosyayi varsayilan uygulamayla ya da bir klasoru dosya gezgininde acar."""
    return open_path(path)


def type_into_app(text: str, app: str = "") -> dict[str, Any]:
    """Bir uygulamaya (Not Defteri, VS Code, Word...) ya da odaktaki pencereye metni harf harf yazar.

    app bos birakilirsa o an odakta olan pencereye yazar.
    """
    return type_text(text, app=app or None)


def search_windows(query: str) -> dict[str, Any]:
    """Windows arama cubugunu acip verilen metni yazar ve ilk sonucu acar."""
    return type_in_search(query, submit=True)


# --- yetenek -> callable listesi ---------------------------------------------

def draft_email(to: str, subject: str, body: str) -> dict[str, Any]:
    """Bir e-posta TASLAGI hazirlar (GONDERMEZ). Gonderme kararini insan/CYRAEN verir."""
    return {
        "status": "taslak hazir",
        "note": "Bu bir taslaktir, gonderilmedi. Gondermek icin CYRAEN'e / kullaniciya ilet.",
        "draft": {"to": to.strip(), "subject": subject, "body": body},
    }


def _kb_write_sync(title: str, content: str, tags: str = "") -> dict[str, Any]:
    """GBrain'e kalici bir not yazar (ajan icin)."""
    import asyncio

    from tools.gbrain_tools import kb_write
    return asyncio.run(kb_write(title, content, tags))


def _kb_search_sync(query: str) -> dict[str, Any]:
    """GBrain'de anlamsal arama yapar (ajan icin)."""
    import asyncio

    from tools.gbrain_tools import kb_search
    return asyncio.run(kb_search(query))


def _adb_run(method: str, *args: Any) -> Any:
    """ADB denetleyicisini ajan thread'inde calistirir.

    Surec geneli tekil denetleyicinin asyncio.Lock'u canli beynin dongusune bagli olabilir;
    bu yuzden ayni ayarlarla KISA OMURLU bir kopya kurulur (PIN dahil, loglanmaz).
    """
    import asyncio

    from tools.adb_tool import ADBController, get_adb_controller

    base = get_adb_controller()
    ctl = ADBController(adb_path=base.adb_path, enabled=base.enabled,
                        tcp_port=base.tcp_port, unlock_pin=base.unlock_pin)
    return asyncio.run(getattr(ctl, method)(*args))


def phone_devices() -> dict[str, Any]:
    """Bilgisayara ADB ile bagli Android telefonlari listeler."""
    devices = _adb_run("get_connected_devices")
    return {"devices": devices, "count": len(devices)}


def phone_unlock() -> dict[str, Any]:
    """Bagli telefonun ekranini uyandirir ve kayitli PIN ile kilidini acar (PIN'i asla yazma)."""
    return _adb_run("unlock_device")


def phone_open(package_or_url: str) -> dict[str, Any]:
    """Telefonda bir uygulamayi (paket adi, orn. com.spotify.music) veya bir URL/deep link'i acar."""
    return _adb_run("open_app_or_url", package_or_url)


def phone_play_media(query_or_url: str) -> dict[str, Any]:
    """Telefonda bir sarki/video arar ve oynatir, ya da verilen medya URL'sini acar."""
    return _adb_run("play_media", query_or_url)


def notify_owner_telegram(text: str) -> dict[str, Any]:
    """Sezai'ye (varsayilan Telegram sohbetine) kisa bir bildirim/ozet mesaji gonderir.
    Ajanlar baska kisilere Telegram mesaji GONDEREMEZ."""
    return send_telegram_message(text=text)


def transit_route(origin: str, destination: str) -> dict[str, Any]:
    """Izmir'de iki nokta arasi toplu tasima icin Google Haritalar linki ve varisa yakin ESHOT duraklari (tarayici acmaz)."""
    return plan_route(origin, destination, open_browser=False)


def izmirim_kart_info() -> dict[str, Any]:
    """Kayitli Izmirim Kart numarasi ve resmi bakiye sorgulama sayfasinin linki (bakiye otomatik okunamaz)."""
    return izmirim_kart_balance(open_browser=False)


def search_web(query: str) -> dict[str, Any]:
    """Internette GUNCEL bilgi arar (Google). Son gelismeler, haberler, guncel tarih/fiyat/surum
    gibi her sey icin MUTLAKA once bunu kullan; kendi bilgin eski olabilir. Detayli ozet + kaynak linkleri doner."""
    return web_research(query)


CAPABILITIES: dict[str, list[Callable[..., Any]]] = {
    "datetime": [get_current_datetime, get_system_status],
    "files": [list_directory, read_text_file, write_text_file],
    "notes": [remember_note, recall_notes],
    "pc_control": [open_app, open_website_url, open_file_or_folder, type_into_app, search_windows],
    "web": [open_website_url],
    "web_search": [search_web],
    "email_read": [check_email, read_email, search_email],
    "email_draft": [check_email, read_email, search_email, draft_email],
    "gbrain": [_kb_write_sync, _kb_search_sync],
    "vault": [memory_search],
    # salt okuma: ajan SILEMEZ (silme sesli CYRAEN + onay kapisinda)
    "maintenance": [cleanup_scan],
    "system": [get_system_status, list_processes],
    "okul": [okul_status, okul_next_exams, okul_today_tasks, okul_schedule, okul_gpa,
             okul_search_notes, okul_add_task, okul_add_exam],
    "quick": [get_weather, calculate, convert_currency],
    "spotify": [spotify_play, spotify_control, spotify_now_playing, spotify_queue, spotify_volume,
                spotify_devices],
    "schedule": [set_reminder, schedule_task, list_reminders, cancel_reminder, add_routine,
                 list_routines],
    "adb": [phone_devices, phone_unlock, phone_open, phone_play_media],
    # Gmail OAuth: okuma + taslak; ajan GONDEREMEZ (gonderim sesli CYRAEN + onay kapisinda)
    "gmail": [get_unread_emails, read_gmail, create_email_draft, generate_auto_reply_draft],
    "telegram": [get_latest_telegram_updates, notify_owner_telegram],
    "transit": [eshot_find_stop, eshot_nearby_stops, eshot_line_info, eshot_approaching_buses,
                transit_route, izmirim_kart_info],
    # MCP: ajan yalnizca onay gerektirmeyen araclari cagirir (yazma sesli CYRAEN + onayda)
    "mcp": [mcp_servers, mcp_list_tools, mcp_call_readonly],
    # odeme/sifre/silme butonlari tarayici katmaninda engellenir
    "browser": BROWSER_TOOLS,
}


def _make_delegate(inbox_path: Path) -> Callable[..., dict[str, Any]]:
    def delegate_task(agent: str, task: str) -> dict[str, Any]:
        """Bir alt gorevi baska bir uzman ajana devreder (orn. arastirmaci, kod_denetcisi, pc_operatoru, not_katibi)."""
        agent = (agent or "auto").strip()
        task = (task or "").strip()
        if not task:
            return {"error": "task zorunlu"}
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "id": uuid.uuid4().hex[:12],
            "agent": agent,
            "task": task,
            "source": "planlayici",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        with inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"status": "devredildi", "agent": agent, "task_id": record["id"]}

    return delegate_task


def build_callables(
    capabilities: list[str],
    *,
    inbox_path: Path | None = None,
) -> list[Callable[..., Any]]:
    """Yetenek anahtarlarindan benzersiz bir callable listesi olusturur."""
    seen: set[str] = set()
    out: list[Callable[..., Any]] = []
    for cap in capabilities:
        if cap == "delegate":
            if inbox_path is not None:
                out.append(_make_delegate(inbox_path))
            continue
        for fn in CAPABILITIES.get(cap, []):
            if fn.__name__ not in seen:
                seen.add(fn.__name__)
                out.append(fn)
    return out


def known_capabilities() -> list[str]:
    return [*CAPABILITIES.keys(), "delegate"]
