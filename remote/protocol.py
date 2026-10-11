"""JARVIS sunucu <-> istemci WebSocket protokolu (tek dogruluk kaynagi).

Hem `server/` hem `client/` bu modulu kullanir; biri degisirse digeri otomatik uyar.

Tum mesajlar JSON metin cercevesidir ve bir "type" alani tasir.

Istemci -> sunucu
  auth             {"type":"auth","token":..,"client":{"name","kind","actions":[..],"confirm":bool}}
                   (baglantidaki ILK mesaj olmali; AUTH_TIMEOUT_S icinde gelmezse baglanti kapanir)
  action_result    {"type":"action_result","id":..,"ok":bool,"result":{..}}
  confirm_response {"type":"confirm_response","id":..,"approved":bool}
  command          {"type":"command","id":..,"text":..}      -> command_result ile yanitlanir
  control          {"type":"control","action":"mic_on|mic_off|away_on|away_off|screen_on|screen_off|webcam_on|webcam_off"}
  frame            {"type":"frame","source":"screen|webcam","jpeg_b64":..}
  ping             {"type":"ping"}

Sunucu -> istemci
  hello            {"type":"hello","client_id":..,"server_version":..}
  event            {"type":"event","kind":..,"data":..,"ts":..}   (motor/ajan/zamanlayici olaylari)
  action_request   {"type":"action_request","id":..,"action":..,"args":{..},"timeout":s}
  confirm_request  {"type":"confirm_request","id":..,"prompt":..,"source":..,"timeout":s}
  confirm_resolved {"type":"confirm_resolved","id":..,"approved":bool}
  stream_control   {"type":"stream_control","screen":bool,"webcam":bool}
  command_result   {"type":"command_result","id":..,"ok":bool,"text":..,"model":..,"error":..}
  error            {"type":"error","error":..}
  pong             {"type":"pong"}

Ses (mikrofon/hoparlor) bu kanalda DEGIL: mevcut `net/audio_server.py` (varsayilan port
8771, 1 byte etiket + PCM16) aynen kullanilir.
"""

from __future__ import annotations

PROTOCOL_VERSION = 1
AUTH_TIMEOUT_S = 10.0
MAX_MESSAGE_BYTES = 8 * 1024 * 1024   # ekran karesi (base64 JPEG) icin yeterli

DEFAULT_ACTION_TIMEOUT_S = 60.0

