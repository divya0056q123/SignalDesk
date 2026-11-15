import asyncio

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.main import create_app
from app.websocket import EventHub


def _register(client: TestClient, username: str) -> dict[str, str]:
    email = f"{username}@example.com"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secure-password-1", "email": email},
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


def test_accounts_cannot_read_each_others_workspace(tmp_path):
    app = create_app(
        tmp_path / "tenants.db",
        auth_enabled=True,
        secret_key="production-like-test-secret-0123456789",
        allow_registration=True,
        ingest_api_key="machine-secret",
        ingest_tenant_id="alice",
    )
    with TestClient(app) as client:
        alice = _register(client, "alice")
        bob = _register(client, "bob")

        rule = client.post(
            "/api/alerts/rules",
            headers=alice,
            json={"name": "Alice errors", "threshold": 1, "window_minutes": 10},
        )
        assert rule.status_code == 201
        upload = client.post(
            "/api/logs/upload",
            headers=alice,
            files={"file": ("alice.log", b"ERROR [alice-service] first\nERROR [alice-service] second")},
        )
        assert upload.status_code == 200

        assert client.get("/api/logs", headers=alice).json()
        assert client.get("/api/alerts/rules", headers=alice).json()
        assert client.get("/api/alerts", headers=alice).json()

        assert client.get("/api/logs", headers=bob).json() == []
        assert client.get("/api/metrics", headers=bob).json()["total_events"] == 0
        assert client.get("/api/services", headers=bob).json() == []
        assert client.get("/api/alerts/rules", headers=bob).json() == []
        assert client.get("/api/alerts", headers=bob).json() == []
        assert client.get("/api/clusters", headers=bob).json() == []

        ingested = client.post(
            "/api/ingest",
            headers={"X-API-Key": "machine-secret"},
            json={"events": [{"message": "machine event", "service": "alice-service"}]},
        )
        assert ingested.status_code == 202
        assert any(log["message"] == "machine event" for log in client.get("/api/logs", headers=alice).json())
        assert client.get("/api/logs", headers=bob).json() == []


def test_browser_sessions_use_httponly_cookie_and_validate_write_origin(tmp_path):
    app = create_app(
        tmp_path / "cookie.db",
        auth_enabled=True,
        secret_key="production-like-test-secret-0123456789",
        allow_registration=False,
        cors_origins=["http://localhost:5173"],
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "username": "cookie-user",
                "password": "secure-password-1",
                "email": "cookie-user@example.com",
            },
        )
        assert response.status_code == 201
        assert "set-cookie" not in response.headers
        session = client.post(
            "/api/auth/login",
            json={"username": "cookie-user", "password": "secure-password-1"},
        )
        cookie = session.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert client.get("/api/auth/me").json() == {
            "username": "cookie-user",
            "email": "cookie-user@example.com",
            "email_verified": False,
        }

        rejected = client.post(
            "/api/alerts/rules",
            json={"name": "Bad origin", "threshold": 1, "window_minutes": 5},
            headers={"Origin": "https://attacker.example"},
        )
        assert rejected.status_code == 403
        accepted = client.post(
            "/api/alerts/rules",
            json={"name": "Good origin", "threshold": 1, "window_minutes": 5},
            headers={"Origin": "http://localhost:5173"},
        )
        assert accepted.status_code == 201

        assert client.post("/api/auth/logout").json() == {"ok": True}
        assert client.get("/api/auth/me").status_code == 401


def test_first_account_requires_bootstrap_code_in_production_mode(tmp_path):
    app = create_app(
        tmp_path / "bootstrap.db",
        auth_enabled=True,
        secret_key="production-like-test-secret-0123456789",
        allow_registration=False,
    )
    app.state.app_env = "production"
    app.state.bootstrap_token = "one-time-setup-code-for-production-123"

    with TestClient(app) as client:
        assert client.get("/api/auth/status").json()["setup_token_required"] is True
        credentials = {
            "username": "owner",
            "password": "secure-password-1",
            "email": "owner@example.com",
        }
        assert client.post("/api/auth/register", json=credentials).status_code == 403
        created = client.post(
            "/api/auth/register",
            json=credentials,
            headers={"X-Setup-Token": app.state.bootstrap_token},
        )
        assert created.status_code == 201
        assert client.get("/api/auth/status").json()["setup_token_required"] is False
        assert client.post(
            "/api/auth/register",
            json={
                "username": "stranger",
                "password": "secure-password-1",
                "email": "stranger@example.com",
            },
        ).status_code == 403


def test_legacy_shared_data_migrates_to_oldest_account(tmp_path):
    import sqlite3
    from datetime import datetime, timezone

    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE log_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, severity TEXT NOT NULL,
                service TEXT NOT NULL, source TEXT NOT NULL, message TEXT NOT NULL
            );
            CREATE TABLE alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, threshold INTEGER NOT NULL,
                window_minutes INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE triggered_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id INTEGER NOT NULL, rule_name TEXT NOT NULL,
                message TEXT NOT NULL, count INTEGER NOT NULL, triggered_at TEXT NOT NULL
            );
            """
        )
        db.execute(
            "INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)",
            ("legacy-owner", hash_password("secure-password-1"), datetime.now(timezone.utc).isoformat()),
        )
        db.execute(
            "INSERT INTO log_events(timestamp,severity,service,source,message) VALUES(?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), "INFO", "legacy", "test", "preserve this event"),
        )

    app = create_app(
        database,
        auth_enabled=True,
        secret_key="production-like-test-secret-0123456789",
        allow_registration=False,
        sample_data_enabled=False,
    )
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "legacy-owner", "password": "secure-password-1"},
        )
        assert login.status_code == 200
        token = {"Cookie": f"rtla_session={login.cookies['rtla_session']}"}
        logs = client.get("/api/logs", headers=token).json()
        assert len(logs) == 1
        assert logs[0]["message"] == "preserve this event"


def test_production_configuration_rejects_missing_database_and_host_allowlist(tmp_path):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(
            tmp_path / "production.db",
            app_env="production",
            secret_key="p" * 40,
            bootstrap_token="b" * 40,
            database_url="",
            sample_data_enabled=False,
            allowed_hosts=["logs.example.com"],
            cors_origins=["https://logs.example.com"],
        )

    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        create_app(
            tmp_path / "production.db",
            app_env="production",
            secret_key="p" * 40,
            bootstrap_token="b" * 40,
            database_url="postgresql://db/signaldesk",
            sample_data_enabled=False,
            allowed_hosts=["*"],
            cors_origins=["https://logs.example.com"],
        )


def test_websocket_hub_broadcasts_only_to_the_requested_tenant():
    class Socket:
        def __init__(self):
            self.events = []

        async def accept(self):
            pass

        async def send_json(self, event):
            self.events.append(event)

    async def verify():
        hub = EventHub()
        alice, bob = Socket(), Socket()
        await hub.connect(alice, "alice")
        await hub.connect(bob, "bob")
        await hub.broadcast({"type": "log", "data": {"message": "private"}}, "alice")
        assert len(alice.events) == 1
        assert bob.events == []

    asyncio.run(verify())
