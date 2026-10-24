"""Beyin motoru olay gozlemcisi (observer) sozlesmesi.

`BrainEngine` calisirken onemli olaylari bu arayuz uzerinden yayinlar. Varsayilan
implementasyon hicbir sey yapmaz; arayuz (UI) katmani alt sinif turetip Qt sinyallerine
koprular. Tum metotlar motorun kendi thread'inden cagrilabilir, bu yuzden
implementasyonlar thread-safe olmalidir.
"""

from __future__ import annotations


class EngineObserver:
    """No-op taban gozlemci. Override edilmeyen her metot sessizce yok sayilir."""

    # --- baglanti durumu: "connecting" | "active" | "reconnecting" | "offline" |
    #     "offline-voice" (internet yok, yerel sesli sohbet dinliyor) | "closed"
    def on_connection(self, status: str) -> None:
        pass

    # --- konusma durumu: "idle" | "listening" | "speaking"
    def on_state(self, state: str) -> None:
        pass

    # --- 0.0 - 1.0 arasi anlik mikrofon ses seviyesi
    def on_input_level(self, level: float) -> None:
        pass

    # --- 0.0 - 1.0 arasi anlik hoparlor (model sesi) seviyesi
    def on_output_level(self, level: float) -> None:
        pass

    # --- kullanici transkripti (final=False => kismi/canli, True => tamamlandi)
    def on_user_transcript(self, text: str, final: bool) -> None:
        pass

    # --- asistan transkripti (final=False => kismi/canli, True => tamamlandi)
    def on_assistant_transcript(self, text: str, final: bool) -> None:
        pass

    # --- model bir veya daha fazla araci cagirdi
    def on_tool_call(self, names: list[str]) -> None:
        pass

    # --- arac sonucu dondu
    def on_tool_result(self, name: str, ok: bool, detail: str) -> None:
        pass

    # --- harici ajan koprusunden mesaj enjekte edildi
    def on_bridge_message(self, text: str) -> None:
        pass

    # --- kullanicidan onay iste (evet/hayir). Motor thread'inden BLOKLAYARAK cagrilir.
    #     Varsayilan (arayuzsuz mod): sozlu onay modelin sorumlulugundadir -> gec.
    #     Arayuz katmani bunu gercek bir onay diyaloguyla override eder.
    def confirm(self, prompt: str) -> bool:
        return True

    # --- model uygulamanin tamamen kapanmasini istedi (kendini kapatma)
    def on_exit_request(self) -> None:
        pass

    # --- baska bir pencereye yazi yaziliyor (arayuz gecici olarak cekilebilir)
    def on_external_typing(self, active: bool) -> None:
        pass

    # --- icerik paneli (tools/panel_tools.py): {"kind": "video|wiki|doc|web|spotify|news|chart|weather|info|close", ...}.
    #     Arayuz paneli gosterebiliyorsa True doner; False ise arac icerigi varsayilan
    #     uygulamada/tarayicida acar (arayuzsuz mod).
    def on_panel(self, payload: dict) -> bool:
        return False

    def on_wake(self, awake: bool) -> None:
        """Uyandirma kelimesi kapisi: True = dinliyor (uyandi / kapi kapali), False = uykuda."""
        pass

    def on_persona(self, key: str) -> None:
        """Kisilik modu degisti: "jarvis" | "friday" | "ultron" (core/personas.py)."""
        pass
