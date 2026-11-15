import hashlib
import hmac
import logging
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import ValidationError

from .anomaly import detect_anomalies
from .auth import SESSION_COOKIE_NAME, create_token, hash_password, read_token, verify_password
from .clustering import cluster_events
from .config import MAX_INGEST_BATCH, MAX_UPLOAD_BYTES
from .models import (
    AlertRule, AlertRuleCreate, Anomaly, AuthSession, Credentials, EmailAddress, EmailTokenRequest,
    IngestBatch, IngestKeyCreate, IngestResponse, LogCluster, LogEvent, LoginCredentials, Metrics,
    PasswordResetRequest, RegistrationResponse, TimelinePoint, TriggeredAlert,
)
from .parser import parse_line
from .repository import EmailAlreadyUsedError, IngestKeyLimitError, LogRepository, UserExistsError


_DUMMY_PASSWORD_HASH = hash_password("dummy-password", salt=b"signaldesk-dummy-salt")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TOKEN_LIFETIME = timedelta(minutes=30)
_MAX_INGEST_KEYS_PER_ACCOUNT = 10
_logger = logging.getLogger(__name__)


def require_user(request: Request, authorization: str | None = Header(default=None)) -> str | None:
    """Dependency for dashboard routes: enforced only when AUTH_ENABLED is on."""
    if not request.app.state.auth_enabled:
        request.state.tenant_id = "default"
        return None
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif cookie_token:
        token = cookie_token
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin not in request.app.state.cors_origins:
                raise HTTPException(status_code=403, detail="Invalid request origin")
    else:
        raise HTTPException(status_code=401, detail="Sign in required", headers={"WWW-Authenticate": "Bearer"})
    username = read_token(token, request.app.state.secret_key)
    if username is None:
        raise HTTPException(status_code=401, detail="Session expired, sign in again", headers={"WWW-Authenticate": "Bearer"})
    user = _repository(request).get_user(username)
    if user is None or read_token(
        token,
        request.app.state.secret_key,
        session_version=int(user.get("session_version", 0)),
    ) is None:
        raise HTTPException(status_code=401, detail="Session expired, sign in again", headers={"WWW-Authenticate": "Bearer"})
    request.state.tenant_id = username
    return username


router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])  # needs a session when auth is on
public_router = APIRouter(prefix="/api")  # health check and API-key ingestion
auth_router = APIRouter(prefix="/api/auth")


def _repository(request: Request) -> LogRepository:
    return request.app.state.repository


def _tenant_id(request: Request) -> str:
    return getattr(request.state, "tenant_id", "default")


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return email


def _new_auth_token(repository: LogRepository, username: str, purpose: str) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    repository.issue_auth_token(
        username,
        purpose,
        token_hash,
        datetime.now(timezone.utc) + _TOKEN_LIFETIME,
    )
    return token


def _send_email_logged(sender, recipient: str, subject: str, body: str) -> None:
    try:
        sender.send(recipient, subject, body)
    except (OSError, RuntimeError, smtplib.SMTPException):
        _logger.exception("Could not send account email")


def _email_link(sender, query_key: str, token: str) -> str:
    return f"{sender.public_base_url}/?{urlencode({query_key: token})}"


@public_router.get("/health")
def health(request: Request) -> dict[str, str]:
    _repository(request).health_check()
    return {"status": "ok"}


