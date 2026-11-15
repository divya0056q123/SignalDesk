from datetime import datetime, timedelta

from app.anomaly import detect_anomalies, static_threshold_baseline


def series(values):
    start = datetime(2026, 1, 1)
    return [{"bucket": start + timedelta(minutes=i), "errors": v, "total": v} for i, v in enumerate(values)]


def test_flags_a_clear_spike_but_not_normal_noise():
    points = series([2, 3, 2, 1, 3, 2, 2, 3, 2, 1, 2, 3, 25, 2, 3])
    found = detect_anomalies(points, "errors")
    assert [a["observed"] for a in found] == [25]
    assert found[0]["level"] == "high"
    assert found[0]["expected"] == 2.0


def test_needs_history_before_judging():
    assert detect_anomalies(series([0, 0, 50]), "errors") == []


def test_tiny_absolute_changes_are_ignored():
    assert detect_anomalies(series([0] * 10 + [2] + [0] * 3), "errors") == []


def test_earlier_incident_does_not_hide_the_next_one():
    points = series([2, 2, 3, 2, 2, 2, 30, 2, 2, 3, 2, 28, 2])
    assert [a["observed"] for a in detect_anomalies(points, "errors")] == [30, 28]


def test_static_baseline_is_kept_for_comparison():
    assert static_threshold_baseline(series([1, 1, 1, 1, 40]), "errors") == [4]
