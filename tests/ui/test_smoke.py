"""HUD duman testi: pencere kurulur, olaylar islenir, cizim bos degil."""
from tests.ui.conftest import wait_ms


def test_window_builds_and_renders(qapp, main_window):
    main_window.show()
    wait_ms(qapp, 300)
    img = main_window.grab().toImage()
    assert img.width() >= 1300 and img.height() >= 800
    assert not img.isNull()


def test_observer_events_update_status(qapp, main_window):
    main_window.show()
    obs = main_window._observer
    obs.connection.emit("active")
    obs.state.emit("listening")
    wait_ms(qapp, 100)
    assert "bağlı" in main_window._sb_conn.text().lower()
