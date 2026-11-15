import hashlib
import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app


SECRET = "production-like-test-secret-0123456789"


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secure-password-1", "email": f"{username}@example.com"},
    )
    assert response.status_code == 201
    session = client.post(
        "/api/auth/login",
        json={"username": username, "password": "secure-password-1"},
    )
    assert session.status_code == 200
    return {
        "Cookie": f"rtla_session={session.cookies['rtla_session']}",
        "Origin": "http://localhost:5173",
    }


def test_ingestion_keys_are_hashed_owner_scoped_and_revocable(tmp_path):
    database = tmp_path / "keys.db"
    app = create_app(
        database,
        auth_enabled=True,
        secret_key=SECRET,
        allow_registration=True,
        ingest_api_key="legacy-shared-key",
        sample_data_enabled=False,
    )
    with TestClient(app) as client:
        alice = _register(client, "alice")
        bob = _register(client, "bob")
        client.cookies.clear()
        assert client.get("/api/ingest-keys").status_code == 401

        created = client.post("/api/ingest-keys", headers=alice, json={"name": "  Payments  "})
        assert created.status_code == 201
        key = created.json()
        assert key["name"] == "Payments"
        assert key["key"].startswith("sd_ingest_")

        listed = client.get("/api/ingest-keys", headers=alice).json()
        assert len(listed) == 1
        assert listed[0]["id"] == key["id"] and listed[0]["name"] == "Payments"
        assert "key" not in listed[0] and "key_hash" not in listed[0]
        assert client.get("/api/ingest-keys", headers=bob).json() == []
        with sqlite3.connect(database) as db:
            stored_hash = db.execute(
                "SELECT key_hash FROM ingest_keys WHERE id=?", (key["id"],)
            ).fetchone()[0]
        assert stored_hash == hashlib.sha256(key["key"].encode()).hexdigest()
        assert stored_hash != key["key"]

        batch = {"events": [{"message": "alice machine event", "service": "payments"}]}
        ingested = client.post("/api/ingest", headers={"X-API-Key": key["key"]}, json=batch)
        assert ingested.status_code == 202
        assert [row["message"] for row in client.get("/api/logs", headers=alice).json()] == ["alice machine event"]
        assert client.get("/api/logs", headers=bob).json() == []

        assert client.delete(f"/api/ingest-keys/{key['id']}", headers=bob).status_code == 404
        assert client.delete(f"/api/ingest-keys/{key['id']}", headers=alice).status_code == 204
        assert client.post("/api/ingest", headers={"X-API-Key": key["key"]}, json=batch).status_code == 401


def test_ingestion_key_limit_and_revocation_free_slot(tmp_path):
    app = create_app(
        tmp_path / "limit.db",
        auth_enabled=True,
        secret_key=SECRET,
        allow_registration=True,
        sample_data_enabled=False,
    )
    with TestClient(app) as client:
        headers = _register(client, "limited")
        keys = [
            client.post("/api/ingest-keys", headers=headers, json={"name": f"key-{index}"}).json()
            for index in range(10)
        ]
        assert len(client.get("/api/ingest-keys", headers=headers).json()) == 10
        rejected = client.post("/api/ingest-keys", headers=headers, json={"name": "one too many"})
        assert rejected.status_code == 409
        assert client.delete(f"/api/ingest-keys/{keys[0]['id']}", headers=headers).status_code == 204
        assert client.post("/api/ingest-keys", headers=headers, json={"name": "replacement"}).status_code == 201
