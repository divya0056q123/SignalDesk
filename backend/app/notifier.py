"""Outbound notifications (Slack-compatible incoming webhook, also fine for Discord/Teams relays)."""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger("signaldesk.notifier")


class WebhookNotifier:
    def __init__(self, url: str | None, timeout: float = 5.0):
        self.url = url or None
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.url) and self.url.startswith(("https://", "http://"))

    def _post(self, text: str) -> bool:
        request = urllib.request.Request(
            self.url,  # type: ignore[arg-type]
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - URL is operator-configured
                return 200 <= response.status < 300
        except Exception as exc:  # never let a dead webhook break ingestion
            logger.warning("webhook delivery failed: %s", exc)
            return False

    async def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        return await asyncio.to_thread(self._post, text)

    @staticmethod
    def format_alert(alert: dict[str, Any]) -> str:
        return f":rotating_light: *{alert['rule_name']}* - {alert['message']}"

    @staticmethod
    def format_anomaly(anomaly: dict[str, Any]) -> str:
        return (
            f":chart_with_upwards_trend: *Anomaly ({anomaly['level']})* in {anomaly['metric']}: "
            f"{anomaly['observed']} events/min vs ~{anomaly['expected']} expected (score {anomaly['score']})."
        )
