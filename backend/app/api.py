from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError

from .config import MAX_UPLOAD_BYTES
from .models import AlertRule, AlertRuleCreate, IngestResponse, LogEvent, Metrics, TimelinePoint, TriggeredAlert
from .parser import parse_line
from .repository import LogRepository

router = APIRouter(prefix="/api")


def _repository(request: Request) -> LogRepository:
    return request.app.state.repository


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get("/health")
def health() -> dict[str, str]:
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
    )


@router.get("/metrics", response_model=Metrics)
def metrics(request: Request) -> dict:
    return _repository(request).get_metrics()


@router.get("/timeline", response_model=list[TimelinePoint])
def timeline(request: Request, minutes: int = Query(default=60, ge=1, le=1440)) -> list[dict]:
    return _repository(request).get_timeline(minutes)


@router.get("/services", response_model=list[str])
def services(request: Request) -> list[str]:
    return _repository(request).list_services()


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
    accepted, rejected = await request.app.state.ingestor.ingest_lines(lines)
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
    accepted, rejected = await request.app.state.ingestor.ingest_lines(lines)
    return {"accepted": accepted, "rejected": rejected, "message": "Log file processed."}


@router.get("/alerts/rules", response_model=list[AlertRule])
def alert_rules(request: Request) -> list[dict]:
    rules = _repository(request).list_rules()
    for rule in rules:
        rule["enabled"] = bool(rule["enabled"])
        rule["created_at"] = datetime.fromisoformat(rule["created_at"])
    return rules


@router.post("/alerts/rules", response_model=AlertRule, status_code=201)
def create_alert_rule(request: Request, rule: AlertRuleCreate) -> dict:
    stored = _repository(request).create_rule(rule)
    stored["enabled"] = bool(stored["enabled"])
    stored["created_at"] = datetime.fromisoformat(stored["created_at"])
    return stored


@router.get("/alerts", response_model=list[TriggeredAlert])
def triggered_alerts(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    return _repository(request).list_alerts(limit)


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
