"""Android ADB Control - "Ultron" modulu.

Bagli Android cihazlari `adb` (Android Debug Bridge) uzerinden yonetir:
kilit acma, uygulama/URL acma, medya oynatma ve serbest shell komutlari.

WiFi (kablosuz ADB): USB'siz, agdaki cihazlara `adb connect <ip>:<port>` ile
baglanir. `adb_tcp_devices` ayarindaki adresler acilista otomatik denenir; ayrica
USB'den bagli bir cihaz `enable_wifi()` ile kablosuz moda alinabilir (kablo cekilir).

Tasarim ilkeleri (proje mimarisine sadik):
- Tamamen asenkron: komutlar `asyncio.create_subprocess_exec` ile calisir,
  event loop asla bloklanmaz (`subprocess.run` KULLANILMAZ).
- `loguru.logger` ile loglama; `adb` yoksa veya cihaz bagli degilse sistem
  cokmez - `logger.warning` ile yakalanir ve LLM'e kullanici dostu bir hata doner.
- Ayarlar `config.settings.Settings` uzerinden (`adb_enabled`, `adb_path`,
  `adb_tcp_port`, `adb_tcp_devices`).

`ADBController` hem `BrainEngine` tarafindan dogrudan kullanilir hem de
modul-seviyesi ince sarmalayicilar (`adb_list_devices`, `adb_unlock_device`, ...)
araciligiyla Gemini Live "function calling" araci olarak sunulur.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shlex
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from loguru import logger

from config.secrets import set_secret
from config.settings import APP_DIR, BASE_DIR, Settings, get_settings

# Kilit ekranini gecmek icin: once uyandir (KEYCODE_WAKEUP=224), sonra
# ekrani yukari kaydir. Koordinatlar cihazdan bagimsiz kabaca calisir
# (yuzde degil piksel; cogu telefonda alt->ust swipe kilidi acar).
_WAKE_KEYCODE = "224"      # KEYCODE_WAKEUP
_MENU_KEYCODE = "82"       # KEYCODE_MENU (guvensiz kilitlerde acar)
_ENTER_KEYCODE = "66"      # KEYCODE_ENTER (PIN onayi)
_UNLOCK_SWIPE = ("300", "1000", "300", "300", "300")  # x1 y1 x2 y2 duration_ms
# Rakam -> Android KEYCODE (KEYCODE_0=7 ... KEYCODE_9=16). PIN'i `input text` yerine
# tus-tus gondermek kilit ekraninda daha guvenilir ve PIN'i loglara acikca yazmaz.
_DIGIT_KEYCODE = {str(d): str(7 + d) for d in range(10)}

_DEFAULT_TCP_PORT = 5555
# "192.168.1.42", "192.168.1.42:5555" veya "phone.local:37000"
_ADDR_RE = re.compile(r"^(?P<host>[A-Za-z0-9._-]+)(?::(?P<port>\d{1,5}))?$")


class ADBError(RuntimeError):
    """ADB calistirilamadi / cihaz yok / komut basarisiz."""


def _normalize_addr(address: str, default_port: int = _DEFAULT_TCP_PORT) -> str:
    """`host` veya `host:port` -> `host:port` (port yoksa varsayilan eklenir)."""
    raw = (address or "").strip()
    if raw.startswith(("tcp:", "adb-tls://")):
        raw = raw.split("://", 1)[-1].split("tcp:", 1)[-1]
    m = _ADDR_RE.match(raw)
    if not m:
        raise ADBError(f"Gecersiz ag adresi: {address!r} (ornek: 192.168.1.42 veya 192.168.1.42:5555)")
    host = m.group("host")
    port = m.group("port") or str(default_port)
    return f"{host}:{port}"


class ADBController:
    """Bagli Android cihazlari yoneten asenkron ADB sarmalayici."""

    def __init__(
        self,
        adb_path: str = "adb",
        *,
        enabled: bool = True,
        tcp_port: int = _DEFAULT_TCP_PORT,
        tcp_devices: Iterable[str] | None = None,
        unlock_pin: str = "",
    ) -> None:
        self.adb_path = (adb_path or "adb").strip() or "adb"
        self.enabled = bool(enabled)
        self.tcp_port = int(tcp_port or _DEFAULT_TCP_PORT)
        # acilista otomatik `adb connect` denenecek ag adresleri
        self.tcp_devices: list[str] = [a.strip() for a in (tcp_devices or []) if a and a.strip()]
        # ekran kilidi PIN'i (gizli - loglanmaz); `unlock_device` otomatik girer
        self.unlock_pin = "".join(ch for ch in (unlock_pin or "") if ch.isdigit())
        self._available: bool | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ altyapi

    async def _resolve_binary(self) -> str | None:
        """`adb` calistirilabilir yolunu dondurur; bulunamazsa None."""
        found = shutil.which(self.adb_path)
        if found:
            return found
        # adb_path mutlak yol olarak verilmis olabilir
        candidate = Path(self.adb_path).expanduser()
        if candidate.is_file():
            return str(candidate)
        return None

    async def _exec(
        self,
        args: list[str],
        *,
        device_id: str | None = None,
        timeout: float = 20.0,
    ) -> tuple[int, str, str]:
        """`adb [-s <id>] <args>` calistirir. (returncode, stdout, stderr) doner.

        `subprocess.run` YERINE `asyncio.create_subprocess_exec` kullanir.
        """
        binary = await self._resolve_binary()
        if binary is None:
            raise ADBError(
                f"'{self.adb_path}' bulunamadi. Android Platform-Tools kurun ve "
                f"PATH'e ekleyin ya da .env'de CYRAEN_ADB_PATH ile tam yolu verin."
            )

        cmd = [binary]
        if device_id:
            cmd += ["-s", device_id]
        cmd += args

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except NotImplementedError:
            # Bazi Windows event loop'larinda (SelectorEventLoop) alt surec
            # desteklenmez - bloklamayi ayri thread'e tasiyarak telafi et.
            return await asyncio.to_thread(self._exec_blocking, cmd, timeout)
        except FileNotFoundError as exc:
            raise ADBError(f"ADB calistirilamadi: {exc}") from exc

        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            with contextlib.suppress(Exception):
                proc.kill()
            raise ADBError(f"ADB komutu zaman asimina ugradi ({timeout:.0f}s): {' '.join(args)}") from exc

        out = (out_b or b"").decode("utf-8", "replace").strip()
        err = (err_b or b"").decode("utf-8", "replace").strip()
        return proc.returncode or 0, out, err

    @staticmethod
    def _exec_blocking(cmd: list[str], timeout: float) -> tuple[int, str, str]:
        import subprocess

        r = subprocess.run(  # noqa: S603 - komut sabit adb, argumanlar kontrollu
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()

    async def available(self) -> bool:
        """`adb` erisilebilir mi (bir kez tespit edip cache'ler)."""
        if not self.enabled:
            return False
        if self._available is not None:
            return self._available
        try:
            code, _out, _err = await self._exec(["version"], timeout=8.0)
            self._available = code == 0
        except ADBError as exc:
            logger.warning(f"ADB kullanilamiyor: {exc}")
            self._available = False
        return self._available

    async def probe(self) -> dict[str, Any]:
        """Baslangicta cagrilir: ADB + bagli cihaz durumunu loglar."""
        if not self.enabled:
            logger.info("ADB modulu devre disi (adb_enabled=false).")
            return {"enabled": False}
        if not await self.available():
            logger.warning(
                "ADB bulunamadi - Android cihaz kontrolu devre disi. "
                "Platform-Tools kurup PATH'e ekleyin veya CYRAEN_ADB_PATH ayarlayin."
            )
            return {"enabled": True, "available": False}

        # WiFi: yapilandirilmis ag cihazlarina otomatik baglan (acilisi bekletmemek
        # icin kisa timeout; erisilemeyen adres startup'i uzatmasin)
        wifi: list[str] = []
        for addr in self.tcp_devices:
            res = await self.connect_wifi(addr, timeout=6.0)
            if res.get("ok"):
                wifi.append(res.get("address", addr))
            else:
                logger.warning(f"ADB WiFi otomatik baglanti basarisiz [{addr}]: {res.get('error')}")

        try:
            devices = await self.get_connected_devices()
        except ADBError as exc:
            logger.warning(f"ADB cihaz listesi alinamadi: {exc}")
            return {"enabled": True, "available": True, "devices": []}
        if devices:
            logger.success(f"ADB hazir - bagli cihaz(lar): {', '.join(devices)}")
        else:
            logger.info("ADB hazir - su an bagli Android cihaz yok.")
        return {"enabled": True, "available": True, "devices": devices, "wifi": wifi}

    # ------------------------------------------------------------------ ust API

    async def get_connected_devices(self) -> list[str]:
        """Bagli (yetkili) Android cihazlarin seri numaralarini dondurur."""
        code, out, err = await self._exec(["devices"])
        if code != 0:
            raise ADBError(err or "adb devices basarisiz")
        serials: list[str] = []
        for line in out.splitlines()[1:]:  # ilk satir "List of devices attached"
            line = line.strip()
            if not line or "\t" not in line:
                continue
            serial, state = (p.strip() for p in line.split("\t", 1))
            if state == "device":
                serials.append(serial)
            elif state in {"unauthorized", "offline"}:
                logger.warning(f"ADB cihazi '{serial}' durumu: {state} (atlandi)")
        return serials

    # ------------------------------------------------------------------ WiFi / kablosuz

    async def connect_wifi(self, address: str, *, timeout: float = 15.0) -> dict[str, Any]:
        """Ag uzerinden bir cihaza baglanir (`adb connect <ip>:<port>`).

        `address`: "192.168.1.42" veya "192.168.1.42:5555". Port yoksa `tcp_port`.
        """
        if not await self.available():
            return {"ok": False, "error": "ADB kullanilamiyor."}
        try:
            addr = _normalize_addr(address, self.tcp_port)
        except ADBError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            code, out, err = await self._exec(["connect", addr], timeout=timeout)
        except ADBError as exc:
            return {"ok": False, "address": addr, "error": str(exc)}
        text = (out or err).lower()
        ok = code == 0 and ("connected to" in text or "already connected" in text)
        if not ok:
            logger.warning(f"ADB connect [{addr}] basarisiz: {out or err}")
            return {
                "ok": False,
                "address": addr,
                "error": (out or err or "baglanti kurulamadi")
                + ". Telefonda kablosuz hata ayiklamayi ac, ayni WiFi agina bagli ol; "
                "Android 11+ ise once adb_pair_wifi ile eslesme kodu gir.",
            }
        logger.success(f"ADB WiFi bagli: {addr}")
        return {"ok": True, "address": addr, "output": out or err}

    async def disconnect_wifi(self, address: str | None = None) -> dict[str, Any]:
        """Bir ag cihaz baglantisini keser; `address` yoksa TUM ag baglantilari."""
        if not await self.available():
            return {"ok": False, "error": "ADB kullanilamiyor."}
        args = ["disconnect"]
        if address:
            try:
                args.append(_normalize_addr(address, self.tcp_port))
            except ADBError as exc:
                return {"ok": False, "error": str(exc)}
        try:
            code, out, err = await self._exec(args, timeout=10.0)
        except ADBError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": code == 0, "output": out or err or "baglanti kesildi"}

    async def pair_wifi(
        self, address: str, code: str, connect_port: str | int | None = None
    ) -> dict[str, Any]:
        """Android 11+ kablosuz hata ayiklama eslesmesi (`adb pair <ip>:<port> <kod>`).

        `address` + `code` telefonda "Kablosuz hata ayiklama > Cihazi eslestir" ekranindadir.
        DIKKAT: eslesme portu, BAGLANTI portundan FARKLIDIR. Eslesmeden sonra bu metot:
          1) cihaz mDNS ile kendiliginden goründü mü diye bakar,
          2) `connect_port` verildiyse ona baglanir,
          3) olmazsa kullanicidan ana ekrandaki "IP adresi ve port"u ister.
        """
        if not await self.available():
            return {"ok": False, "error": "ADB kullanilamiyor."}
        addr = (address or "").strip()
        pin = (code or "").strip()
        if not addr or not pin:
            return {"ok": False, "error": "'address' ve 'code' zorunlu (telefondaki eslesme ekranindan)."}

        try:
            before = set(await self.get_connected_devices())
        except ADBError:
            before = set()
        try:
            rc, out, err = await self._exec(["pair", addr, pin], timeout=25.0)
        except ADBError as exc:
            return {"ok": False, "error": str(exc)}
        if not (rc == 0 and "successfully paired" in (out or "").lower()):
            logger.warning(f"ADB pair [{addr}] basarisiz: {out or err}")
            return {"ok": False, "error": out or err or "eslesme basarisiz"}
        logger.success(f"ADB WiFi eslesti: {addr}")

        host = addr.split(":", 1)[0]

        # 1) mDNS otomatik baglanti (bu makinede genelde calisiyor)
        await asyncio.sleep(2.5)
        try:
            after = await self.get_connected_devices()
        except ADBError:
            after = []
        new = [d for d in after if d not in before]
        if new:
            logger.success(f"ADB WiFi cihazi otomatik gorundu: {new[0]}")
            return {"ok": True, "connected": True, "device": new[0],
                    "note": "Eslesme tamam ve cihaz otomatik baglandi."}

        # 2) belirtilen ya da eslesme portu ile connect dene
        tried: list[str] = []
        candidates = []
        if connect_port:
            candidates.append(str(connect_port))
        pair_port = addr.split(":", 1)[1] if ":" in addr else ""
        for p in (pair_port, str(self.tcp_port)):
            if p and p not in candidates:
                candidates.append(p)
        for port in candidates:
            res = await self.connect_wifi(f"{host}:{port}", timeout=8.0)
            tried.append(f"{host}:{port}")
            if res.get("ok"):
                return {"ok": True, "connected": True, "address": res.get("address"),
                        "note": "Eslesme tamam ve baglanti kuruldu."}

        return {
            "ok": True,
            "connected": False,
            "tried": tried,
            "note": (
                "Eslesme BASARILI ama otomatik baglanti kurulamadi. Telefonda "
                "'Kablosuz hata ayiklama' ANA ekranindaki 'IP adresi ve port' "
                "(eslesme kodu ekranindaki degil!) ile adb_connect_wifi cagir - "
                f"orn. adb_connect_wifi(\"{host}:<port>\")."
            ),
        }

    async def _discover_ip(self, device_id: str) -> str | None:
        """USB'den bagli cihazin WiFi (wlan0) IPv4 adresini bulur."""
        for args in (
            ["shell", "ip", "-f", "inet", "addr", "show", "wlan0"],
            ["shell", "ip", "route"],
            ["shell", "getprop", "dhcp.wlan0.ipaddress"],
        ):
            with contextlib.suppress(ADBError):
                _rc, out, _err = await self._exec(args, device_id=device_id, timeout=10.0)
                m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", out or "")
                if m and not m.group(1).startswith(("127.", "0.")):
                    return m.group(1)
        return None

    async def enable_wifi(
        self, device_id: str | None = None, port: int | None = None
    ) -> dict[str, Any]:
        """USB'den bagli cihaz(lar)i kablosuz ADB moduna alir ve aga baglanir.

        Adimlar: `adb -s <id> tcpip <port>` -> cihazin IP'sini bul -> `adb connect ip:port`.
        Sonrasinda USB kablosu cekilebilir. `device_id=None` => USB'deki tum cihazlar.
        """
        if not await self.available():
            return {"error": "ADB kullanilamiyor."}
        tcp_port = int(port or self.tcp_port)
        try:
            usb_targets = await self._target_devices(device_id)
        except ADBError as exc:
            return {"error": str(exc)}
        # zaten ag adresi olanlari ele (ip:port bicimli seri)
        usb_targets = [t for t in usb_targets if ":" not in t]
        if not usb_targets:
            return {"error": "USB'den bagli cihaz yok. Once telefonu USB ile bagla ve yetkilendir."}

        results: list[dict[str, Any]] = []
        for serial in usb_targets:
            try:
                await self._exec(["tcpip", str(tcp_port)], device_id=serial, timeout=15.0)
                await asyncio.sleep(1.0)  # adbd'nin TCP modunda yeniden baslamasi
                ip = await self._discover_ip(serial)
                if not ip:
                    results.append({"device": serial, "ok": False, "output": "IP bulunamadi (WiFi acik mi?)"})
                    continue
                conn = await self.connect_wifi(f"{ip}:{tcp_port}")
                results.append({
                    "device": serial,
                    "ok": bool(conn.get("ok")),
                    "address": conn.get("address"),
                    "output": conn.get("output") or conn.get("error"),
                })
            except ADBError as exc:
                results.append({"device": serial, "ok": False, "output": str(exc)})

        connected = [r["address"] for r in results if r.get("ok")]
        return {
            "action": "enable_wifi",
            "port": tcp_port,
            "connected": connected,
            "note": "Kablosuz baglanti kuruldu ise USB kablosunu cekebilirsin." if connected else
                    "Kablosuz baglanti kurulamadi - telefon ve PC ayni agda mi, WiFi acik mi?",
            "results": results,
        }

    async def _target_devices(self, device_id: str | None) -> list[str]:
        """`device_id` verilmisse onu, `None` ise bagli TUM cihazlari dondurur."""
        if device_id:
            return [device_id]
        return await self.get_connected_devices()

    async def _run_on_targets(
        self, device_id: str | None, args: list[str], action: str
    ) -> dict[str, Any]:
        """Verilen `adb` argumanlarini hedef cihaz(lar)da calistirir, ozet doner."""
        if not await self.available():
            return {
                "error": "ADB kullanilamiyor. Android Platform-Tools kurulu ve "
                "PATH'te (veya CYRAEN_ADB_PATH ile tanimli) olmali."
            }
        try:
            targets = await self._target_devices(device_id)
        except ADBError as exc:
            logger.warning(f"ADB hedef cihazlar alinamadi: {exc}")
            return {"error": str(exc)}
        if not targets:
            return {"error": "Bagli Android cihaz yok. USB hata ayiklamayi ac ve cihazi bagla."}

        results: list[dict[str, Any]] = []
        for serial in targets:
            try:
                code, out, err = await self._exec(args, device_id=serial)
                ok = code == 0
                if not ok:
                    logger.warning(f"ADB '{action}' [{serial}] basarisiz: {err or out}")
                results.append(
                    {"device": serial, "ok": ok, "output": (out or err)[:300]}
                )
            except ADBError as exc:
                logger.warning(f"ADB '{action}' [{serial}] hata: {exc}")
                results.append({"device": serial, "ok": False, "output": str(exc)})

        done = [r["device"] for r in results if r["ok"]]
        failed = [r["device"] for r in results if not r["ok"]]
        return {
            "action": action,
            "targeted": targets,
            "succeeded": done,
            "failed": failed,
            "results": results,
        }

    async def _enter_pin(self, serial: str, pin: str) -> None:
        """Kilit ekraninda PIN'i tus-tus girer ve onaylar. PIN loglanmaz."""
        for digit in pin:
            code = _DIGIT_KEYCODE.get(digit)
            if not code:
                continue
            await self._exec(["shell", "input", "keyevent", code], device_id=serial)
            await asyncio.sleep(0.12)
        await asyncio.sleep(0.2)
        await self._exec(["shell", "input", "keyevent", _ENTER_KEYCODE], device_id=serial)

    async def unlock_device(
        self, device_id: str | None = None, pin: str | None = None
    ) -> dict[str, Any]:
        """Cihaz(lar)in ekranini uyandirir, kilit ekranini kaydirir ve (varsa) PIN girer.

        `device_id=None` => bagli TUM cihazlar.
        `pin` verilmezse `self.unlock_pin` (ayar: CYRAEN_ADB_UNLOCK_PIN) kullanilir.
        PIN yoksa yalnizca uyandirma + kaydirma yapilir (guvensiz kilitler acilir).
        """
        if not await self.available():
            return {"error": "ADB kullanilamiyor."}
        try:
            targets = await self._target_devices(device_id)
        except ADBError as exc:
            return {"error": str(exc)}
        if not targets:
            return {"error": "Bagli Android cihaz yok."}

        use_pin = "".join(ch for ch in (pin if pin is not None else self.unlock_pin) if ch.isdigit())

        results: list[dict[str, Any]] = []
        for serial in targets:
            steps_ok = True
            try:
                # 1) ekrani uyandir
                await self._exec(["shell", "input", "keyevent", _WAKE_KEYCODE], device_id=serial)
                await asyncio.sleep(0.4)
                # 2) kilit ekranini yukari kaydir (PIN girisi alani gorunur olur)
                await self._exec(
                    ["shell", "input", "swipe", *_UNLOCK_SWIPE], device_id=serial
                )
                await asyncio.sleep(0.4)
                if use_pin:
                    # 3a) kayitli PIN'i gir ve onayla
                    await self._enter_pin(serial, use_pin)
                    detail = "uyandirildi + kaydirildi + PIN girildi"
                else:
                    # 3b) guvensiz (PIN'siz) kilitlerde menu tusu da acar
                    await self._exec(["shell", "input", "keyevent", _MENU_KEYCODE], device_id=serial)
                    detail = "uyandirildi + kaydirildi"
            except ADBError as exc:
                steps_ok = False
                logger.warning(f"ADB unlock [{serial}] hata: {exc}")
                results.append({"device": serial, "ok": False, "output": str(exc)})
            if steps_ok:
                results.append({"device": serial, "ok": True, "output": detail})

        done = [r["device"] for r in results if r["ok"]]
        note = (
            "Kayitli PIN girildi." if use_pin else
            "PIN/desen korumasi varsa ekran acilir ama kilit tam acilmaz "
            "(PIN kaydetmek icin: CYRAEN'e 'telefon sifresini kaydet <PIN>' de)."
        )
        return {
            "action": "unlock_device",
            "targeted": targets,
            "succeeded": done,
            "failed": [r["device"] for r in results if not r["ok"]],
            "pin_used": bool(use_pin),
            "note": note,
            "results": results,
        }

    async def open_app_or_url(
        self, package_or_url: str, device_id: str | None = None
    ) -> dict[str, Any]:
        """Bir uygulamayi (paket adi) veya deep link / URL'yi acar.

        - `http(s)://...` veya `scheme://...`  => VIEW intent ile acilir
        - `com.paket.adi`                       => monkey ile baslatilir
        - `com.paket/.Activity`                 => am start -n ile acilir
        """
        target = (package_or_url or "").strip()
        if not target:
            return {"error": "'package_or_url' bos."}

        if "://" in target:
            # cihaz kabugu tek string ayristirir -> URL'yi tirnakla (& ? bosluk guvenli)
            cmd = f"am start -a android.intent.action.VIEW -d {shlex.quote(target)}"
            action = f"open_url:{target}"
        elif "/" in target:
            cmd = f"am start -n {shlex.quote(target)}"
            action = f"open_activity:{target}"
        else:
            # paket adi -> varsayilan LAUNCHER aktivitesini baslat
            cmd = (
                f"monkey -p {shlex.quote(target)} "
                f"-c android.intent.category.LAUNCHER 1"
            )
            action = f"open_app:{target}"
        return await self._run_on_targets(device_id, ["shell", cmd], action)

    async def play_media(
        self, url_or_query: str, device_id: str | None = None
    ) -> dict[str, Any]:
        """Cihaz(lar)da medya/muzik oynatmayi tetikler.

        - Bir URL ise (YouTube/Spotify/http) VIEW intent ile acilir ve oynatilir.
        - Duz metin ise ('sarki adi') -> arama araciligiyla oynatma denemesi:
          once medya oynat tusu, sonra bir muzik arama intent'i.
        """
        q = (url_or_query or "").strip()
        if not q:
            return {"error": "'url_or_query' bos."}

        if "://" in q or q.startswith("www."):
            url = q if "://" in q else f"https://{q}"
            cmd = f"am start -a android.intent.action.VIEW -d {shlex.quote(url)}"
            return await self._run_on_targets(device_id, ["shell", cmd], f"play_url:{url}")

        # Serbest metin: once genel PLAY_FROM_SEARCH intent'i, cozulmezse Spotify
        # arama deep link'i. `query` BOSLUKLU olabilir -> cihaz kabugu icin tirnakla.
        from urllib.parse import quote as _urlquote

        attempts = [
            ("play_search", "am start -a android.media.action.MEDIA_PLAY_FROM_SEARCH "
                            f"--es query {shlex.quote(q)}"),
            ("spotify_search", "am start -a android.intent.action.VIEW -d "
                               f"{shlex.quote('spotify:search:' + _urlquote(q))}"),
        ]
        last: dict[str, Any] = {}
        for label, cmd in attempts:
            last = await self._run_on_targets(device_id, ["shell", cmd], f"{label}:{q}")
            if last.get("succeeded"):
                break
        # oynatmayi tetiklemek icin medya tusu (KEYCODE_MEDIA_PLAY=126)
        with contextlib.suppress(Exception):
            await self._run_on_targets(device_id, ["shell", "input", "keyevent", "126"], "media_play")
        return last

    async def execute_raw_shell(
        self, command: str, device_id: str | None = None
    ) -> dict[str, Any]:
        """Esnek kullanim: verilen `adb shell` komutunu calistirir.

        `command` bir kabuk komut satiridir, orn. "settings get system screen_brightness".
        """
        cmd = (command or "").strip()
        if not cmd:
            return {"error": "'command' bos."}
        # Komutu TEK string olarak gonder -> cihaz kabugu kendi ayristirir,
        # kullanicinin tirnaklari/pipe'lari korunur (local split BOZAR).
        return await self._run_on_targets(device_id, ["shell", cmd], f"shell:{cmd}")


# --------------------------------------------------------------------- singleton

_controller: ADBController | None = None


def get_adb_controller(settings: Settings | None = None) -> ADBController:
    """Sureç genelinde tek `ADBController` ornegi (tembel kurulur)."""
    global _controller
    if _controller is None:
        cfg = settings or get_settings()
        _controller = ADBController(
            adb_path=cfg.adb_path,
            enabled=cfg.adb_enabled,
            tcp_port=getattr(cfg, "adb_tcp_port", _DEFAULT_TCP_PORT),
            tcp_devices=getattr(cfg, "adb_tcp_devices", None),
            unlock_pin=getattr(cfg, "adb_unlock_pin", ""),
        )
    return _controller


_ENV_PIN_KEY = "CYRAEN_ADB_UNLOCK_PIN"


def _persist_unlock_pin(pin: str) -> dict[str, Any]:
    """PIN'i `.env` dosyasina yazar + calisan denetleyiciyi gunceller. PIN loglanmaz."""
    digits = "".join(ch for ch in (pin or "") if ch.isdigit())
    if not (4 <= len(digits) <= 16):
        return {"error": "PIN 4-16 haneli olmali (sadece rakam)."}

    # Tercih: OS anahtar deposu (keyring). Yoksa .env yedegine dus.
    if set_secret(_ENV_PIN_KEY, digits):
        os.environ[_ENV_PIN_KEY] = digits
        with contextlib.suppress(Exception):
            get_settings.cache_clear()  # type: ignore[attr-defined]
        if _controller is not None:
            _controller.unlock_pin = digits
        logger.info(f"ADB kilit PIN'i kaydedildi ({len(digits)} hane) -> Credential Manager")
        return {
            "status": "PIN kaydedildi",
            "digits": len(digits),
            "store": "keyring",
            "note": "Bundan sonra 'telefonu ac' dediginde kilit otomatik acilir.",
        }

    env_path = next(
        (p for p in (APP_DIR / ".env", BASE_DIR / ".env") if p.is_file()),
        APP_DIR / ".env",
    )
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
    except OSError as exc:
        return {"error": f".env okunamadi: {exc}"}

    new_line = f"{_ENV_PIN_KEY}={digits}"
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{_ENV_PIN_KEY}=") or line.strip().startswith(f"#{_ENV_PIN_KEY}="):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Telefon ekran kilidi PIN'i (gizli - bu dosya gitignore'da)")
        lines.append(new_line)

    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        return {"error": f".env yazilamadi: {exc}"}

    # calisan surece hemen yansit
    os.environ[_ENV_PIN_KEY] = digits
    with contextlib.suppress(Exception):
        get_settings.cache_clear()  # type: ignore[attr-defined]
    if _controller is not None:
        _controller.unlock_pin = digits

    logger.info(f"ADB kilit PIN'i kaydedildi ({len(digits)} hane) -> {env_path.name}")
    return {
        "status": "PIN kaydedildi",
        "digits": len(digits),
        "file": str(env_path),
        "note": "Bundan sonra 'telefonu ac' dediginde kilit otomatik acilir.",
    }


# ------------------------------------------------------- Gemini Live arac sarmalayicilari
# ToolRunner bu asenkron fonksiyonlari dogrudan cagirir (dict doner).


async def adb_list_devices() -> dict[str, Any]:
    """Bagli Android cihazlarin seri (ID) listesini getirir (USB + WiFi)."""
    ctrl = get_adb_controller()
    if not await ctrl.available():
        return {"error": "ADB kullanilamiyor (Platform-Tools kurulu degil / PATH'te yok)."}
    try:
        devices = await ctrl.get_connected_devices()
    except ADBError as exc:
        logger.warning(f"adb_list_devices hata: {exc}")
        return {"error": str(exc)}
    wifi = [d for d in devices if ":" in d]
    usb = [d for d in devices if ":" not in d]
    return {"count": len(devices), "devices": devices, "wifi": wifi, "usb": usb}


async def adb_connect_wifi(address: str) -> dict[str, Any]:
    """Ag uzerinden bir Android cihaza baglanir (ornek: '192.168.1.42' ya da '192.168.1.42:5555')."""
    return await get_adb_controller().connect_wifi(address)


async def adb_disconnect_wifi(address: str | None = None) -> dict[str, Any]:
    """Bir ag cihaz baglantisini keser; adres verilmezse tum kablosuz baglantilar."""
    return await get_adb_controller().disconnect_wifi(address or None)


async def adb_pair_wifi(
    address: str, code: str, connect_port: str | None = None
) -> dict[str, Any]:
    """Android 11+ kablosuz hata ayiklama eslesmesi + otomatik baglanti denemesi.

    `address` + `code` telefonda 'Kablosuz hata ayiklama > Cihazi eslestir' ekranindaki
    IP:PORT ve 6 haneli koddur. `connect_port` verilirse (ana ekrandaki baglanti portu)
    eslesme sonrasi ona baglanir; verilmezse mDNS/otomatik denenir.
    """
    return await get_adb_controller().pair_wifi(address, code, connect_port or None)


async def adb_enable_wifi(device_id: str | None = None) -> dict[str, Any]:
    """USB'den bagli cihaz(lar)i kablosuz ADB moduna alir; sonra kablo cekilebilir."""
    return await get_adb_controller().enable_wifi(device_id or None)


async def adb_unlock_device(
    device_id: str | None = None, pin: str | None = None
) -> dict[str, Any]:
    """Belirtilen cihazin (veya None ise bagli TUM cihazlarin) ekranini acar.

    `pin` verilmezse kayitli PIN (CYRAEN_ADB_UNLOCK_PIN) kullanilir.
    """
    return await get_adb_controller().unlock_device(device_id or None, pin or None)


async def adb_set_unlock_pin(pin: str) -> dict[str, Any]:
    """Telefon ekran kilidi PIN'ini kalici olarak kaydeder (cyraen-brain/.env).

    Sonraki acilislarda da gecerli olur; `adb_unlock_device` bu PIN'i otomatik girer.
    """
    return await asyncio.to_thread(_persist_unlock_pin, pin)


async def adb_open(package_or_url: str, device_id: str | None = None) -> dict[str, Any]:
    """Cihaz(lar)da bir uygulamayi veya URL/deep link'i acar."""
    return await get_adb_controller().open_app_or_url(package_or_url, device_id or None)


async def adb_play_media(url_or_query: str, device_id: str | None = None) -> dict[str, Any]:
    """Cihaz(lar)da medya/muzik oynatir (URL veya arama metni)."""
    return await get_adb_controller().play_media(url_or_query, device_id or None)


async def adb_shell(command: str, device_id: str | None = None) -> dict[str, Any]:
    """Cihaz(lar)da serbest `adb shell` komutu calistirir."""
    return await get_adb_controller().execute_raw_shell(command, device_id or None)
