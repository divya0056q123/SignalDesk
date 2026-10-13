from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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
