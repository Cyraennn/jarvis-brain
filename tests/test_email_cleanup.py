"""tools/email_cleanup - agsiz testler (kurallar, LLM cevabi, CSV, klasor bulma)."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone

from tools.email_cleanup import (
    Mail, apply_llm_answer, classify_rules, special_folders, summarize, write_csv,
)

NOW = datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=30)


def _mail(uid="1", **kw):
    base = dict(uid=uid, sender="Magaza", sender_addr="news@shop.com", subject="Kampanya",
                date=OLD, category="promotions", unsubscribe=True)
    base.update(kw)
    return Mail(**base)


def test_promo_with_unsubscribe_is_deleted_by_rule():
    m = _mail()
    assert classify_rules([m], set(), NOW) == []
    assert m.decision == "sil"


def test_protections_keep_mail():
    cases = [
        _mail("1", flagged=True),
        _mail("2", important=True),
        _mail("3", date=NOW - timedelta(days=2)),
        _mail("4", date=None),
        _mail("5", sender_addr="hoca@ege.edu.tr"),
        _mail("6", subject="Siparişiniz kargoya verildi"),
        _mail("7", sender_addr="friend@gmail.com"),
    ]
    pending = classify_rules(cases, {"friend@gmail.com"}, NOW)
    assert pending == []
    assert all(m.decision == "tut" for m in cases), [(m.uid, m.reason) for m in cases]


def test_uncertain_goes_to_llm():
    m = _mail(category="updates", unsubscribe=False)
    assert classify_rules([m], set(), NOW) == [m]
    assert m.decision == ""


def test_llm_answer_missing_or_broken_means_keep():
    batch = [_mail("1"), _mail("2"), _mail("3")]
    apply_llm_answer(batch, '[{"i":0,"karar":"sil","neden":"reklam"},{"i":1,"karar":"tut"}]')
    assert [m.decision for m in batch] == ["sil", "tut", "tut"]
    other = [_mail("4")]
    apply_llm_answer(other, "bozuk cevap")
    assert other[0].decision == "tut"


def test_csv_and_summary(tmp_path):
    a, b = _mail("1", decision="sil", reason="r"), _mail("2", decision="tut", reason="r")
    path = write_csv(tmp_path / "x.csv", [a, b])
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [r["karar"] for r in rows] == ["sil", "tut"]
    assert "2 mail okundu: 1 Cop kutusuna tasindi, 1 tutuldu" in summarize([a, b])


def test_special_folders_from_list_flags():
    class FakeConn:
        def list(self):
            return "OK", [b'(\\HasNoChildren \\Trash) "/" "[Gmail]/&AMcA9g-p kutusu"',
                          b'(\\HasNoChildren \\Sent) "/" "[Gmail]/G&APY-nderilmi&AV8- Postalar"',
                          b'(\\HasNoChildren) "/" "INBOX"']
    f = special_folders(FakeConn())
    assert f["trash"] == '"[Gmail]/&AMcA9g-p kutusu"'
    assert f["sent"].startswith('"[Gmail]/G')


def test_pace_delay_spreads_remaining_time():
    from tools.email_cleanup import pace_delay

    now = datetime(2026, 10, 5, 1, 0)
    assert pace_delay(now, datetime(2026, 10, 5, 7, 0), 60) == 360.0
    assert pace_delay(now, None, 10) == 0.0
    assert pace_delay(now, datetime(2026, 10, 5, 0, 30), 5) == 0.0
