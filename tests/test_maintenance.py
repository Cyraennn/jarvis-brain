"""Disk bakimi (tools/maintenance) - gercek sisteme dokunmadan gecici klasorlerle."""

from __future__ import annotations

import asyncio
import csv
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.maintenance as m

MB = 1024 * 1024


def _file(path: Path, size: int, age_days: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    temp = tmp_path / "Temp"
    cache = tmp_path / "Opera" / "Cache"
    downloads = tmp_path / "Downloads"
    old_tmp = _file(temp / "eski" / "a.tmp", 2 * MB, age_days=3)
    new_tmp = _file(temp / "yeni.tmp", MB)  # 24 saatten yeni -> dokunulmaz
    _file(cache / "Cache_Data" / "f_0001", 3 * MB)
    big = _file(downloads / "Kurulum.exe", 60 * MB, age_days=30)
    _file(downloads / "Taze.exe", 60 * MB)  # yeni -> aday degil
    _file(downloads / "kucuk.zip", MB, age_days=30)  # kucuk -> aday degil
    _file(downloads / "belge.pdf", 80 * MB, age_days=30)  # uzanti degil

    monkeypatch.setattr(m, "cache_roots", lambda: {"temp": [temp], "browser_cache": [cache]})
    monkeypatch.setattr(m, "user_file_roots", lambda: [downloads])
    monkeypatch.setattr(m, "get_settings",
                        lambda: SimpleNamespace(data_dir=tmp_path / "data", obsidian_vault=""))
    monkeypatch.setattr(m, "recycle_bin_info", lambda: {"size_mb": 0, "items": 0})
    recycled: list[Path] = []

    def fake_recycle(p: Path) -> bool:
        recycled.append(p)
        p.unlink()
        return True

    monkeypatch.setattr(m, "send_to_recycle_bin", fake_recycle)
    return SimpleNamespace(temp=temp, cache=cache, old_tmp=old_tmp, new_tmp=new_tmp,
                           big=big, recycled=recycled, data=tmp_path / "data")


def test_scan_is_read_only_and_finds_candidates(env):
    scan = m.cleanup_scan()
    cats = scan["categories"]
    assert cats["temp"]["size_mb"] == pytest.approx(2.0)  # yeni.tmp sayilmaz
    assert cats["browser_cache"]["size_mb"] == pytest.approx(3.0)
    items = cats["installers"]["items"]
    assert [Path(i["path"]).name for i in items] == ["Kurulum.exe"] and items[0]["id"] == "i1"
    assert env.old_tmp.exists() and env.big.exists()
    assert (env.data / "maintenance" / "last_scan.json").is_file()
    assert "GB temizlenebilir" in m.scan_summary(scan)


def test_plan_requires_scan_and_valid_input(env):
    assert "error" in m.plan_cleanup("temp")
    m.cleanup_scan()
    assert "error" in m.plan_cleanup()
    assert "error" in m.plan_cleanup("hepsini_sil")
    plan = m.plan_cleanup("temp", "i1")
    assert plan["cache"] == ["temp"] and len(plan["files"]) == 1
    assert "COP KUTUSUNA: Kurulum.exe" in m.describe_plan(plan)


def test_run_cleans_cache_and_recycles_files(env):
    m.cleanup_scan()
    out = m.cleanup_run("temp,browser_cache", "i1")
    assert out["status"] == "tamam"
    assert not env.old_tmp.exists()
    assert env.new_tmp.exists()  # taze gecici dosya korunur
    assert env.temp.is_dir() and env.cache.is_dir()  # kokler silinmez
    assert env.recycled == [env.big]
    rows = list(csv.DictReader(open(out["manifest"], encoding="utf-8")))
    assert {r["islem"] for r in rows} == {"silindi", "cop_kutusu"}


def test_confirm_denied_deletes_nothing(env):
    from tools.tool_runner import ToolRunner

    m.cleanup_scan()
    prompts: list[str] = []
    runner = ToolRunner(confirm=lambda p: prompts.append(p) or False)
    import tools.tool_runner as tr

    res = runner._registry["cleanup_run"](categories="temp", ids="i1")
    assert res["status"] == "iptal edildi"
    assert env.old_tmp.exists() and env.big.exists()
    assert "Kurulum.exe" in prompts[0]
    assert runner._registry["empty_recycle_bin"]()["status"] == "iptal edildi"
    assert tr.cleanup_run is m.cleanup_run


def test_protected_paths(monkeypatch, tmp_path):
    from config.settings import APP_DIR

    assert m.is_protected(APP_DIR / "core" / "brain_engine.py")
    assert m.is_protected(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    assert m.is_protected(tmp_path / ".git" / "x")
    assert not m.is_protected(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp" / "x.tmp")
    assert not m.is_protected(tmp_path / "Downloads" / "x.exe")


def test_installers_inside_protected_roots_are_skipped(env, monkeypatch):
    monkeypatch.setattr(m, "is_protected", lambda p: p.name == "Kurulum.exe")
    assert m.find_installers() == []


def test_agent_capability_is_read_only():
    from agents.agent_tools import CAPABILITIES
    from agents.departments import all_agents

    names = {f.__name__ for f in CAPABILITIES["maintenance"]}
    assert names == {"cleanup_scan"}
    assert "bakim_teknisyeni" in all_agents()


def test_health_alert_includes_cleanup_hint(env, monkeypatch):
    from core.scheduler_handler import SchedulerHandler

    sent: list[str] = []

    class Bc:
        async def broadcast(self, text, channels=None):
            sent.append(text)

    settings = SimpleNamespace(data_dir=env.data, morning_briefing_time="", daily_summary_time="",
                               health_cpu_alert=99,
                               health_mem_alert=99, health_disk_alert=50)
    env.data.mkdir(parents=True, exist_ok=True)
    h = SchedulerHandler(settings, broadcaster=Bc())
    monkeypatch.setattr(h, "system_snapshot",
                        lambda: {"cpu": 1, "mem": 1, "disk": 95, "brain_session": None})
    monkeypatch.setattr(m, "scan_summary", lambda scan: "~9.0 GB temizlenebilir")
    real_scan = m.cleanup_scan
    monkeypatch.setattr(m, "cleanup_scan", lambda: {**real_scan(), "reclaimable_mb": 9000})
    asyncio.run(h.health_check())
    assert sent and "temizlik yap" in sent[0] and "Disk %95" in sent[0]
