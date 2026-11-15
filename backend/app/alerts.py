from datetime import datetime, timedelta, timezone
from typing import Any

from .repository import LogRepository


class AlertEvaluator:
    def __init__(self, repository: LogRepository):
        self.repository = repository

    def evaluate(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        triggered = []
        for rule in self.repository.enabled_rules(tenant_id):
            window = timedelta(minutes=rule["window_minutes"])
            since = now - window
            count = self.repository.count_errors_since(since, tenant_id)
            if count > rule["threshold"] and not self.repository.recent_rule_alert(rule["id"], since, tenant_id):
                triggered.append(self.repository.insert_alert(rule, count, tenant_id))
        return triggered
