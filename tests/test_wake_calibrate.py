"""Uyandirma esigi onerisi (mikrofonsuz, saf hesap)."""
from scripts.wake_calibrate import suggest_threshold


def test_threshold_between_background_and_weakest_trigger():
    value, note = suggest_threshold([0.01, 0.12, 0.2], [0.9, 0.7, 0.95])
    assert value == 0.45 and "3/3" in note


def test_missed_tries_are_reported_and_ignored():
    value, note = suggest_threshold([0.3], [0.9, 0.1])
    assert value == 0.6 and "1/2" in note and "Kacan" in note


def test_inseparable_triggers_warn_and_keep_default():
    assert suggest_threshold([0.6], [0.5, 0.4]) == (0.5, suggest_threshold([0.6], [])[1])
    assert "UYARI" in suggest_threshold([0.6], [0.5])[1]


def test_threshold_is_clamped():
    assert suggest_threshold([0.0], [0.1])[0] == 0.2
    assert suggest_threshold([0.97], [0.99])[0] == 0.8
