"""CANLI klavye testi (Windows, gercek SendInput). Yalnizca CYRAEN_LIVE_TESTS=1 ile calisir.

Kendi olusturdugu bir Tk penceresine yazar; baska uygulamalara dokunmaz. Test
sirasinda klavye/fareye dokunmayin.
"""
import os
import subprocess
import sys
import textwrap
import time

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("CYRAEN_LIVE_TESTS") != "1",
    reason="canli test: CYRAEN_LIVE_TESTS=1 ve Windows gerekir",
)

from tools import keyboard_input as kb  # noqa: E402

TITLE = "CYRAEN_TYPE_TEST_WINDOW"

TK_APP = textwrap.dedent(
    '''
    import sys, tkinter as tk
    out = sys.argv[1]
    root = tk.Tk(); root.title("%s"); root.geometry("500x300+200+200")
    t = tk.Text(root); t.pack(fill="both", expand=True); t.focus_set()
    def dump():
        open(out, "w", encoding="utf-8", errors="replace").write(t.get("1.0", "end-1c"))
        root.destroy()
    root.after(int(sys.argv[2]) * 1000, dump)
    root.mainloop()
    '''
    % TITLE
)


def _run_app(tmp_path, seconds=14):
    script = tmp_path / "tkapp.py"
    script.write_text(TK_APP, encoding="utf-8")
    out = tmp_path / "out.txt"
    proc = subprocess.Popen([sys.executable, str(script), str(out), str(seconds)])
    assert kb._wait_for(lambda: kb.find_window(TITLE), 8.0), "test penceresi acilmadi"
    time.sleep(0.6)
    return proc, out


def _finish(proc, out):
    proc.wait(timeout=30)
    return out.read_text(encoding="utf-8")


def test_types_turkish_tab_newline_into_target(tmp_path):
    proc, out = _run_app(tmp_path)
    text = "Merhaba Şğüİıö çĞ\tsekme\nikinci satır {}[]"
    res = kb.type_text(text, app=TITLE, exe_hint=os.path.basename(sys.executable), per_char=0.01)
    got = _finish(proc, out)
    assert res.get("status") == "yazildi", res
    assert got == text


def test_refuses_to_type_when_target_window_missing():
    res = kb.type_text("x", app="BU_PENCERE_YOK_12345")
    assert "error" in res


def test_concurrent_calls_do_not_interleave(tmp_path):
    import threading

    proc, out = _run_app(tmp_path, seconds=16)
    hwnd = kb.find_window(TITLE)
    assert kb.focus_window(hwnd)
    a, b = "A" * 40, "B" * 40
    ts = [
        threading.Thread(target=kb.type_text, args=(a,), kwargs={"per_char": 0.01}),
        threading.Thread(target=kb.type_text, args=(b,), kwargs={"per_char": 0.01}),
    ]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    got = _finish(proc, out)
    assert sorted([got[:40], got[40:]]) == [a, b], got