# ---------------------------------------------------------------------------
# Istemcide (kullanicinin PC'sinde) calismasi gereken fonksiyonlar - IZIN LISTESI.
#
# Anahtar: "<modul>.<fonksiyon>" (fonksiyonun gercek __module__ / __name__ degeri).
# Deger  : saniye cinsinden zaman asimi (None => DEFAULT_ACTION_TIMEOUT_S).
#
# Sunucu bu fonksiyonlari KENDISI calistirmaz; `action_request` ile istemciye yollar.
# Istemci YALNIZCA bu listedeki fonksiyonlari calistirir (sunucu ele gecirilse bile
# istemcide keyfi kod calistirilamaz).
# ---------------------------------------------------------------------------
CLIENT_FUNCTIONS: dict[str, float | None] = {
    # masaustu: uygulama / site / dosya acma
    "tools.app_launcher.open_application": 90,
    "tools.app_launcher.open_website": 90,
    "tools.app_launcher.open_path": None,
    "tools.app_launcher.open_gesture_hud": None,
    # klavye / fare / pencere
    "tools.keyboard_input.type_text": 180,
    "tools.keyboard_input.type_in_search": 120,
    "tools.keyboard_input.type_in_browser": 120,
    "tools.keyboard_input.click_at": None,
    "tools.keyboard_input.drag_select": None,
    "tools.keyboard_input.select_word": None,
    "tools.keyboard_input.select_line": None,
    "tools.keyboard_input.clear_field": None,
    "tools.keyboard_input.erase_chars": None,
    "tools.keyboard_input.move_mouse": None,
    "tools.keyboard_input.scroll": None,
    "tools.keyboard_input.press_keys": None,
    "tools.keyboard_input.close_active_tab": None,
    "tools.keyboard_input.describe_window": None,
    "tools.keyboard_input.find_close_target": None,
    "tools.keyboard_input.close_window": None,
    "tools.keyboard_input.get_foreground_window": None,
    "tools.keyboard_input.media_control": None,
    "tools.keyboard_input.window_action": None,
    "tools.window_control.resolve_close_target": None,
    "tools.window_control.close_application": None,
    # pano, surecler
    "tools.quick_tools.clipboard_get": None,
    # kisisel hafiza: Obsidian kasalari PC'de
    "tools.vault_search.memory_search": 120,
    # disk bakimi (onay sunucuda, is PC'de)
    "tools.maintenance.cleanup_scan": 180,
    "tools.maintenance.plan_cleanup": None,
    "tools.maintenance.cleanup_run": 600,
    "tools.maintenance.empty_recycle_bin": 120,
    "tools.quick_tools.clipboard_set": None,
    "tools.system_tools.list_processes": None,
    "tools.system_tools.kill_process": None,
    # yerel dosyalar
    "tools.basic_tools.list_directory": None,
    "tools.basic_tools.read_text_file": None,
    "tools.basic_tools.write_text_file": None,
    "tools.file_ops.move_path": 120,
    "tools.file_ops.copy_path": 120,
    "tools.file_ops.rename_path": None,
    "tools.file_ops.make_folder": None,
    "tools.file_ops.zip_paths": 300,
    "tools.file_ops.find_files": 120,
    # ekran / goruntu
    "tools.vision_tools.save_screenshot": None,
    "tools.vision_tools.ocr_screen": 120,
    "tools.vision_tools.ocr_image": 120,
    "tools.vision_tools.record_screen": 330,
    # kod calistirma (sunucu ONCE onay alir, sonra istemciye yollar)
    "tools.code_tools.run_python": 120,
    "tools.code_tools.run_shell": 120,
    "tools.code_tools.git_command": 120,
    # Android telefon (ADB) - telefon ev agindaki PC'ye bagli
    "tools.adb_tool.adb_list_devices": None,
    "tools.adb_tool.adb_connect_wifi": None,
    "tools.adb_tool.adb_pair_wifi": 90,
    "tools.adb_tool.adb_enable_wifi": 90,
    "tools.adb_tool.adb_disconnect_wifi": None,
    "tools.adb_tool.adb_set_unlock_pin": None,
    "tools.adb_tool.adb_unlock_device": None,
    "tools.adb_tool.adb_open": None,
    "tools.adb_tool.adb_play_media": None,
    "tools.adb_tool.adb_shell": None,
    # ajan yetenekleri (agents/agent_tools.py) - PC kontrolu + telefon
    "agents.agent_tools.open_app": 90,
    "agents.agent_tools.open_website_url": 90,
    "agents.agent_tools.open_file_or_folder": None,
    "agents.agent_tools.type_into_app": 180,
    "agents.agent_tools.search_windows": 120,
    "agents.agent_tools.phone_devices": None,
    "agents.agent_tools.phone_unlock": None,
    "agents.agent_tools.phone_open": None,
    "agents.agent_tools.phone_play_media": None,
}


def qualified_name(fn: object) -> str:
    return f"{getattr(fn, '__module__', '')}.{getattr(fn, '__name__', '')}"


def action_timeout(action: str) -> float:
    value = CLIENT_FUNCTIONS.get(action)
    return float(value) if value else DEFAULT_ACTION_TIMEOUT_S


def short_name(action: str) -> str:
    """Kullaniciya gosterilecek kisa ad: 'tools.app_launcher.open_application' -> 'open_application'."""
    return action.rsplit(".", 1)[-1]
