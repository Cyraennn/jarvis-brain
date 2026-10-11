"""Spotify araclari - agsiz testler (spotipy istemcisi sahte)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.agent_tools import build_callables
from tools import spotify_tool
from tools.tool_declarations import build_declarations
from tools.tool_runner import ToolRunner

SPOTIFY_TOOLS = {"spotify_play", "spotify_control", "spotify_now_playing", "spotify_queue",
                 "spotify_volume", "spotify_devices"}

PC = {"id": "pc1", "name": "SEZAI-PC", "type": "Computer", "is_active": False, "volume_percent": 50}
PHONE = {"id": "ph1", "name": "Pixel", "type": "Smartphone", "is_active": True, "volume_percent": 80}
TRACK = {"name": "Danza Kuduro", "uri": "spotify:track:abc", "artists": [{"name": "Don Omar"}],
         "album": {"name": "Meet the Orphans", "uri": "spotify:album:m1"}, "duration_ms": 198000}


class FakeSpotify:
    def __init__(self, devices=None, results=None):
        self._devices = list(devices or [])
        self._results = results if results is not None else [TRACK]
        self.calls: list[tuple] = []

    def devices(self):
        return {"devices": self._devices}

    def search(self, q, type, limit):
        self.calls.append(("search", q, type))
        return {type + "s": {"items": self._results}}

    def start_playback(self, device_id=None, uris=None, context_uri=None, offset=None):
        self.calls.append(("play", device_id, uris, context_uri, offset))

    def pause_playback(self):
        self.calls.append(("pause",))

    def next_track(self):
        self.calls.append(("next",))

    def add_to_queue(self, uri):
        self.calls.append(("queue", uri))

    def volume(self, v, device_id=None):
        self.calls.append(("volume", v))

    def current_playback(self):
        return {"is_playing": True, "progress_ms": 65000, "item": TRACK, "device": PC,
                "shuffle_state": False}


@pytest.fixture
def fake(monkeypatch):
    sp = FakeSpotify(devices=[PC])
    monkeypatch.setattr(spotify_tool, "spotify_enabled", lambda: True)
    monkeypatch.setattr(spotify_tool, "_client", lambda: sp)
    monkeypatch.setattr(spotify_tool, "get_settings",
                        lambda: SimpleNamespace(spotify_default_device=""))
    return sp


def test_registered_declared_and_capability():
    assert SPOTIFY_TOOLS <= {d.name for d in build_declarations()}
    assert SPOTIFY_TOOLS <= set(ToolRunner().tool_names)
    assert {f.__name__ for f in build_callables(["spotify"])} == SPOTIFY_TOOLS


def test_muzik_dj_has_spotify():
    from agents.departments import gunluk

    dj = next(a for a in gunluk.DEPARTMENT.agents if a.name == "muzik_dj")
    assert "spotify" in dj.capabilities


def test_not_configured_returns_error(monkeypatch):
    monkeypatch.setattr(spotify_tool, "spotify_enabled", lambda: False)
    for fn in (spotify_tool.spotify_play, spotify_tool.spotify_now_playing, spotify_tool.spotify_devices):
        assert "error" in fn()


def test_play_searches_and_plays_track(fake):
    r = spotify_tool.spotify_play("danza kuduro")
    assert r["ok"] and r["playing"] == "Danza Kuduro - Don Omar" and r["device"] == "SEZAI-PC"
    assert ("play", "pc1", None, "spotify:album:m1", {"uri": "spotify:track:abc"}) in fake.calls


def test_play_playlist_uses_context(fake):
    fake._results = [{"name": "Chill", "uri": "spotify:playlist:p1"}]
    r = spotify_tool.spotify_play("chill", kind="playlist")
    assert r["ok"] and ("play", "pc1", None, "spotify:playlist:p1", None) in fake.calls


def test_empty_query_resumes(fake):
    r = spotify_tool.spotify_play("")
    assert r["playing"] == "devam" and ("play", "pc1", None, None, None) in fake.calls
    assert not any(c[0] == "search" for c in fake.calls)


def test_no_results(fake):
    fake._results = []
    assert "error" in spotify_tool.spotify_play("asdfgh")


def test_device_selection_prefers_active_then_named(fake):
    fake._devices = [PC, PHONE]
    spotify_tool.spotify_play("x")
    assert fake.calls[-1][1] == "ph1"           # aktif cihaz
    spotify_tool.spotify_play("x", device="pc")
    assert fake.calls[-1][1] == "pc1"
    assert "error" in spotify_tool.spotify_play("x", device="mutfak")


def test_no_device_launches_app_and_waits(fake, monkeypatch):
    fake._devices = []
    launched = []

    def launch():
        launched.append(True)
        fake._devices = [PC]
        return True

    monkeypatch.setattr(spotify_tool, "_launch_desktop_app", launch)
    monkeypatch.setattr(spotify_tool.time, "sleep", lambda s: None)
    r = spotify_tool.spotify_play("danza kuduro")
    assert launched and r["ok"] and r["device"] == "SEZAI-PC"


def test_no_device_and_launch_fails(fake, monkeypatch):
    fake._devices = []
    monkeypatch.setattr(spotify_tool, "_launch_desktop_app", lambda: False)
    assert "error" in spotify_tool.spotify_play("x")


def test_control_queue_volume_now_playing(fake):
    assert spotify_tool.spotify_control("pause")["ok"]
    assert spotify_tool.spotify_control("next")["ok"]
    assert "error" in spotify_tool.spotify_control("explode")
    assert spotify_tool.spotify_queue("danza")["queued"] == "Danza Kuduro - Don Omar"
    assert spotify_tool.spotify_volume(150)["volume"] == 100
    assert "error" in spotify_tool.spotify_volume("yuksek")
    now = spotify_tool.spotify_now_playing()
    assert now["track"] == "Danza Kuduro" and now["progress"] == "1:05 / 3:18"
    assert ("pause",) in fake.calls and ("next",) in fake.calls and ("volume", 100) in fake.calls


def test_premium_403_message(fake, monkeypatch):
    class Err(Exception):
        http_status = 403
        reason = "PREMIUM_REQUIRED"

    def boom():
        raise Err("forbidden")

    monkeypatch.setattr(fake, "pause_playback", boom)
    assert "Premium" in spotify_tool.spotify_control("pause")["error"]
