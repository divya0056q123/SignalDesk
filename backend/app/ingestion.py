from datetime import datetime, timezone
from typing import Any

from .alerts import AlertEvaluator
from .anomaly import detect_anomalies
from .notifier import WebhookNotifier
from .parser import parse_line
from .repository import LogRepository
from .websocket import EventHub


class LogIngestor:
    def __init__(
        self,
        repository: LogRepository,
        alerts: AlertEvaluator,
        hub: EventHub,
        notifier: WebhookNotifier | None = None,
    ):
        self.repository = repository
        self.alerts = alerts
        self.hub = hub
        self.notifier = notifier or WebhookNotifier(None)
        self._announced: set[tuple[str, str, str]] = set()

    async def _publish_alerts(self, tenant_id: str) -> None:
        for alert in self.alerts.evaluate(tenant_id):
            await self.hub.broadcast({"type": "alert", "data": alert}, tenant_id)
            await self.notifier.send(self.notifier.format_alert(alert))

    async def ingest_line(self, line: str, tenant_id: str = "default") -> dict[str, Any]:
        return (await self.ingest_events([parse_line(line)], tenant_id))[0]

    async def ingest_event(self, event: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
        """Store an already-structured event (HTTP ingestion API)."""
        return (await self.ingest_events([event], tenant_id))[0]

    async def ingest_events(
        self, events: list[dict[str, Any]], tenant_id: str = "default"
    ) -> list[dict[str, Any]]:
        """Persist a batch atomically, then publish each event and evaluate rules once."""
        normalized = []
        for event in events:
            stamp = event.get("timestamp") or datetime.now(timezone.utc)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            normalized.append({**event, "timestamp": stamp})
        stored_events = self.repository.insert_logs(normalized, tenant_id)
        for stored in stored_events:
            await self.hub.broadcast({"type": "log", "data": stored}, tenant_id)
        await self._publish_alerts(tenant_id)
        return stored_events

    async def ingest_lines(self, lines: list[str], tenant_id: str = "default") -> tuple[int, int]:
        accepted = rejected = 0
        events = []
        for line in lines:
            if not line.strip():
                continue
            if len(line) > 100_000:
                rejected += 1
                continue
            events.append(parse_line(line))
        if events:
            await self.ingest_events(events, tenant_id)
            accepted = len(events)
        if accepted:
            await self.check_anomalies(tenant_id)
        return accepted, rejected

    async def check_anomalies(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        """Run the detector on the last 60 minutes; announce each new anomaly once."""
        points = self.repository.get_timeline(60, tenant_id)
        fresh = []
        for metric in ("errors", "total"):
            for anomaly in detect_anomalies(points, metric):
                key = (tenant_id, metric, anomaly["bucket"].isoformat())
                if key in self._announced:
                    continue
                self._announced.add(key)
                fresh.append(anomaly)
                await self.hub.broadcast(
                    {"type": "anomaly", "data": {**anomaly, "bucket": key[2]}}, tenant_id
                )
                await self.notifier.send(self.notifier.format_anomaly(anomaly))
        if len(self._announced) > 5000:
            self._announced.clear()
        return fresh
