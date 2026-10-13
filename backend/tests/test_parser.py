from app.parser import parse_line


def test_parses_iso_application_line():
    event = parse_line("2026-02-03T10:11:12Z ERROR [payments] [checkout.py] charge timed out")
    assert event["severity"] == "ERROR"
    assert event["service"] == "payments"
    assert event["source"] == "checkout.py"
    assert event["message"] == "charge timed out"
    assert event["timestamp"].isoformat() == "2026-02-03T10:11:12+00:00"


def test_parses_severity_first_line_without_a_timestamp():
    event = parse_line("ERROR [api] [main.py] request failed")
    assert event["severity"] == "ERROR"
    assert event["service"] == "api"
    assert event["source"] == "main.py"
    assert event["message"] == "request failed"


def test_parses_apache_status_and_preserves_unknown_lines():
    access = parse_line('127.0.0.1 - - [03/Feb/2026:10:11:12 +0000] "GET /health HTTP/1.1" 503 12')
    assert access["severity"] == "ERROR"
    assert access["service"] == "web"
    raw = parse_line("gibberish but useful for investigation")
    assert raw["severity"] == "UNKNOWN"
    assert raw["message"] == "gibberish but useful for investigation"


def test_parses_syslog_line():
    event = parse_line("Feb  3 10:11:12 edge-01 nginx: upstream error: connection refused")
    assert event["service"] == "nginx"
    assert event["source"] == "edge-01"
    assert event["severity"] == "ERROR"


def test_malformed_syslog_shaped_input_remains_visible():
    line = "Xyz 99 25:91:77 edge-01 nginx: malformed timestamp"
    event = parse_line(line)
    assert event["severity"] == "UNKNOWN"
    assert event["message"] == line
