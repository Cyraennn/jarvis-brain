"""JARVIS Bilgi Kasasi uretici. Calistir: cd jarvis-brain && python build_vault.py"""
import ast
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path.cwd()                                  # jarvis-brain
sys.path.insert(0, str(ROOT))
VAULT = Path.home() / "Documents" / "JARVIS Bilgi Kasasi"
TODAY = date.today().isoformat()
SECRET_RX = re.compile(r"(KEY|TOKEN|PASSWORD|PASS|PIN|SECRET|CREDENTIAL)", re.I)

written: list[str] = []


def note(rel: str, title: str, body: str, tags: list[str] | None = None) -> None:
    p = VAULT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"title: {title}", f"updated: {TODAY}"]
    if tags:
        fm.append("tags: [" + ", ".join(tags) + "]")
    fm.append("---")
    p.write_text("\n".join(fm) + "\n\n" + body.strip() + "\n", encoding="utf-8", newline="\n")
    written.append(rel)


def esc(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


# =====================================================================  KOD'DAN URETILENLER
def gen_tool_catalog() -> tuple[str, int]:
    import tools.tool_declarations as td

    decls = td.build_declarations()
    cats = {
        "Temel / Sistem": {"get_current_datetime", "get_system_status", "list_directory", "read_text_file",
                           "write_text_file", "remember_note", "recall_notes"},
        "Uygulama ve Web": {"open_application", "open_website", "open_path", "close_application",
                            "open_gesture_hud", "exit_application"},
        "İçerik Paneli (arayüz içi)": {"show_video", "show_wikipedia", "show_document", "show_website",
                                       "show_spotify", "show_news", "show_market", "show_weather", "show_map", "show_route", "map_control",
                                       "show_info", "close_panel"},
        "Klavye ve Fare": {"type_text", "type_in_search", "click_at", "move_mouse", "scroll", "press_keys",
                           "clear_field", "drag_select", "select_word", "select_line", "erase_chars",
                           "close_active_tab", "type_in_browser"},
        "Görüntü ve Ekran": {"look_at_screen", "save_screenshot", "ocr_screen", "ocr_image", "record_screen"},
        "PC Güç ve Dosya": {"media_control", "window_action", "list_processes", "kill_process", "move_path",
                            "copy_path", "rename_path", "make_folder", "zip_paths", "find_files"},
        "Hızlı Araçlar": {"web_search", "get_weather", "calculate", "convert_currency", "translate",
                          "clipboard_get", "clipboard_set"},
        "Kod Çalıştırma": {"run_python", "run_shell", "git_command"},
        "Proaktif (Hatırlatıcı/Rutin)": {"set_reminder", "list_reminders", "cancel_reminder", "add_routine",
                                         "list_routines", "remove_routine"},
        "Ajan Sistemi": {"dispatch_to_agent"},
        "Telefon Uygulaması": {"phone_call", "send_sms", "set_alarm", "set_timer", "open_phone_app",
                               "phone_location", "phone_status", "ring_phone", "send_file_to_phone"},
    }
    prefix_cats = [("adb_", "Android (ADB)"), ("okul_", "Okul (BÖTE Ders Merkezi)"),
                   ("kb_", "GBrain (kalıcı bilgi)"), ("summarize_", "GBrain (kalıcı bilgi)")]
    groups: dict[str, list] = defaultdict(list)
    for d in decls:
        cat = None
        for pre, c in prefix_cats:
            if d.name.startswith(pre):
                cat = c
        if cat is None and "email" in d.name:
            cat = "E-posta"
        if cat is None:
            for c, names in cats.items():
                if d.name in names:
                    cat = c
        groups[cat or "Diğer"].append(d)
    gated = {"close_application", "close_active_tab", "kill_process", "move_path", "run_python", "run_shell",
             "git_command", "send_email", "exit_application"}
    out = [f"JARVIS'in Gemini Live oturumuna tanıttığı **{len(decls)} araç** (kaynak: "
           "`tools/tool_declarations.py`, bu sayfa koddan otomatik üretildi).\n",
           "🔒 = çalışmadan önce kullanıcı onayı ister (bkz. [[Onay Kapıları]]). "
           "Parametrelerde `*` zorunlu olanı gösterir.\n"]
    for cat in sorted(groups, key=lambda c: (c == "Diğer", c)):
        out.append(f"\n## {cat} ({len(groups[cat])})\n")
        out.append("| Araç | Ne yapar | Parametreler |")
        out.append("|---|---|---|")
        for d in groups[cat]:
            props = (d.parameters.properties or {}) if d.parameters else {}
            req = set((d.parameters.required or []) if d.parameters else [])
            params = ", ".join(f"`{k}{'*' if k in req else ''}`" for k in props) or "—"
            lock = " 🔒" if d.name in gated else ""
            out.append(f"| `{d.name}`{lock} | {esc(d.description)} | {params} |")
    return "\n".join(out), len(decls)


def gen_settings() -> str:
    from config.settings import Settings

    src = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
    env_of: dict[str, str] = {}
    for m in re.finditer(r"(\w+)\s*=\s*(?:_env_\w+|os\.getenv)\(\s*\"([A-Z0-9_]+)\"", src):
        env_of[m.group(1)] = m.group(2)
    rows = []
    for name, f in Settings.model_fields.items():
        env = env_of.get(name, "")
        default = f.default if f.default is not None else ""
        if getattr(f, "default_factory", None) is not None:
            try:
                default = f.default_factory()
            except Exception:  # noqa: BLE001
                default = "…"
        d = repr(default) if not isinstance(default, str) else (f"`{default}`" if default else "")
        if SECRET_RX.search(name) or SECRET_RX.search(env):
            d = "(gizli — kasaya yazılmadı)"
        ann = getattr(f.annotation, "__name__", str(f.annotation)).replace("typing.", "")
        rows.append((name, ann, esc(str(d))[:90], env))
    out = [f"`config/settings.py` içindeki **{len(rows)} ayar alanı**. Ortam değişkeni sütunu `.env` ile "
           "geçersiz kılma adıdır. Gizli değerler (anahtar, token, şifre, PIN) bilerek yazılmadı.\n",
           "| Ayar | Tür | Varsayılan | Ortam değişkeni |", "|---|---|---|---|"]
    for name, ann, d, env in sorted(rows):
        out.append(f"| `{name}` | {ann} | {d} | {f'`{env}`' if env else ''} |")
    return "\n".join(out)


def gen_departments() -> dict[str, str]:
    from agents.departments import DEPARTMENTS

    pages = {}
    for key, dep in DEPARTMENTS.items():
        k = getattr(key, "value", str(key))
        out = [f"**{dep.title}** — {dep.description}\n", f"Ajan sayısı: **{len(dep.agents)}**\n",
               "| Ajan | Unvan | Otonomi | Skill | Yetenekler |", "|---|---|---|---|---|"]
        for a in dep.agents:
            aut = getattr(a.autonomy, "value", str(a.autonomy))
            out.append(f"| `{a.name}` | {esc(a.title)} | {aut} | {esc(a.skill or '')} | "
                       f"{esc(', '.join(map(str, a.capabilities or [])))} |")
        out.append("\n### Ajan açıklamaları\n")
        for a in dep.agents:
            out.append(f"- **{a.title}** (`{a.name}`): {a.description}")
        out.append("\nÜst sayfa: [[Ajan Sistemi (FounderOS)]]")
        pages[k] = "\n".join(out)
    return pages


def gen_filemap() -> str:
    skip = {"__pycache__", ".venv", "venv", "build", "dist", "data", "node_modules"}
    rows = []
    for p in sorted(ROOT.rglob("*.py")):
        if any(part in skip for part in p.relative_to(ROOT).parts) or p.name == "build_vault.py":
            continue
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        try:
            doc = (ast.get_docstring(ast.parse(text)) or "").strip().splitlines()
            first = doc[0] if doc else ""
        except SyntaxError:
            first = ""
        rows.append((rel, len(text.splitlines()), first))
    out = [f"`jarvis-brain/` altında **{len(rows)} Python dosyası**, toplam "
           f"**{sum(r[1] for r in rows):,} satır**.\n", "| Dosya | Satır | İlk docstring satırı |", "|---|---:|---|"]
    for rel, n, first in rows:
        out.append(f"| `{rel}` | {n} | {esc(first)[:110]} |")
    return "\n".join(out)


def gen_tests() -> str:
    rows = []
    for p in sorted((ROOT / "tests").glob("test_*.py")) + sorted((ROOT / "scripts").glob("test_*.py")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        n = len(re.findall(r"^\s*(?:async )?def test_", text, re.M))
        doc = ast.get_docstring(ast.parse(text)) or ""
        rows.append((p.relative_to(ROOT).as_posix(), n, doc.strip().splitlines()[0] if doc.strip() else ""))
    out = ["| Dosya | Test sayısı (fonksiyon) | Ne test eder |", "|---|---:|---|"]
    out += [f"| `{r[0]}` | {r[1]} | {esc(r[2])} |" for r in rows]
    return "\n".join(out)


# =====================================================================  URETIM
tool_md, tool_count = gen_tool_catalog()
settings_md = gen_settings()
dept_pages = gen_departments()
filemap_md = gen_filemap()
tests_md = gen_tests()
sys_prompt = (ROOT / "prompts" / "system_prompt.txt").read_text(encoding="utf-8")
web_doc = ast.get_docstring(ast.parse((ROOT / "web" / "console_server.py").read_text(encoding="utf-8"))) or ""

VAULT.mkdir(parents=True, exist_ok=True)
(VAULT / ".obsidian").mkdir(exist_ok=True)
(VAULT / ".obsidian" / "app.json").write_text('{\n  "showFrontmatter": true,\n  "defaultViewMode": "preview"\n}\n', encoding="utf-8")

# ---------------------------------------------------------------- GENEL
from agents.departments import all_agents  # noqa: E402

agent_count = len(all_agents())

note("_Index.md", "JARVIS Bilgi Kasası — Ana Sayfa", f"""
Bu kasa JARVIS'e ait **bütün bilgiyi** tek yerde toplar: mimari, araçlar, entegrasyonlar, yapılandırma, güvenlik,
testler, karar günlüğü ve açık sorunlar. Büyük kısmı doğrudan koddan üretildi ({TODAY}), yani kodla birebir uyumlu.

> Not: Canlı JARVIS'in kendi otomatik konuşma/not kayıtları ayrı kasada: `C:\\Users\\KULLANICI\\Documents\\JARVIS Hafiza`.
> Bu kasa **dokümantasyon/inceleme** içindir; JARVIS buraya otomatik yazmaz. Bkz. [[Obsidian Kasaları]].

## Buradan başla
- [[Genel Bakış]] — JARVIS nedir, neyden oluşur
- [[Nasıl Çalıştırılır]] — kurulum ve çalıştırma
- [[Sorunlar ve Yapılacaklar]] — açık işler, riskler (**önce bunu incele**)
- [[2026-10-12 Ekim Güncellemeleri]] — en son yapılan büyük değişiklikler

## Mimari
[[Canlı Beyin Motoru]] · [[Ajan Sistemi (FounderOS)]] · [[Masaüstü Arayüzü (HUD)]] · [[Web Konsolu ve PWA]] ·
[[Köprü (Bridge)]] · [[Proaktif Sistem]] · [[GBrain Kalıcı Hafıza]] · [[Modeller ve Anahtarlar]]

## Departmanlar (6) ve {agent_count} ajan
{' · '.join(f'[[Departman - {k}]]' for k in dept_pages)}

## Araçlar
[[Araç Kataloğu]] · [[Onay Kapıları]] · [[Klavye ve Fare Kontrolü]] · [[Uygulama Açma]]

## Entegrasyonlar
[[WhatsApp Kolu]] · [[Android ADB]] · [[E-posta]] · [[Okul Köprüsü]] · [[Android İstemcisi]] ·
[[Obsidian Kasaları]] · [[OpenRouter]]

## Yapılandırma
[[Ayarlar ve Ortam Değişkenleri]] · [[Sistem Prompt'u]] · [[WhatsApp Yapılandırması]] · [[Dosya Haritası]]

## Güvenlik ve Test
[[Güvenlik Modeli]] · [[Gizli Değerler]] · [[Testler]]

## Günlük
[[2026-09-02 İlk Kurulum]] · [[2026-09-03 Genişleme]] · [[2026-09-20 İyileştirme Turu]] ·
[[2026-10-12 Ekim Güncellemeleri]]

## İlgili projeler
[[OPTIMAL ENGINE (Next.js)]]
""", ["indeks"])

note("00 Genel/Genel Bakış.md", "Genel Bakış", f"""
**JARVIS**, Sezai için çalışan Türkçe konuşan, sesli bir yapay zeka asistanıdır. Windows masaüstünde çalışır;
mikrofonu dinler, webcam ve ekranı görebilir, klavye/fare ile bilgisayarı kullanabilir, telefonu (ADB) ve WhatsApp'ı
yönetebilir, 6 departmanlık bir ajan ekibine iş dağıtabilir.

## Bileşenler
| Bileşen | Ne | Detay |
|---|---|---|
| Canlı beyin | Gemini Live (ses ↔ ses), tek `asyncio.TaskGroup` | [[Canlı Beyin Motoru]] |
| Araçlar | {tool_count} Function Declaration | [[Araç Kataloğu]] |
| Ajan sistemi | Conductor + 6 kişisel asistan departmanı + 27 ajan | [[Ajan Sistemi (FounderOS)]] |
| Masaüstü arayüzü | PySide6 HUD (Iron Man teması) | [[Masaüstü Arayüzü (HUD)]] |
| Web konsolu | Telefondan kontrol, PWA, SSE | [[Web Konsolu ve PWA]] |
| Köprü | `bridge/inbox.txt` / `outbox.txt` | [[Köprü (Bridge)]] |
| Proaktif | Hatırlatıcı + rutin | [[Proaktif Sistem]] |
| Kalıcı bilgi | GBrain (embedding araması) | [[GBrain Kalıcı Hafıza]] |
| WhatsApp | Playwright ile WhatsApp Web botu | [[WhatsApp Kolu]] |
| Android | ADB kontrolü | [[Android ADB]] |

## Teknoloji
- Python **3.11+** (TaskGroup/ExceptionGroup şart), Python 3.12.10 ile geliştirildi
- `google-genai` (Live v1alpha), PyAudio (16 kHz giriş / 24 kHz çıkış), opencv-python, `mss`, pydantic, loguru
- PySide6-Essentials (arayüz), Playwright (WhatsApp), `openai` SDK (OpenRouter için), stdlib `http.server` (web konsolu)
- Windows'a özel: ctypes `SendInput`, `SetWindowDisplayAffinity`, EnumWindows

## Konum
- Kod: `C:\\Users\\KULLANICI\\OneDrive\\Masaüstü\\Masaüstü\\multi\\jarvis-brain`
- Aynı klasörün kökünde ayrı bir Next.js projesi vardır: [[OPTIMAL ENGINE (Next.js)]]
- Çalışma verisi: `jarvis-brain/data/` (git'te yok)

Ayrıntılı dosya listesi: [[Dosya Haritası]].
""", ["genel"])

note("00 Genel/Nasıl Çalıştırılır.md", "Nasıl Çalıştırılır", """
## Kurulum
```bash
cd jarvis-brain
python -m venv .venv && .venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env      # GEMINI_API_KEY vb. doldur
```
Opsiyonel: `pip install keyring` (PIN'i Windows Credential Manager'da tutar), `playwright install chromium` (WhatsApp).

## Çalıştırma
| Komut | Ne yapar |
|---|---|
| `python run_ui.py` | **Önerilen.** Masaüstü HUD + sesli beyin + ajan orkestratörü + web konsolu |
| `python main.py` | Sessiz mod (arayüzsüz) — beyin + WhatsApp kolu aynı TaskGroup'ta |
| `python run_agents.py` | Yalnızca ajan orkestratörü |
| `scripts/launch_jarvis.vbs` | Konsolsuz başlatıcı (masaüstü kısayolu bunu çağırır) |
| `build_windows.bat` | PyInstaller ile `dist/JARVIS/JARVIS.exe` |

> ⚠️ **`run_agents.py` ile `run_ui.py`'yi aynı anda çalıştırma.** İkisi de `bridge/inbox.txt`'i işler → görevler çift çalışır.

## Test
```bash
cd jarvis-brain
python -m pytest tests -q                       # birim/simülasyon
$env:JARVIS_LIVE_TESTS=1; python -m pytest tests/test_keyboard_live.py   # canlı klavye testi (kendi Tk penceresine yazar)
```
Ayrıntı: [[Testler]].

## Ses düşerse
`-9999 Unanticipated host error` genelde Windows Ayarlar > Mikrofon sayfası açıkken cihazı tuttuğu için olur; sayfayı
kapat. Ses açılamazsa JARVIS **çökmez**: oturum, ekran, araçlar ve ajanlar çalışır, mikrofon düğmesi yeniden dener.

## WhatsApp botunu başlatma
Bkz. [[WhatsApp Kolu]] (kalıcı `enabled` kapalı; geçici açmak için `JARVIS_WHATSAPP_ENABLED=1`).
""", ["genel"])

note("00 Genel/Dosya Haritası.md", "Dosya Haritası", filemap_md + "\n\nÜst: [[Genel Bakış]]", ["referans", "otomatik"])

# ---------------------------------------------------------------- MIMARI
note("01 Mimari/Canlı Beyin Motoru.md", "Canlı Beyin Motoru", """
`core/brain_engine.py` — `BrainEngine`. Gemini Live WebSocket oturumunu (`client.aio.live.connect`, v1alpha,
model `models/gemini-2.5-flash-native-audio-latest`) yönetir. Tek bir `asyncio.TaskGroup` içinde **7 eşzamanlı görev**:

| Görev | İş |
|---|---|
| `_send_realtime` | Mikrofon/kamera/ekran karelerini modele gönderir |
| `_listen_audio` | Mikrofonu okur (model konuşurken **eko engelleme**) |
| `_receive_audio` | Modelden ses/transkript/araç çağrısı alır |
| `_play_audio` | Hoparlöre çalar |
| `_stream_webcam_frames` | ~1.5 sn'de bir JPEG kare |
| `_stream_screen_frames` | ~1.2 sn'de bir ekran karesi (`mss`) |
| `_watch_bridge_inbox` | `bridge/outbox.txt`'i tail eder, oturuma enjekte eder ([[Köprü (Bridge)]]) |

## Dayanıklılık
- Exponential-backoff **yeniden bağlanma**.
- `_open_audio_streams` 6 deneme × 2 sn (Windows `-9999` geçici hatası için).
- Ses açılamazsa **graceful degrade**: `_audio_ok=False`, `on_connection("no-audio")`; `retry_audio()` ile mikrofon düğmesinden yeniden denenir.
- Çalışma zamanı kontrolleri: `set_mic_muted`, `set_output_muted`, `set_webcam_streaming`, `set_screen_streaming`, `inject_bridge_message`.

## Araç çağırma
Model Function Declaration ile araç çağırır → `tools/tool_runner.py::ToolRunner` `asyncio.to_thread` içinde çalıştırır
(event loop bloklanmaz). Bkz. [[Araç Kataloğu]], [[Onay Kapıları]].

## Gözlemci (Observer)
`core/events.py::EngineObserver` arayüzü: `on_connection`, `on_transcript`, `on_external_typing`, `confirm(prompt)`,
`on_exit_request`… Arayüz (`ui/qt_observer.py`) bunu Qt sinyallerine çevirir; başsız modda varsayılan `confirm → True`.

## Ekran görüşü ve yakalama dışı bırakma
JARVIS penceresi `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` ile **ekran yakalamada görünmez** — model pencerenin
arkasını görür, sen pencereyi görürsün. Ekranla etkileşen araçlar çalışırken pencere geçici çekilir (bkz. [[Klavye ve Fare Kontrolü]]).

## Sistem prompt'u
[[Sistem Prompt'u]] (`prompts/system_prompt.txt`).
""", ["mimari"])

dep_links = "\n".join(f"- [[Departman - {k}]]" for k in dept_pages)
note("01 Mimari/Ajan Sistemi (FounderOS).md", "Ajan Sistemi (FounderOS)", f"""
JARVIS = **Conductor**. Kullanıcı ya da telefon bir görev verir; Conductor görevi departmanlara yönlendirir.

## Akış
1. Görev `bridge/inbox.txt`'ten (ya da `dispatch_to_agent` aracı / `/api/task` ile) gelir — `agents/orchestrator.py::AgentOrchestrator`.
2. `agents/conductor.py::Conductor.route` (Gemini, JSON çıktı) görevi **6 departman (okul, iletişim, sistem, telefon, bilgi, günlük) / {agent_count} ajana** delege eder.
3. **Otonomi kapısı:**
   - `fully_autonomous` → doğrudan çalışır
   - `human_assisted` → `observer.confirm` diyaloğu (ya da `agents_auto_approve_assisted`)
   - `human_led` → **bloklanır**
4. `agents/agent.py::Agent` çalışır (skill + elle araç döngüsü; `genai_util.generate_with_retry` ile model rotasyonu).
5. Sonuç `bridge/outbox.txt` + Supabase günlüğü + ntfy bildirimi; sesli beyin sonucu okur.

## Departmanlar
{dep_links}

## Skill
`agents/skills/markdown_auditor.py` — deterministik Markdown denetçisi (başlık atlaması, kırık bağ/görsel, alt-metin,
karışık liste, çıplak URL, TODO). `AgentSpec.skill` verilince ajan önce skill'i çalıştırır, JSON raporu LLM'e özetletir.

## Entegrasyon iskeleti (`agents/integrations/`)
`supabase_sync`, `ntfy`, `notifier` (ntfy + web SSE yayını), `email_client`. Anahtar yoksa `data/task_logs.jsonl` / log'a düşer.

## Dosyalar
`agents/{{orchestrator,conductor,agent,agent_tools,registry,schemas,events,genai_util}}.py`,
`agents/departments/*.py`, `agents/agents.example.json`.

Model seçimi ve rotasyonu: [[Modeller ve Anahtarlar]].
""", ["mimari", "ajan"])

for k, body in dept_pages.items():
    note(f"01 Mimari/Departmanlar/Departman - {k}.md", f"Departman - {k}", body, ["departman"])

note("01 Mimari/Masaüstü Arayüzü (HUD).md", "Masaüstü Arayüzü (HUD)", """
`python run_ui.py` — PySide6 (Essentials + Addons). Varsayılan arayüz **Komuta HUD**'dur (`ui/hud/hud_window.py::HudWindow`,
`MainWindow`'dan türer); eski panel yerleşimi `JARVIS_UI_STYLE=classic` ile açılır. Palet `ui/theme.py`: koyu lacivert zemin,
mint `ACCENT` (#44d7b5), altın `GOLD` (konuşma/uyarı), menekşe `MYSTIC`; kartlar üstten ışık alır, altlarına gölge düşer.

## Yerleşim (Komuta HUD)
- **Üst çubuk:** logo + metin chip düğmeler (odak, mikrofon, kamera, ekran, tam ekran, üstte, tepsi, kapat).
- **Sol sütun** (`ui/hud/stat_cards.py`): saat + mini takvim + hava (`ClockCard`, `MiniCalendar`), okul (`OkulCard`),
  sistem ölçerleri (`SystemCard`: CPU/RAM/disk), ajanlar.
- **Merkez:** `ui/hud/command_graph.py::CommandGraph(BrainGraph)` — sese tepki veren parçacık küresi (JARVIS), iç yörüngede
  6 departman, dış yörüngede tüm ajanlar. Yörünge izleyiciye yatıktır ve yavaşça döner (öndekiler büyük/parlak, arkadakiler
  küçük/soluk); fareyle sürükleyince elle döner. Durum/animasyon mantığı `BrainGraph`'tan gelir.
- **Sağ sütun:** canlı görüş (tıkla büyüt), görev akışı, hızlı komutlar (`QuickCommandsCard`), rutinler (`RoutinesCard`), günlük.
- **Alt:** `>_` komut satırı + kayan durum satırı.
- Eski zırh büstü `ui/hud/suit_core.py::SuitCore` **silindi** (2026-10-12).

## İçerik paneli
Video, Wikipedia, web sitesi, belge, Spotify kartı, haberler, fiyat grafiği, hava durumu ve bilgi kartı ayrı pencerede değil
merkezdeki grafın **yerinde** açılır (`ui/widgets/content_panel.py::ContentPanel`).
- Araçlar (`tools/panel_tools.py`): `show_video`, `show_wikipedia`, `show_document`, `show_website`, `show_spotify`,
  `show_news`, `show_market`, `show_weather`, `show_map`, `show_route`, `map_control`, `show_info`, `close_panel`.
- Model kimlik, adres ya da dosya yolu **uyduramaz**: yalnız sorgu/ad verir; video kimliğini, sayfa başlığını ve dosya yolunu
  araç bulur ve doğrular. Doğrulanamayan istek `{"error": ...}` döner, panel açılmaz. Tek istisna `show_info` (gövdeyi model yazar).
- Akış: araç sonucu `"panel"` yükü taşır → `ToolRunner._panel` yükü modele giden yanıttan çıkarır →
  `EngineObserver.on_panel(payload) -> bool` → `QtEngineObserver.panel` sinyali → `ContentPanel.show_content`.
- Arayüz yoksa (sessiz mod / web gözlemcisi `False` döner) video, wiki, site ve belge varsayılan uygulamada açılır; haber,
  grafik, hava ve bilgi kartının verisi zaten yanıtta olduğundan model sesli aktarır.
- Web içeriği QtWebEngine ister (`ui/widgets/panel_web.py`, **PySide6-Addons**, tembel içe aktarılır; yoksa sistem tarayıcısı).
  Haber, grafik, hava ve bilgi kartı saf Qt'dir (`ui/widgets/panel_views.py`).
- Kaynaklar anahtarsız: YouTube oEmbed, Wikipedia REST, Google Haberler RSS, Yahoo Finance.
- Belgeler: yalnız `.pdf` / `.txt` / `.md`, en çok 50 MB, izinli kökler `JARVIS_DOCS_DIRS` (boş = Belgeler + Masaüstü + İndirilenler).
- Web konsoluna yalnız tür + başlık gider (dosya yolu LAN'a açık veri yoluna yazılmaz).

## Klasik yerleşim (`JARVIS_UI_STYLE=classic`)
sol ikon şeridi · **sol panel** (`agent_panel.py`: departman ağacı + SOP/rozet detay kartı + görev akışı) · **merkez**
(`brain_graph.py`: JARVIS → 6 departman altıgeni → tıklayınca alt ajanlar yelpazesi) + konuşma transkripti + köprü/komut
girişi · **sağ panel** (webcam + ekran görüşü + sistem günlüğü) · durum çubuğu.

## Masaüstü uygulaması davranışı
- Her zaman üstte pencere + `QSystemTrayIcon` (Göster/Gizle, Her zaman üstte, Windows ile başlat `HKCU\\...\\Run`, Çıkış).
- Kapatınca **tepsiye küçülür** (`setQuitOnLastWindowClosed(False)`). Açılışta `assets/applause.wav` çalar.
- `exit_application` aracı = kendini kapatma (onaya tabi).
- Motor ayrı thread + asyncio döngüsünde (`engine_worker.py`); `qt_observer.py` olayları Qt sinyallerine çevirir.
- Dış yazma sırasında (`on_external_typing`) pencere `showMinimized()` olur (klavye odağını da bırakır), bitince `showNormal()`.

Bileşenler: `ui/{app,main_window,engine_worker,orchestrator_worker,scheduler_worker,web_worker,qt_observer,sound,theme}.py`,
`ui/widgets/{webcam_view,transcript_view,log_view,agent_panel,brain_graph,content_panel,panel_views,panel_web}.py`,
`ui/hud/{hud_window,command_graph,stat_cards,hud_card,backdrop,boot,fonts}.py`, `ui/strings.py` (doğru Türkçe metinler, `tr_upper/tr_lower`).

## Performans (2026-09-20, Aşama 1)
- `WebcamView`: aynı kare tekrar gelirse decode/ölçekleme yok, ölçeklenmiş kare önbellekte, gizliyken zamanlayıcı durur.
- `TranscriptView`: en fazla 400 parça (aşılınca toplu silinir), kullanıcı yukarıdaysa zorla kaydırmaz.
- `LogView`: 100 ms'de bir toplu ekleme, 2000 satır sınırı, yukarıdaysa kaydırmaz.
- `BrainGraph`: statik katman (ızgara/halkalar) `QPixmap` önbelleğinde, renkler önceden hazır, animasyon gerçek zamana (dt) bağlı, meşgulken ~30 / boştayken ~15 FPS, gizli/küçültülünce durur.
- Ölçüm (offscreen, 6 departman): kare başına 17,9 → 15,4 ms; boşta tahmini CPU ≈ %54 → %23 (tek çekirdek).
- Ölü kod `HudOrb` silindi. Durum çubuğu: gerçek model adı, `GÖREV aktif/toplam`, ribbon beyin düğmesi = **odak modu** (yan panelleri gizle/göster), sahte sekme kaldırıldı.
- Bulunan hata: Python `lower()` `BAĞLI`→`bağli` yapıyordu → `tr_lower`.
- Test: `tests/ui/` (offscreen), `scripts/ui_snapshot.py` (PNG). Plan: `C:\\Users\\KULLANICI\\.claude\\plans\\aray-z-biraz-g-ncelleyelim-snug-moon.md` (Aşama 2-4 bekliyor).
""", ["mimari", "arayüz"])

note("01 Mimari/Web Konsolu ve PWA.md", "Web Konsolu ve PWA", f"""
`web/console_server.py` — stdlib `http.server` (`ThreadingHTTPServer`). Telefondan `http://<pc-lan-ip>:8770?key=<token>` ile açılır.

```
{web_doc}
```

## Özellikler
- Mobil Iron Man sayfası, Web Speech API ile sesli komut, **SSE** canlı akış (`web/event_bus.py::BUS`).
- **Telefon görüşmesi modu:** sürekli `SpeechRecognition` + `SpeechSynthesis` (tr-TR), konuşurken mikrofon durur (eko), `wakeLock`.
- **Uzak mod:** PC hoparlörü susar ama `_play_audio` konuşma süresi kadar bekler; transkript telefona akmaya devam eder.
- **PWA:** `/manifest.webmanifest` (start_url'de token), `/sw.js`, `/icon-*.png`. Tam yükleme istemi HTTPS ister (ngrok/tailscale); düz LAN'da iOS "Ana ekrana ekle" çalışır.
- `/hud`: el-jesti kontrollü 3D HUD (webcam + MediaPipe, tarayıcıda).

## Güvenlik (2026-09-20'de sertleştirildi)
- Token karşılaştırması `hmac.compare_digest`; token `?key=` (SSE/PWA için) **veya** `X-Jarvis-Key` başlığı.
- **CORS `*` kaldırıldı** → izin listesi: varsayılan `localhost:8000/8770`, ek için `JARVIS_WEB_CORS_ORIGINS`.
- **Token yoksa LAN'a açılmaz**, yalnızca `127.0.0.1`.
- Kalan risk: token URL'de (tarayıcı geçmişi/log) ve düz HTTP. Bkz. [[Güvenlik Modeli]].
- Test: `tests/test_console_server.py`.
""", ["mimari", "web"])

note("01 Mimari/Köprü (Bridge).md", "Köprü (Bridge)", """
Dosya tabanlı, basit iletişim hattı (`bridge/`, git'te yok):
- `bridge/outbox.txt` → **canlı beyne** enjekte edilir (`_watch_bridge_inbox` tail eder). `[` ile başlayan satırlar ön ek olmadan enjekte edilir.
- `bridge/inbox.txt` → **ajan orkestratörüne** görev kuyruğu.

Yazanlar: telefon (`/api/say`, `/api/task`), hatırlatıcılar (`[HATIRLATICI]`), WhatsApp aynası (`[WHATSAPP] ...`), harici ajanlar.
Konuşma günlüğü için etiketler: `[TELEFON]→telefon`, `[HATIRLATICI]→hatırlatıcı`, `[TELEFON BİLDİRİMİ]→atlanır`.

> WhatsApp'a gelen/giden **her mesaj** buraya `[WHATSAPP] ...` olarak yazılır — canlı beyin duyar. Bkz. [[WhatsApp Kolu]].
""", ["mimari"])

note("01 Mimari/Proaktif Sistem.md", "Proaktif Sistem", """
`core/scheduler.py` + `ui/scheduler_worker.py` — dosya tabanlı `data/reminders.json` ve `data/routines.json`.
- `parse_when`: Türkçe doğal dil ("yarın 9'da", "2 saat sonra"...).
- Vade gelince → `bridge/outbox.txt` + Notifier (ntfy + web SSE).
- Hazır rutin: **"Günlük Brifing"**.
- Araçlar: `set_reminder`, `list_reminders`, `cancel_reminder`, `add_routine`, `list_routines`, `remove_routine` ([[Araç Kataloğu]]).
""", ["mimari"])

note("01 Mimari/GBrain Kalıcı Hafıza.md", "GBrain Kalıcı Hafıza", """
`agents/gbrain/store.py` — `data/gbrain/notes.jsonl` + Gemini embeddings (`text-embedding-004`) + kosinüs benzerliği;
embedding başarısızsa kelime eşleşmesi yedeği.

- Araçlar: `kb_write`, `kb_search`, `kb_ask`, `kb_recent`, `summarize_document` (txt/md/kod; pdf → pypdf).
- Her kayıt aynı zamanda `<vault>/GBrain/<slug>.md` **Markdown aynası** olarak yazılır ([[Obsidian Kasaları]]).
- `bilgi_bankasi` ajanı `gbrain` yeteneğini kullanır.
""", ["mimari", "hafıza"])

note("01 Mimari/Modeller ve Anahtarlar.md", "Modeller ve Anahtarlar", f"""
| Amaç | Model / sağlayıcı | Not |
|---|---|---|
| Canlı ses beyni | `models/gemini-2.5-flash-native-audio-latest` (Live, v1alpha) | Ayrı kota; sorunsuz çalıştı |
| Ajanlar / yönlendirme | `agents_model` zinciri: `gemini-flash-lite-latest` → `gemini-3.5-flash-lite` → `gemini-3.5-flash` → `gemini-3.6-flash` | `settings.agent_model_chain` |
| WhatsApp yanıtı | **OpenRouter** `nvidia/nemotron-3-super-120b-a12b:free` → Gemma 4 31B → Qwen 3.8 27B → **Gemini yedeği** | [[OpenRouter]] |
| Embedding | `text-embedding-004` | [[GBrain Kalıcı Hafıza]] |
| OCR / vision | Gemini multimodal (Tesseract yok) | `tools/vision_tools.py` |

## Model rotasyonu ve retry (`agents/genai_util.py::generate_with_retry`)
Model listesi sırayla denenir; her model için üstel geri çekilmeli yeniden deneme (varsayılan 3 deneme, 6→45 sn). 429/503 geçici hata;
404 model kapalı. Zincirdeki tüm modeller başarısızsa son hata fırlatılır.

## Gerçekler (2026-09 itibarıyla)
- `gemini-2.5-*` (Live ses modeli hariç) yeni anahtarlara **404** — zincirden çıkarıldı (2026-09-20).
- Ücretsiz kotada `gemini-3.6-flash` ≈ günde 20 istek. **2026-09-20'de tüm zincir 429 (RESOURCE_EXHAUSTED)** idi.
- `AQ.` önekli **ephemeral token** da `generate_content` için çalışır (~30 dk ömür); kalıcı kullanım için AI Studio'dan `AIza…` anahtarı gerekir.

## Anahtarlar nerede?
`jarvis-brain/.env` (**gitignore'da**). Değerler bu kasaya bilerek yazılmadı: bkz. [[Gizli Değerler]].
""", ["mimari", "model"])

# ---------------------------------------------------------------- ARACLAR
note("02 Araçlar/Araç Kataloğu.md", "Araç Kataloğu", tool_md + "\n\nİlgili: [[Onay Kapıları]] · [[Klavye ve Fare Kontrolü]] · [[Uygulama Açma]]",
     ["araç", "otomatik"])

note("02 Araçlar/Onay Kapıları.md", "Onay Kapıları", """
`ToolRunner._confirm(prompt) -> bool` → `EngineObserver.confirm`. Arayüzde `QtEngineObserver.confirm` bir `ConfirmRequest`
(threading.Event) + `confirm_requested` sinyali üretir; MainWindow'da **modal QMessageBox** açılır, motor thread'i bloklanır.
Başsız modda varsayılan `True` (onay yok!).

## Onay isteyen araçlar
| Araç | Onay metni |
|---|---|
| `close_application` | "'X' uygulamasını kapatayım mı?" (nazik kapatma: `taskkill /IM`, `/F` **yok**; `_PROTECTED` liste asla: explorer/system/svchost…) |
| `close_active_tab` | "Odaktaki sekmeyi kapatayım mı?" |
| `kill_process` | "'X' sürecini kapatayım mı?" |
| `move_path` (üzerine yazma) | Üzerine yazılacaksa |
| `run_python`, `run_shell` | Kodu/komutu gösterir (`code_exec_enabled` varsayılan **false**) |
| `git_command` (yazan alt komutlar) | "git X çalıştırayım mı?" |
| `send_email` | Taslağı sesli okur, sonra pencere |
| `exit_application` | "JARVIS'i tamamen kapatayım mı?" |

Ayar: `confirm_before_close` / `JARVIS_CONFIRM_CLOSE`.

## Onay İSTEMEYEN ama riskli araçlar
`type_text`, `click_at`, `press_keys`, `clear_field`, `drag_select`, `adb_*` (PIN ile kilit açma dahil). Sesli kullanımı bozmamak için
bilerek onaysız; bunun yerine [[Klavye ve Fare Kontrolü]] içindeki odak korumaları var. Bkz. [[Güvenlik Modeli]].
""", ["araç", "güvenlik"])

note("02 Araçlar/Klavye ve Fare Kontrolü.md", "Klavye ve Fare Kontrolü", """
`tools/keyboard_input.py` — ctypes `SendInput` (bağımlılıksız, **Windows'a özel**).

## Ne yapar
- `type_text(text, app=, submit=, x=, y=)`: harf harf yazar. `x,y` (**0-1000 normalize**, Gemini pointing convention) verilirse önce oraya tıklar (en güvenilir yol).
  `app=` verilirse `find_window` (EnumWindows + exe/başlık eşleme) ile pencereyi bulur, öne getirir, istemci alanına tıklar.
- `click_at`, `move_mouse`, `scroll`, `press_keys('ctrl+s')`, `clear_field`, `drag_select`, `select_word`, `select_line`, `erase_chars`.
- `search_and_open` / `type_in_search`: Win+S → yaz → Enter. `type_in_browser`: tarayıcı adres çubuğuna yazar.
- `window_action`, `media_control`, `focus_window`, `close_active_tab`, `close_search`.

## 2026-09-20 düzeltmeleri (kök nedenler)
1. **`about:blank` hatası:** `type_in_browser` `webbrowser.open_new_tab("about:blank")` kullanıyordu. Windows'ta `about:` kayıtlı protokol değil →
   **"Birlikte aç" (`openwith.exe`) penceresi** açılıyor, `Ctrl+L` + metin + Enter o pencereye yazılıyordu. Artık gerçek `https://www.google.com/` açılır
   ve tarayıcı exe'si (`BROWSER_EXES`) öne gelmeden yazılmaz. *(Kullanıcının varsayılan tarayıcısı Opera GX → `opera.exe`.)*
2. **Geri çekme eksikti:** `open_application`, `open_website`, `type_in_search` `ToolRunner._retracted` ile sarılı değildi → JARVIS penceresi
   odaktayken tuşlar kendi giriş kutusuna gidebiliyordu. Artık sarılı.
3. **Girdi karışması:** eşzamanlı araçlar aynı anda tuş gönderebiliyordu → global `_INPUT_LOCK` (RLock); tüm girdi fonksiyonları sıralanır.
4. **`ALT` hilesi:** `focus_window` ön plan kilidi için `ALT`'a dokunuyordu; Not Defteri/Office'te menüyü etkinleştirip harfleri menüye yolluyordu → atanmamış `VK_F24`.
5. **Odak doğrulaması:** `focus_window` 3 deneme + doğrulama yapar; öne gelmezse `type_text` **yazmaz**. Yazarken her 8 karakterde odak kontrol edilir
   (`FocusLost`, sonuçta `typed_chars`).
6. Vekil çiftleri (emoji), `\\t` ve `\\r\\n` doğru; basılı kalmış Shift/Ctrl/Alt/Win bırakılır; 200+ karakterde hızlanır.

## Bilinen sınır
Yönetici yetkisiyle çalışan pencerelere `SendInput` ile yazılamaz (UIPI). JARVIS yönetici değilse bu pencerelerde yazma reddedilir.
Test: `tests/test_keyboard_live.py` (canlı, kendi Tk penceresine yazar).
""", ["araç", "windows"])

note("02 Araçlar/Uygulama Açma.md", "Uygulama Açma", """
`tools/app_launcher.py`.

## `open_application(name)` akışı (Windows)
1. Ayar `open_apps_via_search` (varsayılan **True**) ise görünür arama akışı: aramaya **kısayolun gerçek adı** (`_search_text_for`: takma ad → Başlat/Masaüstü `.lnk` adı → ham ad) harf harf yazılır.
   - Arama paneli **gerçekten açıldı mı** doğrulanır (ön plan değişti / `SearchHost.exe`); açılmadıysa hiçbir şey yazılmaz.
   - Enter'dan sonra **yeni pencere** belirdi mi `_confirm_launched` ile doğrulanır (6 sn).
2. Doğrulanamazsa `close_search()` + **doğrudan başlatma**: takma ad → bulanık kısayol araması → `os.startfile`/PATH. Sonuçta `note` alanı nedeni söyler.
3. macOS `open -a`, Linux `xdg-open`/PATH.

## `open_website(target)`
URL/alan adı/arama sorgusu. `type_in_browser` yolu başarısız olursa **doğrudan** varsayılan tarayıcıda açılır (`via: dogrudan`).

## Bilinen kusur
Olmayan bir uygulama adı aratılırsa Windows araması Enter'la **web araması** yapabilir (eski davranış).
Testler: `tests/test_app_launcher.py`. Bkz. [[Klavye ve Fare Kontrolü]].
""", ["araç"])

# ---------------------------------------------------------------- ENTEGRASYONLAR
note("03 Entegrasyonlar/WhatsApp Kolu.md", "WhatsApp Kolu", """
`core/whatsapp_handler.py` (+ `core/media_utils.py`). Playwright `launch_persistent_context` (`data/whatsapp_session/`, QR bir kez) ile `web.whatsapp.com`.
`main.py` `BrainEngine` + `WhatsAppHandler`'ı **aynı TaskGroup**'ta çalıştırır. `run()` tüm hatayı yutar + backoff ile yeniden bağlanır.

> ⚠️ **Durum (2026-09-20):** kalıcı `enabled: false`. Giriş (QR) ve "mesajlar dinleniyor" aşaması canlı doğrulandı; **gerçek mesaj okuma→yanıt→gönderme akışı henüz hiç canlı test edilmedi.** Seçiciler (`SEL` sözlüğü) WhatsApp Web'in güncel DOM'una uymayabilir.

## Mesaj akışı
1. Her turda listenin en üstündeki `scan_top_chats` (8) sohbet gezilir (okunmamış rozetine **bakılmaz**; son mesaja göre karar).
2. Rol: **admin** (tüm komutlar) / **whitelist** (otomatik yanıt) / **other** (yok sayılır). Gruplar `reply_to_groups`'a göre.
3. Sohbetin sonundan başa, ilk kendi `message-out` balonuna kadar tüm gelen mesajlar toplanır.
4. Kara liste (tam kelime), mod kapısı (otomatik/manuel/sessiz), cooldown (8 sn).
5. Ses/görsel → Gemini multimodal ile metne çevrilir (`media_utils`; Whisper yok), sonra silinir.
6. **Art arda gelen mesajlar TEK mesaja birleştirilir** (`_merge_messages`) → tek yanıt (2026-09-20).
7. Yanıt üretimi: [[OpenRouter]] (birincil) → Gemini yedeği; `REPLY_TIMEOUT_S=50`.
8. **İnsan simülasyonu:** düşünme beklemesi (2–6 sn, uzunlukla artar) + `press_sequentially` (28–65 ms/karakter). 180+ karakterde ilk 60 harf yavaş, kalanı yapıştırılır.
9. Her gelen/giden mesaj `bridge/outbox.txt`'e `[WHATSAPP] …` yazılır (canlı beyin duyar).

## Dürüstlük kuralları (2026-09-20)
`HONESTY_RULES` **her zaman** system prompt'un sonuna eklenir (`whatsapp.json` prompt'u ezse bile):
1. İçtenlikle "bot musun?" sorulursa insan olduğunu söyleme; Sezai'nin yapay zeka asistanı olduğunu belirt.
2. Sezai adına söz/plan/taahhüt verme.
3. Saat, yer, sonuç uydurma; bilmiyorsan "Sezai'ye ileteyim, döner" de.

**Kişisel sorular** ("nerdesin", "napıyosun", "müsait misin", "gelecek misin"…; Türkçe karakter normalize edilir; tek başına "nerde?" da, "nerede yapılıyor maç" değil):
- `_status_context()` okul ders programından **gerçek** durumu verir ("şu an X dersinde"); veri yoksa "BİLİNMİYOR".
- Bot üçüncü tekil kişiyle "Sezai'ye ilettim, müsait olunca döner" der ve `notify_personal_questions` ile yöneticiye bildirim gider.
- Yöneticinin kendi sorusu kişisel sayılmaz.

## Yönetici komutları (admin numarasından)
`JARVIS durum` · `JARVIS modu [otomatik|manuel|sessiz]` · `JARVIS sessiz` · `JARVIS mikrofon/hoparlör aç/kapat` · `JARVIS söyle: X` · `JARVIS ajan: X` · `JARVIS hafıza sil` · `JARVIS kapat`.

## Yapılandırma ve testler
[[WhatsApp Yapılandırması]] · `tests/test_whatsapp_sim.py` (DOM sınırı taklit edilir, **gerçek WhatsApp'a dokunmaz**) · [[Testler]].

## Riskler
- Otomasyonla WhatsApp Web kullanımı **hesap kısıtlamasına** yol açabilir.
- İzinli kişiyle yazışmalar üçüncü taraf modele gider → [[OpenRouter]] gizlilik notu.
- `admin_numbers` yer tutucu (`+905xxxxxxxxx`), ntfy kurulu değil → bildirimler yalnızca log'a düşer.
""", ["entegrasyon", "whatsapp"])

note("03 Entegrasyonlar/OpenRouter.md", "OpenRouter", """
WhatsApp yanıtlarının **düşünme** işi Gemini'den OpenRouter'a alındı (Gemini ücretsiz kotası tükendiği için; 2026-09-20).
OpenAI uyumlu API (`https://openrouter.ai/api/v1`), `openai` SDK (`AsyncOpenAI`, `max_retries=0`).

## Yapılandırma
| Ayar | Nerede | Not |
|---|---|---|
| `OPENROUTER_API_KEY` | `.env` | **gizli** |
| `OPENROUTER_MODEL` | `.env` | birincil model; `whatsapp.json` `openrouter_model`'i ezer |
| `openrouter_fallback_models` | `whatsapp.json` | sırayla denenecek yedekler |
| `reply_provider` | `whatsapp.json` | `auto` (OpenRouter → Gemini), `openrouter`, `gemini` |

Seçilen model: `nvidia/nemotron-3-super-120b-a12b:free`; yedekler `google/gemma-4-31b-it:free`, `qwen/qwen3.8-27b:free`.

## Davranış
- Model başına 25 sn sınır; boş yanıt = başarısız → sıradaki model.
- Bazı ücretsiz modeller `system` rolünü reddeder (400 "instruction …") → talimat ilk kullanıcı mesajına katlanır (`_fold_system`).
- `<think>…</think>` etiketleri atılır, yanıt tek satıra indirilir.
- Tüm OpenRouter modelleri başarısız olursa **Gemini yedeği**.
- OpenRouter'da arama aracı yok → prompt'a "internete erişemiyorsun, tahmin yürütme" yönergesi eklenir.

## Denemeler (2026-09-20)
Nemotron 3 Super iki zor soruyu doğru yanıtladı ("nerdesin" → uydurma konum yok; "bot musun?" → "Sezai'nin yapay zeka asistanıyım").
Gemma ve Qwen o anda sağlayıcı tarafında `429` (paylaşımlı ücretsiz havuz) döndü.

## ⚠️ Bilinmesi gerekenler
- Ücretsiz modeller ≈ **günde 50 istek** (kredi yoksa), dakikada 20.
- Ücretsiz sağlayıcılar istemleri **kaydedip eğitimde kullanabilir** → özel yazışmalar üçüncü tarafa gider.
- Anahtar sohbette paylaşıldı → **iptal edip yenile** ([[Gizli Değerler]]).
""", ["entegrasyon", "model"])

note("03 Entegrasyonlar/Android ADB.md", "Android ADB", """
`tools/adb_tool.py` — asenkron `ADBController` (`asyncio.create_subprocess_exec`; Windows SelectorEventLoop için `to_thread` yedeği). `adb`: `C:\\Users\\KULLANICI\\AppData\\Local\\Android\\sdk\\platform-tools\\adb`.

- **Cihaz:** Samsung SM-S721B (Galaxy S24 FE), kablosuz hata ayıklama ile bağlı.
- **Kablosuz:** `connect_wifi`, `disconnect_wifi`, `pair_wifi(address, code, connect_port=None)`, `enable_wifi`. Android 11+ **eşleşme portu ≠ bağlantı portu**; `pair_wifi` ikisini ayırır, mDNS ile kendiliğinden görünmeyi de dener.
- **Kontrol:** `unlock_device` (uyandır + kaydır + kayıtlı PIN'i tuş tuş gir), `open_app_or_url`, `play_media` (URL → VIEW intent; metin → `MEDIA_PLAY_FROM_SEARCH`, olmazsa `spotify:search:` derin bağlantı), `execute_raw_shell`.
- **PIN:** `adb_set_unlock_pin` → tercihen **Windows Credential Manager** (`keyring`), yoksa `.env` (`JARVIS_ADB_UNLOCK_PIN`). PIN loglanmaz, sesli tekrarlanmaz. Bkz. [[Gizli Değerler]].
- **Shell tırnaklama hatası (düzeltildi 2026-09-03):** argümanlar ayrı argv verilince cihaz kabuğu tekrar bölüyordu ("Fenerbahçe 100. yıl marşı" → `pkg=100.`). Artık komut tek string + `shlex.quote`.
- `probe()` açılışta `adb_tcp_devices` adreslerine 6 sn zaman aşımıyla bağlanır. `device_id=None` → bağlı **tüm** cihazlar.
- Araçlar `adb_*` önekli ([[Araç Kataloğu]]); hepsi onaysız.
""", ["entegrasyon", "android"])

note("03 Entegrasyonlar/E-posta.md", "E-posta", """
`agents/integrations/email_client.py` — stdlib `imaplib`/`smtplib`, **uygulama şifresi** ile. Gmail hesabı `.env`'de bağlı (IMAP+SMTP test edildi).
`tools/email_tools.py`: `check_email`, `read_email`, `search_email` (salt-okuma) + `send_email` (**onay kapılı**).
Prompt kuralı: göndermeden önce taslağı **sesli oku**, "göndereyim mi?" diye sor; sonra sistem ayrıca pencere açar.
Ajanlar: `eposta_triyaj`, `yanit_taslakcisi`, `gelen_kutusu` ([[Departman - iletisim]]).
Yapılandırılmamışsa araç "yapılandırılmamış" döner. Test: `scripts/test_email.py`. Anahtarlar: [[Gizli Değerler]].
""", ["entegrasyon"])

note("03 Entegrasyonlar/Okul Köprüsü.md", "Okul Köprüsü", """
**BÖTE Ders Merkezi** (`okul/`, saf HTML/JS PWA, localStorage) ↔ JARVIS çift yönlü **yerel HTTP köprüsü** (Supabase yok).

- okul → JARVIS: `okul/assets/js/modules/jarvis.js` her değişiklikte 3 sn debounce ile `POST http://<pc>:8770/api/okul/push` (`App.store.exportAll()`, `text/plain` → CORS preflight yok).
- JARVIS → okul: `window focus` / `visibilitychange` → `GET /api/okul/pull` → dönen op'lar `applyOps` ile `tasks`/`exams`'a eklenir.
- JARVIS tarafı: `web/console_server.py` `_okul_push` (→ `data/okul_state.json`, atomik) / `_okul_pull` (→ `data/okul_outbox.json`, döndürür+temizler).
- Araçlar (`tools/okul_tool.py`): `okul_status`, `okul_next_exams`, `okul_today_tasks`, `okul_schedule`, `okul_gpa`, `okul_search_notes`, `okul_add_task`, `okul_add_exam`.
- Veri şekilleri: `tasks{id,title,course,due,priority,status}`, `exams{course,type,date,time,location,topics}`, `schedule{name,day(0=Pzt),start,end,room,instructor}`, `grades_courses{term,name,credit,grade}`.
- okul **HTTP'den açılmalı** (`python -m http.server 8000` `okul/` içinde); `file://` iken `fetch` bloklu. Yapılandırma: `okul/assets/js/config.js` `jarvis:{host,token,enabled}`.

> ⚠️ **2026-09-20 itibarıyla `data/okul_state.json` içinde ders (`schedule`) yok (0 kayıt).** Bu yüzden [[WhatsApp Kolu]]'nun "şu an derste" cevabı henüz çalışmaz; dersler okul uygulamasına girilip senkronlanınca çalışır.
> ⚠️ `config.js` içine JARVIS token'ı sabit yazılı (statik sitede `.env` yok) → yenilenmeli ([[Gizli Değerler]]).
""", ["entegrasyon", "okul"])

note("03 Entegrasyonlar/Android İstemcisi.md", "Android İstemcisi", """
`C:\\dev\\jarvis-android` — Kotlin / Jetpack Compose istemci uygulaması (`app/`, Gradle Kotlin DSL).
Bağlantı: JARVIS [[Web Konsolu ve PWA]] sunucusuna **SSE** (`/api/events`) + `?key=` token + `/api/say`.
Derleme/KSP notları önceki oturumlardan hafıza notunda; **bu kasa hazırlanırken kod incelenmedi** (yalnızca klasörün var olduğu doğrulandı).
""", ["entegrasyon", "android"])

note("03 Entegrasyonlar/Obsidian Kaşaları.md".replace("ş", "s"), "Obsidian Kasaları", """
Üç ayrı kasa vardır:

| Kasa | Konum | Amaç | Kim yazar |
|---|---|---|---|
| **JARVIS Bilgi Kasası** (bu kasa) | `C:\\Users\\KULLANICI\\Documents\\JARVIS Bilgi Kasasi` | Dokümantasyon / inceleme | Bir kez üretildi (koddan); JARVIS yazmaz |
| **JARVIS Hafıza** | `C:\\Users\\KULLANICI\\Documents\\JARVIS Hafiza` | Canlı otomatik kayıt | JARVIS (`Konusmalar/`, `Notlar/`, `GBrain/`) + eski `Proje/` dokümanları (2026-09-03) |
| Claude Memory | `C:\\Users\\KULLANICI\\Documents\\Claude Memory` | Claude'un hafızası | Claude |

`tools/obsidian_sync.py`: `vault_dir`, `append_note`, `read_recent_notes`, `write_doc`, `append_conversation(role, text)`.
- `remember_note` → `<vault>/Notlar/YYYY-MM-DD.md` günlük dosya.
- GBrain her kaydı `<vault>/GBrain/<slug>.md` aynası olarak bırakır.
- `Konusmalar/YYYY-MM-DD.md` → `**HH:MM · Etiket:** metin`; `turn_complete`'te user+jarvis (`brain_engine._log_conversation`).
- Ayarlar: `JARVIS_OBSIDIAN_VAULT`, `JARVIS_OBSIDIAN_SUBDIR` (boş = kasa kökü), `obsidian_log_conversations`. Kasa yoksa sessiz yedek (yerel `data/`).

> `JARVIS Hafiza\\Proje\\` altındaki 15 doküman 2026-09-03 tarihli; **WhatsApp, ADB PIN/keyring, yazma düzeltmeleri, OpenRouter ve güvenlik sertleştirmesini içermez**. Güncel kaynak bu kasadır.
""", ["entegrasyon", "obsidian"])

# ---------------------------------------------------------------- YAPILANDIRMA
note("04 Yapılandırma/Ayarlar ve Ortam Değişkenleri.md", "Ayarlar ve Ortam Değişkenleri", settings_md + "\n\nÜst: [[Genel Bakış]] · Gizliler: [[Gizli Değerler]]",
     ["yapılandırma", "otomatik"])

note("04 Yapılandırma/Sistem Prompt'u.md", "Sistem Prompt'u", "`prompts/system_prompt.txt` (canlı beynin kişiliği ve kuralları) — kodla birebir kopya:\n\n```text\n" + sys_prompt.strip() + "\n```\n\nÜst: [[Canlı Beyin Motoru]]", ["yapılandırma"])

note("04 Yapılandırma/WhatsApp Yapılandırması.md", "WhatsApp Yapılandırması", """
`config/whatsapp.json` (**gitignore'da**; şema `config/whatsapp.example.json`; önce `whatsapp.json`, yoksa örnek okunur). Ortam ezme: `JARVIS_WHATSAPP_ENABLED`, `JARVIS_WHATSAPP_HEADLESS`.

| Alan | Varsayılan | Anlamı |
|---|---|---|
| `enabled` | false | Kapalıyken handler hiç başlamaz |
| `headless` | false | Görünür tarayıcı |
| `user_data_dir` / `download_dir` | `data/whatsapp_session` / `data/whatsapp_media` | Oturum / medya |
| `poll_interval_seconds` | 4.0 | Yoklama aralığı |
| `scan_top_chats` | 8 | Her turda bakılacak sohbet |
| `history_size` | 12 | Kişi başı hafıza turu |
| `cooldown_seconds` | 8.0 | Aynı kişiye yanıtlar arası |
| `typing_delay_enabled` / `typing_min_seconds` / `typing_max_seconds` | true / 2 / 6 | Düşünme beklemesi |
| `whitelist_mode` | `list` | `list` (yalnız izinliler) · `all` (admin dışı herkes) · `off` (yalnız admin) |
| `admin_numbers` | — | Yönetici; **şu an yer tutucu** |
| `allowed_contacts` | `["ornek_kisi"]` | İzinli kişiler (numara **veya** rehber adı; büyük/küçük harf ve emoji duyarsız, alt dize eşleşir) |
| `blacklisted_words` | [] | Tam kelime eşleşmesi; eşleşirse yanıt yok + bildirim |
| `reply_to_groups` | false | Gruplar |
| `startup_mode` | `otomatik` | `otomatik` / `manuel` / `sessiz` |
| `media_enabled`, `media_max_mb`, `media_retention_minutes` | true / 16 / 30 | Ses/görsel işleme |
| `web_search_enabled` | true | Gemini Google araması (yalnız Gemini yolu) |
| `notify_personal_questions` | true | "Nerdesin" gibi sorularda yöneticiyi bilgilendir |
| `reply_provider` | `auto` | Bkz. [[OpenRouter]] |
| `openrouter_model`, `openrouter_fallback_models` | — | Bkz. [[OpenRouter]] |
| `system_prompt` | (kişilik metni) | **`HONESTY_RULES` her zaman sonuna eklenir** |

> `whatsapp.json` içindeki `system_prompt` koddaki varsayılanı **ezer**; ikisini birlikte güncelle.
Bkz. [[WhatsApp Kolu]].
""", ["yapılandırma", "whatsapp"])

# ---------------------------------------------------------------- GUVENLIK
note("05 Güvenlik/Güvenlik Modeli.md", "Güvenlik Modeli", """
JARVIS klavye, fare, kabuk, e-posta, telefon ve WhatsApp yetkilerine sahip olduğu için güvenlik önemlidir.

## Var olan kontroller
| Kontrol | Nerede |
|---|---|
| Onay kapıları (kapatma, süreç öldürme, kod, git yazma, e-posta, kapanış) | [[Onay Kapıları]] |
| `code_exec_enabled` **varsayılan kapalı**; `run_python -I` sandbox | `tools/code_tools.py` |
| Web konsolu: token (`hmac.compare_digest`), CORS izin listesi, token yoksa loopback | [[Web Konsolu ve PWA]] |
| Ekran yakalama dışı bırakma (pencere modele görünmez) | [[Canlı Beyin Motoru]] |
| Yazma odak koruması, girdi kilidi | [[Klavye ve Fare Kontrolü]] |
| WhatsApp: yalnız izinli kişi/grup yok, kara liste, cooldown, dürüstlük kuralları, yönetici bildirimi | [[WhatsApp Kolu]] |
| `_PROTECTED` süreç listesi (explorer/system/svchost asla kapatılmaz) | `tools/window_control.py` |
| Nazik kapatma (`taskkill` `/F` yok) | `tools/window_control.py` |

## Açık riskler
1. `type_text`, `click_at`, `press_keys`, `adb_*` **onaysız**; yanlış tıklama/yazma zarar verebilir.
2. Web konsolu token'ı URL'de ve düz HTTP; ağdaki biri dinleyebilir.
3. Başsız modda (`main.py`) `confirm` varsayılan **True** → onay kapıları fiilen kapalı.
4. WhatsApp otomasyonu hesap kısıtlaması riski; yazışmalar üçüncü taraf modele gider.
5. Anahtarların sohbette paylaşılması → [[Gizli Değerler]].
6. 85 aracın hepsi tek LLM'e açık; yanlış araç seçme riski büyür.

Bkz. [[Sorunlar ve Yapılacaklar]].
""", ["güvenlik"])

note("05 Güvenlik/Gizli Değerler.md", "Gizli Değerler", """
**Bu kasaya hiçbir gizli değer yazılmadı.** Aşağıda yalnızca *nerede tutulduğu* ve *ne yapılması gerektiği* var.

| Gizli | Nerede | Durum / yapılacak |
|---|---|---|
| `GEMINI_API_KEY` | `jarvis-brain/.env` | Live için gerekli. `AQ.` ephemeral token de çalışır (~30 dk). |
| OPTIMAL ENGINE `GEMINI_API_KEY` | `multi/.env.local` | **Sohbette paylaşıldı → yenile** |
| `OPENROUTER_API_KEY` | `jarvis-brain/.env` | **2026-09-20'de sohbete yapıştırıldı → OpenRouter'dan iptal edip yenile** |
| `EMAIL_APP_PASSWORD` | `.env` | Gmail uygulama şifresi |
| `JARVIS_WEB_TOKEN` | `.env` | Web konsolu; boşsa yalnız localhost |
| ADB kilit PIN'i | Tercihen **Credential Manager** (`keyring`); yoksa `.env` `JARVIS_ADB_UNLOCK_PIN` | `keyring` bu makinede **kurulu değil** → şu an `.env`. `pip install keyring` sonra PIN'i bir kez yeniden kaydet |
| okul `config.js` token'ı | `okul/assets/js/config.js` | Statik sitede sabit yazılı → yenile |
| WhatsApp oturumu | `data/whatsapp_session/` | Giriş çerezleri; **paylaşma**, git'te yok |

`config/secrets.py`: `get_secret` / `set_secret` (keyring yoksa sessizce `None`/`False`; çağıran `.env`'ye düşer).
Kural: `.env`, `config/whatsapp.json`, `data/`, `bridge/*.txt` **gitignore'da**.
""", ["güvenlik"])

# ---------------------------------------------------------------- TEST
note("06 Test/Testler.md", "Testler", f"""
Toplam test dosyaları ve içerikleri (kodda saptandı, {TODAY}):

{tests_md}

## Çalıştırma
```bash
python -m pytest tests -q
$env:JARVIS_LIVE_TESTS=1; python -m pytest tests/test_keyboard_live.py -q   # canlı (klavye/fare kullanma!)
```
Son tam çalıştırma: **95 geçti, 3 canlı test atlandı** (canlılar `JARVIS_LIVE_TESTS=1` ister).

## Ne kapsanıyor / kapsanmıyor
✅ WhatsApp karar mantığı (rol, mod, cooldown, kara liste, admin komutu, hafıza, insan gönderimi, tek mesaj birleştirme, kişisel sorular, dürüstlük kuralları, OpenRouter zinciri) — **DOM sınırı taklit edilerek**.
✅ Web konsolu auth/CORS/loopback; keyring geri dönüşü; uygulama açma yedek yolları; klavye yazma (canlı, kendi Tk penceresi).
❌ **Playwright ile gerçek WhatsApp Web akışı**, gerçek Gemini/OpenRouter yanıt kalitesi (yalnız elle denemeler), ADB, e-posta gönderimi, sesli beyin.
Eski elle betikler: `scripts/test_delegation.py`, `test_email.py`, `test_mega.py`.
""", ["test", "otomatik"])

# ---------------------------------------------------------------- GUNLUK
note("07 Günlük/2026-09-02 İlk Kurulum.md", "2026-09-02 İlk Kurulum", """
İlk tam sürüm kuruldu ve canlı test edildi: `pip install -r requirements.txt`, `python main.py` Gemini Live oturumu açtı (sesli yanıt + transkript),
köprü enjeksiyonu çalıştı, mikrofon/hoparlör 16k/24k tamam.

Aynı gün eklenenler: masaüstü HUD arayüzü, ekran görüşü (`mss`) + `look_at_screen`, klavye/fare simülasyonu (`SendInput`), fare + doğru yere yazma/silme,
capture exclusion, onay mekanizması, uygulama açma (`app_launcher`), FounderOS çok-ajanlı sistem (6 departman/37 ajan), e-posta, PyInstaller paketleme,
**"MEGA GENİŞLEME"** (web konsolu, proaktif sistem, hızlı araçlar, PC güç, vision, kod, GBrain — 66 araç).
Bkz. [[Canlı Beyin Motoru]], [[Ajan Sistemi (FounderOS)]], [[Masaüstü Arayüzü (HUD)]].
""", ["günlük"])

note("07 Günlük/2026-09-03 Genişleme.md", "2026-09-03 Genişleme", """
- Masaüstü kısayolu (`scripts/launch_jarvis.vbs`, konsolsuz).
- **Obsidian entegrasyonu** ve ayrılmış **JARVIS Hafıza** kasası + otomatik konuşma kaydı ([[Obsidian Kasaları]]).
- **Telefon kontrolü + çift yönlü sesli görüşme + PWA** ([[Web Konsolu ve PWA]]).
- **Android ADB / "Ultron" modülü** (WiFi dahil) → 75 araç; sonra **PIN + otomatik kilit açma** → 76 ([[Android ADB]]).
- **ADB WiFi pair→connect** düzeltmesi ve **shell tırnaklama** hatası düzeltmesi.
- **okul köprüsü** → 84 araç ([[Okul Köprüsü]]).
- Not: bugünkü sayım kodda **85 araç** ([[Araç Kataloğu]]).
""", ["günlük"])

note("07 Günlük/2026-09-20 İyileştirme Turu.md", "2026-09-20 İyileştirme Turu", """
## OPTIMAL ENGINE (Next.js) sertleştirme — bkz. [[OPTIMAL ENGINE (Next.js)]]
Auth/origin kontrolü, zod şemaları, hız sınırı, Gemini anahtarı header'a, vault yazıcı symlink/atomik yazma, plan önbelleği, UI iyileştirmeleri,
vitest + eslint + CI. `RadialGraphCanvas` 542→100 satır, klavye erişilebilirliği.

## JARVIS
1. **Web konsolu sertleştirme:** `compare_digest`, `X-Jarvis-Key`, CORS izin listesi, token yoksa loopback ([[Web Konsolu ve PWA]]).
2. **PIN:** keyring desteği (`config/secrets.py`) ([[Gizli Değerler]]).
3. **Yazma / uygulama açma düzeltmeleri** — kök nedenler `about:blank`→`openwith.exe`, eksik geri çekme, girdi karışması, ALT hilesi ([[Klavye ve Fare Kontrolü]], [[Uygulama Açma]]).
4. **WhatsApp simülasyon testleri** (DOM taklidi) → tüm karar mantığı doğrulandı ([[WhatsApp Kolu]]).
5. **Tek mesaja birleştirme:** art arda gelen mesajlar tek kullanıcı turu, tek yanıt.
6. **Yanıt kalitesi:** Google Search grounding + tarih/saat bağlamı (Gemini yolu); yanıt üretimi 50 sn sınırlı (eskiden kotada dakikalarca tıkıyordu); zincirden ölü `gemini-2.5-flash` (404) çıkarıldı.
7. **Dürüstlük kuralları:** "bot musun?" → insan olduğunu söylemez; söz/uydurma yasak; kişisel sorularda gerçek ders programı + yönetici bildirimi.
8. **`ornek_kisi`** izinli kişiye eklendi.
9. **Canlı deneme:** WhatsApp Web'e giriş yapıldı (QR), "mesajlar dinleniyor" görüldü; **mesaj gelmeden durduruldu**.
10. **OpenRouter** birincil yanıt modeli oldu ([[OpenRouter]]); Gemini yedek.
11. **HUD Aşama 1:** performans (WebcamView/Transcript/Log/BrainGraph), doğru Türkçe metinler, gerçek model adı, GÖREV aktif/toplam, odak modu; `HudOrb` silindi; `tests/ui/` + `scripts/ui_snapshot.py` ([[Masaüstü Arayüzü (HUD)]]).
12. Bu kasa oluşturuldu.

## Bulgular
- Gemini ücretsiz kotası tüm zincirde tükenmişti (429).
- Modelin insan taklidi yapması ve senin adına söz vermesi gerçek bir risk olarak görüldü → kurallar koda gömüldü.
""", ["günlük"])

note("07 Günlük/2026-10-12 Ekim Güncellemeleri.md", "2026-10-12 Ekim Güncellemeleri", """
Eylül sonundan 13 Ekim'e kadar yapılanların özeti. Ayrıntılı proje notları ayrı kasada: `JARVIS Hafiza/Proje/`.

## Arayüz
1. **Komuta HUD** varsayılan oldu; merkezde dönen 3B yörünge (`CommandGraph`), zırh büstü (`SuitCore`) silindi, mint palet ([[Masaüstü Arayüzü (HUD)]]).
2. **İçerik paneli:** video, Wikipedia, belge, site, Spotify, haber, piyasa grafiği, hava ve bilgi kartı arayüzün içinde açılır (10 yeni araç, [[Araç Kataloğu]]).

## Beyin motoru
3. **Uyandırma kelimesi** "Hey JARVIS" (openwakeword) + en fazla uyanık kalma tavanı; köprü mesajı sırasında mikrofon modele kapanır.
4. **Kesintisiz hafıza:** Live oturum devam tutamağı (session resumption) + temiz oturumda "OTURUM BAĞLAMI" (tarih/saat, dünün özeti, bugünkü konuşmanın sonu).
5. **Gün sonu özeti:** `core/daily_summary.py` → `JARVIS Hafiza/Gunluk/YYYY-MM-DD.md` (varsayılan 23:30 + açılışta telafi).
6. **Yalnız benim sesim:** konuşmacı doğrulama (`core/speaker_verify.py`, sherpa-onnx); profil yoksa pasif.
7. **Çevrimdışı mod:** internet yokken yerel model (Ollama qwen2.5) + yazılı sohbet + sesli konuşma (vosk + Piper/SAPI).

## Ajanlar ve entegrasyonlar
8. Ajan başına model + yedek zinciri (Claude → OpenRouter → Gemini → yerel), sessiz yedek yok ([[OpenRouter]], [[Modeller ve Anahtarlar]]).
9. Gmail OAuth, Telegram kolu, İzmir ulaşım araçları, Spotify kolu, MCP istemcisi, tarayıcı ajanı, disk bakımı, kişisel hafıza araması.
10. Sunucu (beyin) + istemci (gövde) ayrımı ve VPS kurulum dosyaları (`server/`, `client/`, `deploy/`).

## Güvenlik
11. **Güvenli kapatma:** kapatma kısayolları (alt+f4, ctrl+w ...) onaysız gitmez, onay gerçek pencere başlığını gösterir, korumalı pencereler reddedilir ([[Onay Kapıları]]).

## Paketler (2026-10-13)
google-genai 2.30.1, PySide6 6.12.0 (Essentials + Addons), playwright 1.63.0, anthropic 1.13.0, huggingface_hub 2.2.0,
numpy 2.5.4, onnxruntime 1.31.0. Aynı Python'u paylaşan crewai yüzünden pydantic 2.12.5, openai 2.x ve mcp 1.28.x'te bırakıldı;
websockets 16.x'te kaldı (google-genai `<17` istiyor).
""", ["günlük"])

# ---------------------------------------------------------------- SORUNLAR
note("08 Sorunlar/Sorunlar ve Yapılacaklar.md", "Sorunlar ve Yapılacaklar", """
Öncelik sırasıyla. ✅ = yapıldı, ☐ = açık.

## Acil / güvenlik
- ☐ **OpenRouter anahtarını yenile** (sohbette paylaşıldı).
- ☐ **OPTIMAL ENGINE Gemini anahtarını yenile** (sohbette paylaşılmıştı).
- ☐ `okul/config.js` içindeki sabit JARVIS token'ını yenile.
- ☐ `pip install keyring` sonra ADB PIN'ini bir kez yeniden kaydet (şu an `.env`'de).
- ☐ Başsız modda (`main.py`) onay kapıları fiilen kapalı (`confirm` → `True`): karar ver.

## WhatsApp
- ☐ **Gerçek mesaj akışı hiç canlı test edilmedi** (okuma → yanıt → gönderme). İlk test için `ornek_kisi`'un mesaj atması gerekiyor.
- ☐ `admin_numbers` yer tutucu (`+905xxxxxxxxx`); ntfy kurulu değil → "seni soruyorlar" bildirimi yalnız log'a düşüyor.
- ☐ Bot "Sezai meşgul görünüyor" gibi hafif tahminler üretebiliyor → prompt'ta daha nötr cümleye sabitle.
- ☐ Gizlilik kararı: ücretsiz OpenRouter modelleri yazışmayı kaydedebilir → `reply_provider: gemini` veya yerel model (Ollama/LM Studio kurulu, GPU 6 GB).
- ☐ Otomasyon hesap kısıtlaması riski; resmi WhatsApp Business API değerlendir.
- ☐ Seçiciler (`SEL`) WhatsApp Web güncellemesiyle bozulabilir.

## Model / kota
- ☐ Gemini ücretsiz kotası tükenmişti (2026-09-20); faturalandırma ya da OpenRouter'a taşıma.
- ✅ Ölü `gemini-2.5-flash` zincirden çıkarıldı.

## Veri
- ☐ `okul_state.json` içinde ders programı yok → WhatsApp "şu an derste" cevabı çalışmaz. Okul uygulamasına dersleri gir + `localhost:8000` senkronu.

## Kod kalitesi
- ☐ Büyük dosyalar bölünmeli: `core/whatsapp_handler.py` (~1.3k satır), `ui/main_window.py`, `tools/adb_tool.py`, `tools/keyboard_input.py`, `tools/tool_declarations.py`.
- ☐ 85 aracı bağlama göre gruplayıp yalnız ilgili olanları modele ver (yanlış araç seçme riski).
- ☐ `type_text`/`click_at`/`adb_*` için ek onay ya da hedef pencere gösterimi (sesli kullanımla denge).
- ☐ Olmayan uygulama adı aratılınca Windows'un web araması yapması.
- ☐ Yönetici yetkili pencerelere yazılamaz (UIPI) — kısıt.
- ☐ Canlı klavye testi bir çalıştırmada 2 kez düştü, sonra 3/3 geçti (odak çekişmesi şüphesi); nedeni kesinleşmedi.
- ☐ `run_agents.py` ile `run_ui.py` aynı anda çalıştırılmamalı (çift işlem).

## Ürün fikirleri
- ☐ Yerel model ile WhatsApp yanıtları (gizlilik).
- ☐ Konum yerine takvim/ders programı bağlamı genişletilebilir.
- ☐ Next.js OPTIMAL ENGINE: Finances/Social/Funnel sekmelerini vault verisine bağla; Next 15 geçişi.

## Yapılanlar
✅ Web konsolu sertleştirme · ✅ keyring desteği · ✅ yazma/uygulama açma düzeltmeleri · ✅ WhatsApp simülasyon testleri · ✅ tek mesaj birleştirme ·
✅ dürüstlük kuralları + kişisel soru akışı · ✅ OpenRouter entegrasyonu · ✅ yanıt üretimi zaman sınırı.
Ayrıntı: [[2026-09-20 İyileştirme Turu]].
""", ["sorun", "yapılacak"])

note("09 İlgili Projeler/OPTIMAL ENGINE (Next.js).md", "OPTIMAL ENGINE (Next.js)", """
`multi/` kök dizini — Bennett Spooner'ın "FounderOS / OptimalEngine" AI-agent şablonunun **siberpunk dashboard klonu** (bir Instagram reel videosuna "birebir aynı" istendi; video bulanık olduğu için renk tonları kesin değil). JARVIS'ten **ayrı** bir projedir.

- **Stack:** Next.js 14.2 (App Router), React 18, TypeScript, Tailwind 3.4, Framer Motion, lucide-react, gray-matter, zod. Gemini düz REST.
- **Sekmeler:** Brain (radyal graph + drill-down) · Personas · Social · Funnel · Finances · Hierarchy.
- **Akış:** Dropzone (metin/ses/dosya) → `/api/ingest` `plan` (Conductor notları önerir) → IngestPanel'de seçili notlar → `commit` ile Obsidian vault'a yazılır → `_system/hygiene-log.md`.
- **API:** `POST /api/gemini` (chat/orchestrate), `POST /api/ingest` (plan/commit/full).
- **Env:** `GEMINI_API_KEY`, `GEMINI_CONDUCTOR_MODEL`, `GEMINI_AGENT_MODEL`, `OBSIDIAN_VAULT_PATH`, opsiyonel `APP_API_TOKEN`.

## 2026-09-20 sertleştirme
same-origin + isteğe bağlı token + hız sınırı, zod şemaları, Gemini anahtarı `x-goog-api-key` header'ında, upstream hata gövdesi sızmaz,
`vaultWriter` symlink/atomik yazma/boyut sınırı + `archive`, plan önbelleği (10 dk), `router.refresh()`, not seçimi/önizleme, `AbortController`,
vitest (22 test) + eslint + CI, `RadialGraphCanvas` bölündü, klavye erişilebilirliği.

## Açık
Renk tonları (Figma/screenshot bekleniyor) · Next 15 · Finances/Social/Funnel gerçek veri · **Git'te hiç commit yok** (üst dizin geniş bir repo).
Ayrıntılı not: hafızadaki `optimal_engine_project`.
""", ["proje"])

# =====================================================================  DOGRULAMA
names = {Path(w).stem for w in written}
bad = []
for rel in written:
    text = (VAULT / rel).read_text(encoding="utf-8")
    for m in re.finditer(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", text):
        if m.group(1).strip() not in names:
            bad.append((rel, m.group(1)))
print(f"{len(written)} not yazildi -> {VAULT}")
print("kirik wikilink:", len(bad))
for b in sorted(set(bad))[:20]:
    print("  ", b)
