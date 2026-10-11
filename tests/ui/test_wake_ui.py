"""Uyandirma kelimesi arayuzu: dugme -> worker, uyku durumu metni, cip genislik butcesi."""


class FakeWorker:
    def __init__(self) -> None:
        self.wake: list[bool] = []

    def set_wake_word_enabled(self, enabled: bool) -> None:
        self.wake.append(enabled)


def test_wake_toggle_reaches_worker_and_shows_sleep(main_window, monkeypatch):
    w = main_window
    w._wake_btn.setChecked(False)  # .env'de JARVIS_WAKE_WORD=true olsa da kapali basla
    worker = FakeWorker()
    monkeypatch.setattr(w, "_worker", worker)
    chimes = []
    monkeypatch.setattr("ui.sound.play_chime", lambda: chimes.append(1))

    w._wake_btn.setChecked(True)
    assert worker.wake == [True]

    w._on_wake(False)  # motor: uykuda
    assert "UYKUDA" in w._state_line.text()
    w._on_state("idle")
    assert "UYKUDA" in w._state_line.text()  # idle uyku metnini ezmez

    w._on_wake(True)  # "Hey JARVIS"
    assert chimes == [1]
    assert "UYKUDA" not in w._state_line.text()

    w._wake_btn.setChecked(False)
    assert worker.wake == [True, False]
    assert "UYKUDA" not in w._state_line.text()
