from datetime import datetime, timedelta

from app.clustering import cluster_events, mask


def event(i, severity, service, message):
    return {"id": i, "timestamp": datetime(2026, 1, 1) + timedelta(seconds=i),
            "severity": severity, "service": service, "message": message}


def test_variable_parts_are_masked():
    assert mask("timeout after 5s for 10.0.0.1:8080 id=42") == ["timeout", "after", "<*>", "for", "<*>", "id=<*>"]


def test_similar_messages_collapse_into_one_template():
    events = [event(i, "ERROR", "payments", f"provider timeout after {i}s order={900 + i}") for i in range(25)]
    events += [event(100 + i, "INFO", "api", f"request completed latency={i}ms") for i in range(10)]
    result = cluster_events(events)
    assert len(result) == 2
    assert result[0]["count"] == 25 and result[0]["severity"] == "ERROR"
    assert result[0]["services"] == ["payments"]


def test_severe_patterns_rank_above_noisy_info():
    events = [event(i, "INFO", "api", "heartbeat ok") for i in range(50)]
    events += [event(100, "CRITICAL", "db", "disk full on /var/lib")]
    assert cluster_events(events)[0]["severity"] == "CRITICAL"
