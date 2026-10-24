"""scripts/export_lab_package.py: dosya filtreleme + token uretimi/idempotency +
.env birlestirme mantigi - gercek zip/proje agacina dokunmadan (tmp_path)."""
from pathlib import Path

from scripts.export_lab_package import (
    _iter_code_files,
    _parse_env_lines,
    build_lab_env_text,
    ensure_remote_client_tokens,
)


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_iter_code_files_excludes_venv_pycache_and_pyc(tmp_path):
    base = tmp_path / "cyraen-brain"
    _touch(base / "core" / "brain_engine.py")
    _touch(base / ".venv" / "Lib" / "site-packages" / "foo.py")
    _touch(base / "__pycache__" / "brain_engine.cpython-312.pyc")
    _touch(base / "core" / "__pycache__" / "x.pyc")
    _touch(base / "build" / "artifact.txt")
    _touch(base / "dist" / "CYRAEN.exe")
    _touch(base / "core" / "compiled.pyc")

    rels = {rel.as_posix() for _, rel in _iter_code_files(base, include_whatsapp_session=True)}
    # build/ ve dist/ de haric (PyInstaller ciktisi, kaynak degil)
    assert rels == {"core/brain_engine.py"}


def test_iter_code_files_excludes_whatsapp_session_by_default(tmp_path):
    base = tmp_path / "cyraen-brain"
    _touch(base / "data" / "notes.md")
    _touch(base / "data" / "whatsapp_session" / "Default" / "History")
    _touch(base / "config" / "whatsapp.json")

    rels = {rel.as_posix() for _, rel in _iter_code_files(base, include_whatsapp_session=False)}
    assert rels == {"data/notes.md", "config/whatsapp.json"}

    rels_incl = {rel.as_posix() for _, rel in _iter_code_files(base, include_whatsapp_session=True)}
    assert "data/whatsapp_session/Default/History" in rels_incl


def test_parse_env_lines_ignores_comments_and_blank():
    lines = ["# yorum", "", "A=1", "  B = 2 ", "BOZUK_SATIR", "C=with=equals"]
    values = _parse_env_lines(lines)
    assert values == {"A": "1", "B": "2", "C": "with=equals"}


def test_ensure_remote_client_tokens_generates_when_missing(tmp_path):
    web, audio = ensure_remote_client_tokens(remote_client_dir=tmp_path)
    assert web and audio and web != audio

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"CYRAEN_WEB_TOKEN={web}" in env_text
    assert f"CYRAEN_REMOTE_AUDIO_TOKEN={audio}" in env_text
    assert "CYRAEN_SERVER_HOST=" in env_text


def test_ensure_remote_client_tokens_is_idempotent(tmp_path):
    web1, audio1 = ensure_remote_client_tokens(remote_client_dir=tmp_path)
    web2, audio2 = ensure_remote_client_tokens(remote_client_dir=tmp_path)
    assert (web1, audio1) == (web2, audio2)


def test_ensure_remote_client_tokens_preserves_server_host(tmp_path):
    ensure_remote_client_tokens(remote_client_dir=tmp_path)
    env_path = tmp_path / ".env"
    text = env_path.read_text(encoding="utf-8").replace(
        "CYRAEN_SERVER_HOST=", "CYRAEN_SERVER_HOST=lab-pc.tailxxxx.ts.net"
    )
    env_path.write_text(text, encoding="utf-8")

    ensure_remote_client_tokens(remote_client_dir=tmp_path)
    assert "CYRAEN_SERVER_HOST=lab-pc.tailxxxx.ts.net" in env_path.read_text(encoding="utf-8")


def test_build_lab_env_text_appends_and_overrides(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GEMINI_API_KEY=real-key\nCYRAEN_WEB_TOKEN=eski-token\n", encoding="utf-8"
    )

    text = build_lab_env_text("yeni-web-token", "yeni-audio-token", env_path=env_path)

    assert "GEMINI_API_KEY=real-key" in text
    assert "CYRAEN_AUDIO_MODE=network" in text
    assert "CYRAEN_WEB_BIND=0.0.0.0" in text
    assert "CYRAEN_OBSIDIAN_VAULT=C:\\CYRAEN\\Hafiza" in text
    # dotenv semantigi: son satir kazanir - hem eski hem yeni CYRAEN_WEB_TOKEN satiri
    # metinde olabilir ama SIRALAMADA yeni deger EN SONDA olmali.
    last_token_line = [
        ln for ln in text.splitlines() if ln.startswith("CYRAEN_WEB_TOKEN=")
    ][-1]
    assert last_token_line == "CYRAEN_WEB_TOKEN=yeni-web-token"


def test_build_lab_env_text_handles_missing_base_env(tmp_path):
    text = build_lab_env_text("w", "a", env_path=tmp_path / "does-not-exist.env")
    assert "CYRAEN_AUDIO_MODE=network" in text
    assert "CYRAEN_WEB_TOKEN=w" in text
