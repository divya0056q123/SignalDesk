from typing import Any

from .alerts import AlertEvaluator
from .parser import parse_line
from .repository import LogRepository
from .websocket import EventHub


class LogIngestor:
    def __init__(self, repository: LogRepository, alerts: AlertEvaluator, hub: EventHub):
        self.repository = repository
        self.alerts = alerts
        self.hub = hub

    async def ingest_line(self, line: str) -> dict[str, Any]:
        stored = self.repository.insert_log(parse_line(line))
        event = {"type": "log", "data": stored}
        await self.hub.broadcast(event)
        for alert in self.alerts.evaluate():
            await self.hub.broadcast({"type": "alert", "data": alert})
        return stored

    async def ingest_lines(self, lines: list[str]) -> tuple[int, int]:
        accepted = rejected = 0
        for line in lines:
            if not line.strip():
                continue
            if len(line) > 100_000:
                rejected += 1
                continue
            await self.ingest_line(line)
            accepted += 1
        return accepted, rejected
