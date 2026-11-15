from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "UNKNOWN"]


class LogEvent(BaseModel):
    id: int
    timestamp: datetime
    severity: Severity
    service: str
    source: str
    message: str


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    threshold: int = Field(ge=1, le=100_000)
    window_minutes: int = Field(ge=1, le=1440)
    enabled: bool = True


class AlertRule(AlertRuleCreate):
    id: int
    created_at: datetime


class TriggeredAlert(BaseModel):
    id: int
    rule_id: int
    rule_name: str
    message: str
    count: int
    triggered_at: datetime


class Metrics(BaseModel):
    total_events: int
    error_rate: float
    events_per_second: float
    by_severity: dict[str, int]


class TimelinePoint(BaseModel):
    bucket: datetime
    total: int
    errors: int
    spike: bool


class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    message: str


class Anomaly(BaseModel):
    bucket: datetime
    metric: Literal["errors", "total"]
    observed: int
    expected: float
    score: float
    level: Literal["medium", "high"]


class LogCluster(BaseModel):
    id: str
    template: str
    count: int
    severity: Severity
    services: list[str]
    first_seen: datetime
    last_seen: datetime
    example: str


class IngestEvent(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    severity: Severity = "INFO"
    service: str = Field(default="external", min_length=1, max_length=100)
    source: str = Field(default="api", max_length=200)
    timestamp: datetime | None = None


class IngestBatch(BaseModel):
    events: list[IngestEvent] = Field(min_length=1)


class IngestKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must contain a non-whitespace character")
        return normalized


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    email: str = Field(min_length=6, max_length=254)


class LoginCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class AuthSession(BaseModel):
    username: str
    email_verified: bool = False


class RegistrationResponse(BaseModel):
    username: str
    email_verification_sent: bool


class EmailAddress(BaseModel):
    email: str = Field(min_length=6, max_length=254)


class EmailTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=200)


class PasswordResetRequest(EmailTokenRequest):
    password: str = Field(min_length=8, max_length=128)
