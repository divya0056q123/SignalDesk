from fastapi.testclient import TestClient

from app.main import create_app


def test_filters_and_validates_log_queries(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        assert client.get("/api/logs").status_code == 200
        upload = client.post(
            "/api/logs/upload",
            files={"file": ("filters.txt", b"INFO [api] [main.py] ready\nERROR [worker] [jobs.py] timeout")},
        )
        assert upload.status_code == 200
        errors = client.get("/api/logs", params={"severity": "ERROR", "service": "worker", "search": "timeout"}).json()
        assert len(errors) == 1
        assert errors[0]["message"] == "timeout"
        assert client.get("/api/logs", params={"service": "missing-service"}).json() == []
        invalid = client.get("/api/logs", params={"severity": "BOGUS"})
        assert invalid.status_code == 422
        invalid_range = client.get(
            "/api/logs",
            params={"start": "2026-02-02T00:00:00Z", "end": "2026-02-01T00:00:00Z"},
        )
        assert invalid_range.status_code == 422


def test_alert_rule_validation_and_triggering(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        created = client.post(
            "/api/alerts/rules",
            json={"name": "Error burst", "threshold": 4, "window_minutes": 10},
        )
        assert created.status_code == 201
        assert client.post(
            "/api/alerts/rules",
            json={"name": "Bad threshold", "threshold": 0, "window_minutes": 10},
        ).status_code == 422
        ingested = client.post("/api/logs/upload", files={
            "file": ("test.log", b"ERROR [api] [main.py] first\nERROR [api] [main.py] second", "text/plain")
        })
        assert ingested.status_code == 200
        assert ingested.json()["accepted"] == 2
        alerts = client.get("/api/alerts").json()
        assert len(alerts) == 1
        assert alerts[0]["count"] == 5


def test_upload_validation_and_large_line_rejection(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        wrong_type = client.post("/api/logs/upload", files={"file": ("payload.csv", b"hello")})
        assert wrong_type.status_code == 415
        result = client.post(
            "/api/logs/upload",
            files={"file": ("payload.txt", b"x" * 100_001 + b"\nplain valid line")},
        )
        assert result.status_code == 200
        assert result.json()["accepted"] == 1
        assert result.json()["rejected"] == 1


def test_websocket_delivers_new_log_event(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/logs") as websocket:
            response = client.post("/api/logs/generate", params={"count": 1})
            assert response.status_code == 200
            event = websocket.receive_json()
            assert event["type"] == "log"
            assert event["data"]["service"] in {"api-gateway", "worker", "payments", "auth", "database"}
        assert client.post("/api/logs/generate", params={"count": 1}).status_code == 200


def test_websocket_delivers_triggered_alert(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        rule = client.post(
            "/api/alerts/rules",
            json={"name": "Socket alert", "threshold": 4, "window_minutes": 10},
        )
        assert rule.status_code == 201
        with client.websocket_connect("/ws/logs") as websocket:
            result = client.post(
                "/api/logs/upload",
                files={"file": ("alerts.log", b"ERROR [api] [main.py] one\nERROR [api] [main.py] two")},
            )
            assert result.status_code == 200
            events = [websocket.receive_json(), websocket.receive_json(), websocket.receive_json()]
            assert [event["type"] for event in events] == ["log", "log", "alert"]
            assert events[-1]["data"]["rule_name"] == "Socket alert"


def test_timeline_returns_ordered_minute_buckets(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        points = client.get("/api/timeline", params={"minutes": 3}).json()
        assert len(points) == 3
        assert points[0]["bucket"] < points[1]["bucket"] < points[2]["bucket"]
        assert all("spike" in point for point in points)
