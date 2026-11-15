from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth import create_token, hash_password, read_token, verify_password
from app.main import create_app
from app.repository import SQLiteRepository
from scripts.reset_password import reset_password

SECRET = "x" * 32
CREDS = {"username": "divyanshi", "password": "correct-horse-1", "email": "divyanshi@example.com"}


def make(tmp_path, **kwargs):
    kwargs.setdefault("allow_registration", False)
    return TestClient(create_app(tmp_path / "t.db", auth_enabled=True, secret_key=SECRET, **kwargs))


class FakeEmailSender:
    configured = True
    public_base_url = "https://logs.example.com"

    def __init__(self):
        self.messages = []

    def send(self, recipient, subject, body):
        self.messages.append((recipient, subject, body))


def _token_from_message(message, query_key):
    link = next(line for line in message[2].splitlines() if line.startswith("https://"))
    return parse_qs(urlparse(link).query)[query_key][0]


def test_password_and_token_primitives():
    stored = hash_password("secret-password")
    assert verify_password("secret-password", stored) and not verify_password("nope", stored)
    token = create_token("a", SECRET)
    assert read_token(token, SECRET) == "a"
    assert read_token(token, "y" * 32) is None
    assert read_token(create_token("a", SECRET, ttl_seconds=-1), SECRET) is None


def test_auth_requires_a_strong_secret(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(tmp_path / "t.db", auth_enabled=True, secret_key="short")


def test_dashboard_routes_need_a_token_but_health_does_not(tmp_path):
    with make(tmp_path) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/logs").status_code == 401
        assert client.get("/api/logs", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_first_user_registers_then_registration_closes(tmp_path):
    with make(tmp_path) as client:
        assert client.get("/api/auth/status").json()["needs_setup"] is True
        created = client.post("/api/auth/register", json=CREDS)
        assert created.status_code == 201
        assert created.json() == {"username": CREDS["username"], "email_verification_sent": False}
        assert client.post("/api/auth/login", json=CREDS).status_code == 200
        assert client.get("/api/logs").status_code == 200
        assert client.get("/api/auth/status").json()["needs_setup"] is False
        other = {"username": "someone", "password": "another-pass-1", "email": "someone@example.com"}
        assert client.post("/api/auth/register", json=other).status_code == 403


def test_login_success_failure_and_lockout(tmp_path):
    with make(tmp_path) as client:
        client.post("/api/auth/register", json=CREDS)
        ok = client.post("/api/auth/login", json=CREDS)
        assert ok.status_code == 200 and ok.json()["username"] == "divyanshi"
        bad = {**CREDS, "password": "wrong-password"}
        for _ in range(5):
            assert client.post("/api/auth/login", json=bad).status_code == 401
        assert client.post("/api/auth/login", json=bad).status_code == 429
        assert client.post("/api/auth/login", json=CREDS).status_code == 429  # locked even for the right password


def test_duplicate_username_and_weak_password(tmp_path):
    with make(tmp_path, allow_registration=True) as client:
        client.post("/api/auth/register", json=CREDS)
        assert client.post("/api/auth/register", json=CREDS).status_code == 409
        assert client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "short", "email": "newuser@example.com"},
        ).status_code == 422


def test_open_registration_allows_new_users_to_join_and_sign_in(tmp_path):
    with make(tmp_path, allow_registration=True) as client:
        first = client.post("/api/auth/register", json=CREDS)
        second_credentials = {
            "username": "newuser",
            "password": "another-pass-1",
            "email": "newuser@example.com",
        }
        second = client.post("/api/auth/register", json=second_credentials)

        assert first.status_code == second.status_code == 201
        session = client.post("/api/auth/login", json=second_credentials)
        assert client.get(
            "/api/auth/me",
            headers={"Cookie": f"rtla_session={session.cookies['rtla_session']}"},
        ).json() == {
            "username": "newuser",
            "email": "newuser@example.com",
            "email_verified": False,
        }
        assert session.status_code == 200


def test_first_user_registration_closes_atomically(tmp_path):
    with make(tmp_path) as client:
        first = client.post("/api/auth/register", json=CREDS)
        second = client.post(
            "/api/auth/register",
            json={"username": "another", "password": "another-pass-1", "email": "another@example.com"},
        )
        assert first.status_code == 201
        assert second.status_code == 403


