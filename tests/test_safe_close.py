"""Guvenli pencere kapatma: kapatma kisayollari onayli, onay gercek hedefi gosterir, geri acma."""

from __future__ import annotations

import pytest

from tools import tool_runner as tr
from tools.keyboard_input import is_close_combo
from tools.tool_runner import ToolRunner
from tools.window_control import is_protected_exe

NOTEPAD = {"hwnd": 11, "title": "notlar.txt - Not Defteri", "exe": "notepad.exe",
           "exe_path": r"C:\Windows\notepad.exe"}
TERMINAL = {"hwnd": 22, "title": "claude", "exe": "windowsterminal.exe",
            "exe_path": r"C:\wt\WindowsTerminal.exe"}
JARVIS = {"hwnd": 33, "title": "J.A.R.V.I.S.", "exe": "pythonw.exe", "exe_path": r"C:\py\pythonw.exe"}


class Harness:
    def __init__(self, monkeypatch, *, approve: bool, foreground: dict | None = None) -> None:
        self.prompts: list[str] = []
        self.sent: list[tuple] = []
        self.approve = approve

        def confirm(prompt: str) -> bool:
            self.prompts.append(prompt)
            return self.approve

        monkeypatch.setattr(tr, "describe_window", lambda hwnd=0: dict(foreground or {}))
        monkeypatch.setattr(tr, "press_keys", self._rec("press_keys", {"status": "gonderildi"}))
        monkeypatch.setattr(tr, "close_window", self._rec("close_window", {"status": "kapatma istegi gonderildi"}))
        monkeypatch.setattr(tr, "close_active_tab", self._rec("close_active_tab", {"status": "aktif sekme kapatildi"}))
        monkeypatch.setattr(tr, "_close_app", self._rec("taskkill", {"status": "kapatma istegi gonderildi"}))
        monkeypatch.setattr(tr, "open_path", self._rec("open_path", {"status": "acildi"}))
        self.runner = ToolRunner(confirm=confirm)

    def _rec(self, name: str, result: dict):
        def fn(*args, **kwargs):
            self.sent.append((name, args, kwargs))
            return dict(result)
        return fn


@pytest.mark.parametrize("keys", ["alt+f4", "Alt + F4", "ctrl+w", "control+w", "ctrl+shift+w", "ctrl+f4", "ctrl+q"])
def test_close_combos_detected(keys):
    assert is_close_combo(keys)


@pytest.mark.parametrize("keys", ["ctrl+s", "enter", "alt+tab", "f4", "w", "", "ctrl+shift+n"])
def test_ordinary_keys_are_not_close_combos(keys):
    assert not is_close_combo(keys)


def test_protected_exes():
    assert is_protected_exe("explorer.exe") and is_protected_exe("PythonW.exe")
    assert not is_protected_exe("notepad.exe")


def test_ordinary_shortcut_needs_no_confirmation(monkeypatch):
    h = Harness(monkeypatch, approve=False, foreground=TERMINAL)
    assert h.runner._tool_press_keys("ctrl+s") == {"status": "gonderildi"}
    assert h.prompts == [] and h.sent == [("press_keys", ("ctrl+s",), {})]


def test_alt_f4_shows_real_target_and_is_not_sent_when_declined(monkeypatch):
    # 6 Ekim olayi: model alt+f4 gonderdi, odakta Claude Code terminali vardi.
    h = Harness(monkeypatch, approve=False, foreground=TERMINAL)
    result = h.runner._tool_press_keys("alt+f4")
    assert result["status"] == "iptal edildi" and result["window"] == "claude"
    assert "claude" in h.prompts[0] and "windowsterminal.exe" in h.prompts[0]
    assert h.sent == []


def test_alt_f4_sent_to_the_confirmed_window_only(monkeypatch):
    h = Harness(monkeypatch, approve=True, foreground=NOTEPAD)
    result = h.runner._tool_press_keys("alt+f4")
    assert result["window"] == NOTEPAD["title"]
    assert h.sent == [("press_keys", ("alt+f4",), {"hwnd": 11})]  # odak onaylanan pencereye


def test_close_combo_refused_on_protected_or_missing_window(monkeypatch):
    h = Harness(monkeypatch, approve=True, foreground=JARVIS)
    assert "korumali" in h.runner._tool_press_keys("alt+f4")["error"]
    assert "korumali" in h.runner._tool_close_active_tab()["error"]
    h2 = Harness(monkeypatch, approve=True, foreground=None)
    assert "error" in h2.runner._tool_press_keys("ctrl+w")
    assert h.prompts == [] and h.sent == [] and h2.sent == []


def test_close_active_tab_prompt_names_the_window(monkeypatch):
    h = Harness(monkeypatch, approve=True, foreground=NOTEPAD)
    h.runner._tool_close_active_tab()
    assert NOTEPAD["title"] in h.prompts[0]
    assert h.sent == [("close_active_tab", (), {"restore_hwnd": 11})]


def test_close_application_closes_only_the_matching_window(monkeypatch):
    h = Harness(monkeypatch, approve=True)
    monkeypatch.setattr(tr, "find_close_target", lambda name, hint="": {**NOTEPAD, "siblings": []})
    result = h.runner._tool_close_application("not defteri")
    assert NOTEPAD["title"] in h.prompts[0]
    assert h.sent == [("close_window", (11,), {})] and result["window"] == NOTEPAD["title"]


def test_close_application_by_title_never_kills_the_whole_process(monkeypatch):
    # "Ayarlar" bir pencere basligi; ayni exe'nin baska pencereleri olsa da yalniz o kapanir
    settings = {"hwnd": 44, "title": "Ayarlar", "exe": "applicationframehost.exe", "exe_path": "x"}
    h = Harness(monkeypatch, approve=True)
    monkeypatch.setattr(tr, "find_close_target",
                        lambda name, hint="": {**settings, "siblings": ["Hesap Makinesi"]})
    h.runner._tool_close_application("Ayarlar")
    assert h.sent == [("close_window", (44,), {})]


def test_close_application_with_many_windows_lists_them(monkeypatch):
    h = Harness(monkeypatch, approve=False)
    monkeypatch.setattr(tr, "find_close_target",
                        lambda name, hint="": {**NOTEPAD, "siblings": ["baska.txt - Not Defteri"]})
    result = h.runner._tool_close_application("notepad")
    assert result["status"] == "iptal edildi" and h.sent == []
    assert "TUM pencereleri (2)" in h.prompts[0] and "baska.txt" in h.prompts[0]


def test_close_application_refuses_protected_window(monkeypatch):
    h = Harness(monkeypatch, approve=True)
    monkeypatch.setattr(tr, "find_close_target", lambda name, hint="": {**JARVIS, "siblings": []})
    assert "korumali" in h.runner._tool_close_application("jarvis penceresi")["error"]
    assert h.sent == [] and h.prompts == []


def test_reopen_last_closed(monkeypatch):
    h = Harness(monkeypatch, approve=True, foreground=NOTEPAD)
    assert "error" in h.runner._tool_reopen_last_closed()  # henuz bir sey kapatilmadi
    h.runner._tool_press_keys("alt+f4")
    h.sent.clear()
    result = h.runner._tool_reopen_last_closed()
    assert h.sent == [("open_path", (NOTEPAD["exe_path"],), {})]
    assert result["window"] == NOTEPAD["title"] and "geri gelmeyebilir" in result["note"]


def test_declined_close_is_not_remembered(monkeypatch):
    h = Harness(monkeypatch, approve=False, foreground=NOTEPAD)
    h.runner._tool_press_keys("alt+f4")
    assert "error" in h.runner._tool_reopen_last_closed()