@router.get("/logs", response_model=list[LogEvent])
def get_logs(
    request: Request,
    search: str | None = Query(default=None, max_length=200),
    severity: str | None = Query(default=None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL|UNKNOWN)$"),
    service: str | None = Query(default=None, max_length=100),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    start = _as_utc(start)
    end = _as_utc(end)
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start must be earlier than or equal to end")
    return _repository(request).query_logs(
        search=search,
        severity=severity,
        service=service,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
        tenant_id=_tenant_id(request),
    )


@router.get("/metrics", response_model=Metrics)
def metrics(request: Request) -> dict:
    return _repository(request).get_metrics(_tenant_id(request))


@router.get("/timeline", response_model=list[TimelinePoint])
def timeline(request: Request, minutes: int = Query(default=60, ge=1, le=1440)) -> list[dict]:
    return _repository(request).get_timeline(minutes, _tenant_id(request))


@router.get("/services", response_model=list[str])
def services(request: Request) -> list[str]:
    return _repository(request).list_services(_tenant_id(request))


@router.post("/logs/generate", response_model=IngestResponse)
async def generate_logs(request: Request, count: int = Query(default=20, ge=1, le=500)) -> dict:
    samples = [
        "INFO [api-gateway] [src/routes.py] request completed status=200 latency=42ms",
        "WARNING [worker] [src/jobs.py] retrying delayed task attempt=2",
        "ERROR [payments] [src/checkout.py] payment provider timeout after 5s",
        "DEBUG [auth] [src/token.py] token refreshed successfully",
        "INFO [database] [src/pool.py] connection pool healthy active=8",
    ]
    import random

    lines = [f"{datetime.now(timezone.utc).isoformat()} {random.choice(samples)}" for _ in range(count)]
    accepted, rejected = await request.app.state.ingestor.ingest_lines(lines, _tenant_id(request))
    return {"accepted": accepted, "rejected": rejected, "message": "Generated sample log events."}


@router.post("/logs/upload", response_model=IngestResponse)
async def upload_logs(request: Request, file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".log", ".txt"}:
        raise HTTPException(status_code=415, detail="Only .log and .txt files are supported")
    chunks = bytearray()
    while len(chunks) <= MAX_UPLOAD_BYTES:
        chunk = await file.read(min(64 * 1024, MAX_UPLOAD_BYTES + 1 - len(chunks)))
        if not chunk:
            break
        chunks.extend(chunk)
    await file.close()
    if len(chunks) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Upload exceeds the {MAX_UPLOAD_BYTES}-byte limit")
    content = bytes(chunks).decode("utf-8", errors="replace")
    lines = content.splitlines()
    accepted, rejected = await request.app.state.ingestor.ingest_lines(lines, _tenant_id(request))
    return {"accepted": accepted, "rejected": rejected, "message": "Log file processed."}


@router.get("/alerts/rules", response_model=list[AlertRule])
def alert_rules(request: Request) -> list[dict]:
    rules = _repository(request).list_rules(_tenant_id(request))
    for rule in rules:
        rule["enabled"] = bool(rule["enabled"])
        rule["created_at"] = datetime.fromisoformat(rule["created_at"])
    return rules


@router.post("/alerts/rules", response_model=AlertRule, status_code=201)
def create_alert_rule(request: Request, rule: AlertRuleCreate) -> dict:
    stored = _repository(request).create_rule(rule, _tenant_id(request))
    stored["enabled"] = bool(stored["enabled"])
    stored["created_at"] = datetime.fromisoformat(stored["created_at"])
    return stored


@router.get("/alerts", response_model=list[TriggeredAlert])
def triggered_alerts(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    return _repository(request).list_alerts(limit, _tenant_id(request))


@router.post("/ingest/parse-preview")
def parse_preview(payload: dict) -> dict:
    line = payload.get("line")
    if not isinstance(line, str) or len(line) > 100_000:
        raise HTTPException(status_code=422, detail="line must be text no longer than 100,000 characters")
    try:
        result = parse_line(line)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Unable to parse log line") from exc
    return result


@router.get("/anomalies", response_model=list[Anomaly])
def anomalies(request: Request, minutes: int = Query(default=60, ge=10, le=1440)) -> list[dict]:
    """Statistically unusual minutes (robust z-score on error and total volume)."""
    points = _repository(request).get_timeline(minutes, _tenant_id(request))
    found = detect_anomalies(points, "errors") + detect_anomalies(points, "total")
    return sorted(found, key=lambda item: item["bucket"], reverse=True)


@router.get("/clusters", response_model=list[LogCluster])
def clusters(
    request: Request,
    minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict]:
    """Group similar messages into templates so thousands of lines become a few patterns."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return cluster_events(_repository(request).logs_since(since, tenant_id=_tenant_id(request)), limit)


@public_router.post("/ingest", response_model=IngestResponse, status_code=202)
async def ingest_events(
    request: Request,
    batch: IngestBatch,
    x_api_key: str | None = Header(default=None),
) -> dict:
    """Machine-to-machine ingestion: other applications POST structured events here."""
    api_key: str = request.app.state.ingest_api_key
    if x_api_key is None:
        if not api_key and not request.app.state.auth_enabled:
            raise HTTPException(status_code=503, detail="HTTP ingestion is disabled; set INGEST_API_KEY")
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    if api_key and hmac.compare_digest(x_api_key.encode(), api_key.encode()):
        tenant_id = request.app.state.ingest_tenant_id if request.app.state.auth_enabled else "default"
    else:
        tenant_id = _repository(request).get_ingest_key_owner(
            hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()
        )
        if tenant_id is None:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    if len(batch.events) > MAX_INGEST_BATCH:
        raise HTTPException(status_code=413, detail=f"At most {MAX_INGEST_BATCH} events per request")
    ingestor = request.app.state.ingestor
    await ingestor.ingest_events([event.model_dump() for event in batch.events], tenant_id)
    await ingestor.check_anomalies(tenant_id)
    return {"accepted": len(batch.events), "rejected": 0, "message": "Events ingested."}


@router.get("/ingest-keys")
def list_ingest_keys(
    request: Request,
    username: str | None = Depends(require_user),
) -> list[dict]:
    if username is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return _repository(request).list_ingest_keys(username)


@router.post("/ingest-keys", status_code=201)
def create_ingest_key(
    request: Request,
    body: IngestKeyCreate,
    username: str | None = Depends(require_user),
) -> dict:
    if username is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    repository = _repository(request)
    key = f"sd_ingest_{secrets.token_urlsafe(32)}"
    key_id = secrets.token_hex(12)
    try:
        repository.create_ingest_key(
            username,
            key_id,
            body.name.strip(),
            hashlib.sha256(key.encode("utf-8")).hexdigest(),
            datetime.now(timezone.utc),
            _MAX_INGEST_KEYS_PER_ACCOUNT,
        )
    except IngestKeyLimitError as exc:
        raise HTTPException(
            status_code=409, detail=f"At most {_MAX_INGEST_KEYS_PER_ACCOUNT} active ingestion keys are allowed"
        ) from exc
    return {"id": key_id, "name": body.name.strip(), "key": key}


@router.delete("/ingest-keys/{key_id}", status_code=204)
def revoke_ingest_key(
    request: Request,
    key_id: str,
    username: str | None = Depends(require_user),
) -> Response:
    if username is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    if not _repository(request).revoke_ingest_key(username, key_id):
        raise HTTPException(status_code=404, detail="Ingestion key not found")
    return Response(status_code=204)


@auth_router.get("/status")
def auth_status(request: Request) -> dict:
    """Lets the UI decide whether to show the sign-in screen."""
    repository = _repository(request)
    state = request.app.state
    return {
        "auth_enabled": state.auth_enabled,
        "needs_setup": state.auth_enabled and repository.count_users() == 0,
        "registration_open": state.allow_registration,
        "setup_token_required": state.app_env == "production" and repository.count_users() == 0,
        "email_verification_required": state.app_env == "production",
    }


@auth_router.post("/register", response_model=RegistrationResponse, status_code=201)
def register(request: Request, credentials: Credentials) -> dict:
    state, repository = request.app.state, _repository(request)
    if not state.auth_enabled:
        raise HTTPException(status_code=404, detail="Authentication is not enabled")
    email = _normalize_email(credentials.email)
    first_user = repository.count_users() == 0
    if first_user and state.app_env == "production":
        setup_token = request.headers.get("x-setup-token", "")
        if not hmac.compare_digest(setup_token, state.bootstrap_token):
            raise HTTPException(status_code=403, detail="A valid setup code is required for the first account")
    if not first_user and not state.allow_registration:
        raise HTTPException(status_code=403, detail="Registration is closed")
    try:
        password_hash = hash_password(credentials.password)
        user = repository.create_first_user(credentials.username, password_hash, email) if first_user else None
        if user is None:
            if first_user and not state.allow_registration:
                raise HTTPException(status_code=403, detail="Registration is closed")
            user = repository.create_user(credentials.username, password_hash, email)
    except UserExistsError as exc:
        raise HTTPException(status_code=409, detail="That username is taken") from exc
    except EmailAlreadyUsedError as exc:
        raise HTTPException(status_code=409, detail="That email address is already in use") from exc

    verification_sent = False
    if state.email_sender.configured:
        token = _new_auth_token(repository, user["username"], "verify_email")
        link = _email_link(state.email_sender, "verify_email", token)
        try:
            state.email_sender.send(
                email,
                "Verify your Real-Time Log Analyzer email",
                f"Verify your email address using this link within 30 minutes:\n\n{link}\n\n"
                "If you did not create this account, you can ignore this message.",
            )
        except (OSError, RuntimeError, smtplib.SMTPException):
            _logger.exception("Could not send email verification to %s", email)
        else:
            verification_sent = True
    return {"username": user["username"], "email_verification_sent": verification_sent}


@auth_router.post("/login", response_model=AuthSession)
def login(request: Request, response: Response, credentials: LoginCredentials) -> dict:
    state, repository = request.app.state, _repository(request)
    if not state.auth_enabled:
        raise HTTPException(status_code=404, detail="Authentication is not enabled")
    name = credentials.username
    if state.throttle.locked(name):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")
    user = repository.get_user(name)
    stored = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
    if not verify_password(credentials.password, stored) or user is None:
        state.throttle.fail(name)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if state.app_env == "production" and not user["email_verified"]:
        state.throttle.fail(name)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    state.throttle.clear(name)
    token = create_token(name, state.secret_key, session_version=int(user.get("session_version", 0)))
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=8 * 3600,
        httponly=True,
        secure=state.app_env == "production",
        samesite="strict",
        path="/",
    )
    return {"username": name, "email_verified": bool(user["email_verified"])}


@auth_router.post("/email")
def set_account_email(
    request: Request,
    body: EmailAddress,
    username: str | None = Depends(require_user),
) -> dict[str, bool]:
    if username is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    sender = request.app.state.email_sender
    if not sender.configured:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    email = _normalize_email(body.email)
    repository = _repository(request)
    try:
        repository.update_user_email(username, email)
    except EmailAlreadyUsedError as exc:
        raise HTTPException(status_code=409, detail="That email address is already in use") from exc
    token = _new_auth_token(repository, username, "verify_email")
    link = _email_link(sender, "verify_email", token)
    try:
        sender.send(
            email,
            "Verify your Real-Time Log Analyzer email",
            f"Verify your email address using this link within 30 minutes:\n\n{link}\n\n"
            "If you did not request this change, contact your administrator.",
        )
    except (OSError, RuntimeError, smtplib.SMTPException) as exc:
        _logger.exception("Could not send email verification to %s", email)
        raise HTTPException(status_code=502, detail="The email was saved, but verification could not be sent. Try again.") from exc
    return {"email_verification_sent": True}


@auth_router.post("/verify-email")
def verify_account_email(request: Request, body: EmailTokenRequest) -> dict[str, bool]:
    repository = _repository(request)
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    username = repository.consume_auth_token(token_hash, "verify_email", datetime.now(timezone.utc))
    if username is None or not repository.mark_email_verified(username):
        raise HTTPException(status_code=400, detail="This verification link is invalid or expired")
    return {"ok": True}


@auth_router.post("/password-reset/request")
def request_password_reset(
    request: Request,
    body: EmailAddress,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    state, repository = request.app.state, _repository(request)
    if not state.email_sender.configured:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    email = _normalize_email(body.email)
    throttle = state.recovery_throttle
    if throttle.locked(email):
        raise HTTPException(status_code=429, detail="Too many recovery requests. Try again later.")
    throttle.fail(email)

    user = repository.get_user_by_email(email, verified_only=True)
    if user:
        token = _new_auth_token(repository, user["username"], "reset_password")
        link = _email_link(state.email_sender, "reset_password", token)
        background_tasks.add_task(
            _send_email_logged,
            state.email_sender,
            email,
            "Reset your Real-Time Log Analyzer password",
            f"Reset your password using this link within 30 minutes:\n\n{link}\n\n"
            "If you did not request this reset, you can ignore this message.",
        )
    return {"message": "If the address is registered and verified, a recovery link has been sent."}


@auth_router.post("/verify-email/request")
def request_email_verification(
    request: Request,
    body: EmailAddress,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    state, repository = request.app.state, _repository(request)
    if not state.email_sender.configured:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    email = _normalize_email(body.email)
    throttle = state.recovery_throttle
    if throttle.locked(email):
        raise HTTPException(status_code=429, detail="Too many verification requests. Try again later.")
    throttle.fail(email)

    user = repository.get_user_by_email(email, verified_only=False)
    if user and not user["email_verified"]:
        token = _new_auth_token(repository, user["username"], "verify_email")
        link = _email_link(state.email_sender, "verify_email", token)
        background_tasks.add_task(
            _send_email_logged,
            state.email_sender,
            email,
            "Verify your Real-Time Log Analyzer email",
            f"Verify your email address using this link within 30 minutes:\n\n{link}\n\n"
            "If you did not request this message, you can ignore it.",
        )
    return {"message": "If an unverified account uses that address, a verification link has been sent."}


@auth_router.post("/password-reset/complete")
def complete_password_reset(request: Request, body: PasswordResetRequest) -> dict[str, bool]:
    repository = _repository(request)
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    username = repository.consume_auth_token(token_hash, "reset_password", datetime.now(timezone.utc))
    if username is None or not repository.update_user_password(username, hash_password(body.password)):
        raise HTTPException(status_code=400, detail="This recovery link is invalid or expired")
    return {"ok": True}


@auth_router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=request.app.state.app_env == "production",
        httponly=True,
        samesite="strict",
    )
    return {"ok": True}


@auth_router.get("/me")
def me(request: Request, username: str | None = Depends(require_user)) -> dict:
    if username is None:
        return {"username": None, "email": None, "email_verified": False}
    user = _repository(request).get_user(username)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return {
        "username": username,
        "email": user["email"],
        "email_verified": bool(user["email_verified"]),
    }