def test_concurrent_first_user_creation_allows_only_one_account(tmp_path):
    repository = SQLiteRepository(tmp_path / "t.db")
    repository.initialize()

    def create_user(username):
        return repository.create_first_user(username, "password-hash", f"{username}@example.com")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create_user, ("first", "second")))
    assert sum(user is not None for user in results) == 1
    assert repository.count_users() == 1


def test_websocket_rejects_missing_token(tmp_path):
    with make(tmp_path, cors_origins=["http://testserver"]) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/logs", headers={"Origin": "http://testserver"}):
                pass
        client.post("/api/auth/register", json=CREDS)
        client.post("/api/auth/login", json=CREDS)
        with client.websocket_connect("/ws/logs", headers={"Origin": "http://testserver"}):
            pass


def test_api_key_ingestion_still_works_with_auth_on(tmp_path):
    with make(tmp_path, ingest_api_key="k") as client:
        batch = {"events": [{"message": "hello", "service": "svc"}]}
        assert client.post("/api/ingest", json=batch, headers={"X-API-Key": "k"}).status_code == 202


def test_local_password_reset_updates_password_and_preserves_login(tmp_path):
    repository = SQLiteRepository(tmp_path / "t.db")
    repository.initialize()
    repository.create_user(CREDS["username"], hash_password(CREDS["password"]), CREDS["email"])

    assert reset_password(repository, CREDS["username"], "replacement-pass-2")
    user = repository.get_user(CREDS["username"])
    assert user is not None and verify_password("replacement-pass-2", user["password_hash"])
    assert not verify_password(CREDS["password"], user["password_hash"])


def test_local_password_reset_rejects_invalid_input_and_unknown_user(tmp_path):
    repository = SQLiteRepository(tmp_path / "t.db")
    repository.initialize()

    with pytest.raises(ValueError, match="Username"):
        reset_password(repository, "invalid username", "replacement-pass-2")
    with pytest.raises(ValueError, match="Password"):
        reset_password(repository, "unknown", "short")
    assert not reset_password(repository, "unknown", "replacement-pass-2")


def test_email_verification_and_password_reset_tokens_are_single_use(tmp_path):
    sender = FakeEmailSender()
    with make(tmp_path, email_sender=sender) as client:
        created = client.post("/api/auth/register", json=CREDS)
        assert created.status_code == 201
        assert created.json()["email_verification_sent"] is True
        assert "set-cookie" not in created.headers

        verify_token = _token_from_message(sender.messages[-1], "verify_email")
        verified = client.post("/api/auth/verify-email", json={"token": verify_token})
        assert verified.status_code == 200 and verified.json() == {"ok": True}
        assert client.post("/api/auth/verify-email", json={"token": verify_token}).status_code == 400
        assert client.post("/api/auth/login", json=CREDS).status_code == 200
        existing_session = client.cookies.get("rtla_session")

        unknown = client.post(
            "/api/auth/password-reset/request",
            json={"email": "unknown@example.com"},
        )
        known = client.post(
            "/api/auth/password-reset/request",
            json={"email": CREDS["email"]},
        )
        assert unknown.status_code == known.status_code == 200
        assert unknown.json() == known.json()

        reset_token = _token_from_message(sender.messages[-1], "reset_password")
        repository = client.app.state.repository
        with repository._connect() as db:
            stored_hash = db.execute("SELECT token_hash FROM auth_tokens").fetchone()[0]
        assert reset_token not in stored_hash

        changed = client.post(
            "/api/auth/password-reset/complete",
            json={"token": reset_token, "password": "replacement-pass-2"},
        )
        assert changed.status_code == 200 and changed.json() == {"ok": True}
        assert client.get("/api/auth/me").status_code == 401
        client.cookies.set("rtla_session", existing_session)
        assert client.get("/api/auth/me").status_code == 401
        assert client.post(
            "/api/auth/password-reset/complete",
            json={"token": reset_token, "password": "another-pass-3"},
        ).status_code == 400
        assert client.post(
            "/api/auth/login",
            json={"username": CREDS["username"], "password": "replacement-pass-2"},
        ).status_code == 200


def test_registration_rejects_duplicate_email_case_insensitively(tmp_path):
    with make(tmp_path, allow_registration=True) as client:
        assert client.post("/api/auth/register", json=CREDS).status_code == 201
        duplicate = {
            "username": "second-user",
            "password": "another-pass-1",
            "email": CREDS["email"].upper(),
        }
        response = client.post("/api/auth/register", json=duplicate)
        assert response.status_code == 409
        assert response.json()["detail"] == "That email address is already in use"
