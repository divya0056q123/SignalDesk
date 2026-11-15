from fastapi.testclient import TestClient

from app.main import create_app

BATCH = {"events": [{"message": "payment timeout after 5s", "severity": "ERROR", "service": "payments"}]}


def test_http_ingestion_is_disabled_without_a_key(tmp_path):
    with TestClient(create_app(tmp_path / "t.db", auth_enabled=False)) as client:
        assert client.post("/api/ingest", json=BATCH).status_code == 503


def test_http_ingestion_requires_the_right_key(tmp_path):
    with TestClient(create_app(tmp_path / "t.db", ingest_api_key="s3cret", auth_enabled=False)) as client:
        assert client.post("/api/ingest", json=BATCH).status_code == 401
        assert client.post("/api/ingest", json=BATCH, headers={"X-API-Key": "wrong"}).status_code == 401
        ok = client.post("/api/ingest", json=BATCH, headers={"X-API-Key": "s3cret"})
        assert ok.status_code == 202 and ok.json()["accepted"] == 1
        found = client.get("/api/logs", params={"service": "payments"}).json()
        assert found and found[0]["severity"] == "ERROR"


def test_http_ingestion_persists_a_batch(tmp_path):
    batch = {"events": [
        {"message": "first", "service": "payments"},
        {"message": "second", "service": "api"},
    ]}
    with TestClient(create_app(tmp_path / "t.db", ingest_api_key="k", auth_enabled=False)) as client:
        before = client.get("/api/metrics").json()["total_events"]
        response = client.post("/api/ingest", json=batch, headers={"X-API-Key": "k"})
        assert response.status_code == 202
        assert response.json()["accepted"] == 2
        after = client.get("/api/metrics").json()["total_events"]
        assert after - before == 2


def test_ingest_validates_payload(tmp_path):
    with TestClient(create_app(tmp_path / "t.db", ingest_api_key="k", auth_enabled=False)) as client:
        headers = {"X-API-Key": "k"}
        assert client.post("/api/ingest", json={"events": []}, headers=headers).status_code == 422
        bad = {"events": [{"message": "x", "severity": "LOUD"}]}
        assert client.post("/api/ingest", json=bad, headers=headers).status_code == 422


def test_ingest_rejects_oversized_request_body_before_parsing(tmp_path):
    app = create_app(tmp_path / "t.db", ingest_api_key="k", auth_enabled=False, max_ingest_body_bytes=128)
    with TestClient(app) as client:
        body = b'{"events":[{"message":"' + b"x" * 256 + b'"}]}'
        headers = {"X-API-Key": "k", "Content-Type": "application/json"}
        declared_size = client.post("/api/ingest", content=body, headers=headers)
        streamed_size = client.post(
            "/api/ingest",
            content=iter((body[:64], body[64:])),
            headers=headers,
        )
        assert declared_size.status_code == streamed_size.status_code == 413


def test_clusters_and_anomalies_endpoints(tmp_path):
    with TestClient(create_app(tmp_path / "t.db", auth_enabled=False)) as client:
        lines = "\n".join(f"ERROR [payments] [x.py] provider timeout after {i}s" for i in range(12))
        client.post("/api/logs/upload", files={"file": ("a.log", lines.encode())})
        clusters = client.get("/api/clusters").json()
        assert any("provider timeout" in c["template"] and c["count"] >= 12 for c in clusters)
        assert client.get("/api/anomalies").status_code == 200
        assert client.get("/api/anomalies", params={"minutes": 1}).status_code == 422
