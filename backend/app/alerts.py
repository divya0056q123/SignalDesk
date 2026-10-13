from datetime import datetime, timedelta, timezone
from typing import Any

from .repository import LogRepository


class AlertEvaluator:
    def __init__(self, repository: LogRepository):
        self.repository = repository

    def evaluate(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        triggered = []
        for rule in self.repository.enabled_rules():
            window = timedelta(minutes=rule["window_minutes"])
            since = now - window
            count = self.repository.count_errors_since(since)
            if count > rule["threshold"] and not self.repository.recent_rule_alert(rule["id"], since):
                triggered.append(self.repository.insert_alert(rule, count))
        return triggered
