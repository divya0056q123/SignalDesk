from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from . import api
from .alerts import AlertEvaluator
from .auth import SESSION_COOKIE_NAME, LoginThrottle, read_token
from .config import (
    ALLOWED_HOSTS, ALLOW_REGISTRATION, APP_ENV, AUTH_ENABLED, CORS_ORIGINS, DATABASE_PATH,
    BOOTSTRAP_TOKEN, DATABASE_URL, INGEST_API_KEY, INGEST_TENANT_ID, MAX_INGEST_BODY_BYTES, SAMPLE_DATA_ENABLED,
    PUBLIC_BASE_URL, SAMPLE_LOG_PATH, SECRET_KEY, SMTP_FROM_EMAIL, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT,
    SMTP_SECURITY, SMTP_USERNAME, WEBHOOK_URL,
)
from .email_service import SMTPEmailSender
from .ingestion import LogIngestor
from .notifier import WebhookNotifier
from .parser import parse_line
from .repository import SQLiteRepository
from .request_limits import RequestBodyLimitMiddleware
from .websocket import EventHub


def create_app(
    database_path=DATABASE_PATH,
    ingest_api_key: str = INGEST_API_KEY,
    auth_enabled: bool = AUTH_ENABLED,
    secret_key: str = SECRET_KEY,
    allow_registration: bool = ALLOW_REGISTRATION,
    database_url: str = DATABASE_URL,
    max_ingest_body_bytes: int = MAX_INGEST_BODY_BYTES,
    ingest_tenant_id: str = INGEST_TENANT_ID,
    bootstrap_token: str = BOOTSTRAP_TOKEN,
    app_env: str = APP_ENV,
    allowed_hosts: list[str] | None = None,
    cors_origins: list[str] | None = None,
    sample_data_enabled: bool = SAMPLE_DATA_ENABLED,
    smtp_host: str = SMTP_HOST,
    smtp_port: int = SMTP_PORT,
    smtp_username: str = SMTP_USERNAME,
    smtp_password: str = SMTP_PASSWORD,
    smtp_from_email: str = SMTP_FROM_EMAIL,
    smtp_security: str = SMTP_SECURITY,
    public_base_url: str = PUBLIC_BASE_URL,
    email_sender: SMTPEmailSender | None = None,
) -> FastAPI:
    if max_ingest_body_bytes < 1:
        raise ValueError("MAX_INGEST_BODY_BYTES must be positive")
    if auth_enabled and len(secret_key) < 16:
        raise RuntimeError("AUTH_ENABLED requires SECRET_KEY to be set to a random string of 16+ characters")
    if app_env == "production":
        if not auth_enabled:
            raise RuntimeError("AUTH_ENABLED must remain enabled in production")
        if len(secret_key) < 32:
            raise RuntimeError("Production requires a SECRET_KEY of at least 32 characters")
        if not database_url:
            raise RuntimeError("Production requires DATABASE_URL; SQLite is for local development only")
        if sample_data_enabled:
            raise RuntimeError("SAMPLE_DATA_ENABLED must be false in production")
        if allowed_hosts is None:
            allowed_hosts = ALLOWED_HOSTS
        if not allowed_hosts or "*" in allowed_hosts:
            raise RuntimeError("Production requires explicit ALLOWED_HOSTS")
        if cors_origins is None:
            cors_origins = CORS_ORIGINS
        if not cors_origins:
            raise RuntimeError("Production requires explicit CORS_ORIGINS")
        if not 1 <= smtp_port <= 65535:
            raise RuntimeError("SMTP_PORT must be between 1 and 65535")
        if smtp_security not in {"starttls", "ssl"}:
            raise RuntimeError("Production SMTP_SECURITY must be starttls or ssl")
        if bool(smtp_username) != bool(smtp_password):
            raise RuntimeError("SMTP_USERNAME and SMTP_PASSWORD must be configured together")
        if email_sender is None:
            email_sender = SMTPEmailSender(
                host=smtp_host,
                port=smtp_port,
                username=smtp_username,
                password=smtp_password,
                sender=smtp_from_email,
                security=smtp_security,
                public_base_url=public_base_url,
            )
        if not email_sender.configured:
            raise RuntimeError("Production requires valid SMTP settings and PUBLIC_BASE_URL for account recovery")
        if not public_base_url.startswith("https://"):
            raise RuntimeError("Production PUBLIC_BASE_URL must use HTTPS")
        if ingest_api_key and not ingest_tenant_id:
            raise RuntimeError("INGEST_TENANT_ID is required when API-key ingestion is enabled")
    elif email_sender is None:
        email_sender = SMTPEmailSender(
            host=smtp_host,
            port=smtp_port,
            username=smtp_username,
            password=smtp_password,
            sender=smtp_from_email,
            security=smtp_security,
            public_base_url=public_base_url,
        )
    elif allowed_hosts is None:
        allowed_hosts = ALLOWED_HOSTS
    if cors_origins is None:
        cors_origins = CORS_ORIGINS
    if database_url:
        from .postgres_repository import PostgresRepository

        repository = PostgresRepository(database_url)
    else:
        repository = SQLiteRepository(database_path)
    hub = EventHub()
    alerts = AlertEvaluator(repository)
    ingestor = LogIngestor(repository, alerts, hub, WebhookNotifier(WEBHOOK_URL))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository.initialize()
        if app_env == "production" and repository.count_users() == 0 and len(bootstrap_token) < 32:
            raise RuntimeError("A BOOTSTRAP_TOKEN of at least 32 characters is required before first-account setup")
        if app_env == "production" and ingest_api_key and not repository.get_user(ingest_tenant_id):
            raise RuntimeError("INGEST_TENANT_ID must be an existing account username")
        if (
            sample_data_enabled
            and repository.count_users() == 0
            and repository.count_logs() == 0
            and SAMPLE_LOG_PATH.exists()
        ):
            samples = SAMPLE_LOG_PATH.read_text(encoding="utf-8").splitlines()
            seeded_at = datetime.now(timezone.utc)
            for index, line in enumerate(samples):
                event = parse_line(line)
                event["timestamp"] = seeded_at - timedelta(seconds=len(samples) - index)
                repository.insert_log(event)
        yield

    app = FastAPI(
        title="Real-Time Log Analyzer",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if app_env == "production" else "/docs",
        redoc_url=None if app_env == "production" else "/redoc",
        openapi_url=None if app_env == "production" else "/openapi.json",
    )
    app.state.repository = repository
    app.state.ingest_api_key = ingest_api_key
    app.state.ingest_tenant_id = ingest_tenant_id
    app.state.bootstrap_token = bootstrap_token
    app.state.app_env = app_env
    app.state.cors_origins = cors_origins
    app.state.auth_enabled = auth_enabled
    app.state.secret_key = secret_key
    app.state.allow_registration = allow_registration
    app.state.throttle = LoginThrottle()
    app.state.recovery_throttle = LoginThrottle(max_failures=5, lock_seconds=300)
    app.state.email_sender = email_sender
    app.state.hub = hub
    app.state.ingestor = ingestor
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    if allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.add_middleware(RequestBodyLimitMiddleware, limits={"/api/ingest": max_ingest_body_bytes})
    app.include_router(api.public_router)
    app.include_router(api.auth_router)
    app.include_router(api.router)

    @app.websocket("/ws/logs")
    async def logs_socket(websocket: WebSocket):
        tenant_id = "default"
        if auth_enabled:
            cookie_token = websocket.cookies.get(SESSION_COOKIE_NAME)
            if cookie_token and websocket.headers.get("origin") not in cors_origins:
                await websocket.close(code=4403)
                return
            token = cookie_token or websocket.query_params.get("token", "")
            token_username = read_token(token, secret_key)
            user = repository.get_user(token_username) if token_username else None
            tenant_id = (
                read_token(token, secret_key, session_version=int(user.get("session_version", 0)))
                if user
                else None
            ) or ""
            if not tenant_id:
                await websocket.close(code=4401)
                return
        await hub.connect(websocket, tenant_id)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await hub.disconnect(websocket, tenant_id)

    return app


app = create_app()
