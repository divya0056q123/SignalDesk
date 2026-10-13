import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .models import AlertRuleCreate


class LogRepository(Protocol):
    def initialize(self) -> None: ...
    def count_logs(self) -> int: ...
    def insert_log(self, event: dict[str, Any]) -> dict[str, Any]: ...
    def query_logs(self, **filters: Any) -> list[dict[str, Any]]: ...
    def get_metrics(self) -> dict[str, Any]: ...
    def get_timeline(self, minutes: int = 60) -> list[dict[str, Any]]: ...
    def list_services(self) -> list[str]: ...
    def create_rule(self, rule: AlertRuleCreate) -> dict[str, Any]: ...
    def list_rules(self) -> list[dict[str, Any]]: ...
    def enabled_rules(self) -> list[dict[str, Any]]: ...
    def count_errors_since(self, since: datetime) -> int: ...
    def recent_rule_alert(self, rule_id: int, since: datetime) -> bool: ...
    def insert_alert(self, rule: dict[str, Any], count: int) -> dict[str, Any]: ...
    def list_alerts(self, limit: int = 50) -> list[dict[str, Any]]: ...


class SQLiteRepository:
    """SQLite implementation of the storage boundary; replaceable by another repository."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS log_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    service TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON log_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_logs_severity ON log_events(severity);
                CREATE INDEX IF NOT EXISTS idx_logs_service ON log_events(service);
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    threshold INTEGER NOT NULL,
                    window_minutes INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS triggered_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id INTEGER NOT NULL,
                    rule_name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    triggered_at TEXT NOT NULL,
                    FOREIGN KEY(rule_id) REFERENCES alert_rules(id)
                );
                """
            )

    def count_logs(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM log_events").fetchone()[0])

    def insert_log(self, event: dict[str, Any]) -> dict[str, Any]:
        timestamp = event["timestamp"]
        if isinstance(timestamp, datetime):
            timestamp = timestamp.astimezone(timezone.utc).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO log_events(timestamp,severity,service,source,message) VALUES(?,?,?,?,?)",
                (timestamp, event["severity"], event["service"], event["source"], event["message"]),
            )
            return dict(db.execute("SELECT * FROM log_events WHERE id=?", (cursor.lastrowid,)).fetchone())

    @staticmethod
    def _log(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["timestamp"] = datetime.fromisoformat(item["timestamp"])
        return item

    def query_logs(
        self,
        *,
        search: str | None = None,
        severity: str | None = None,
        service: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(message LIKE ? OR service LIKE ? OR source LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        if severity:
            clauses.append("severity = ?")
            params.append(severity.upper())
        if service:
            clauses.append("service = ?")
            params.append(service)
        if start:
            clauses.append("timestamp >= ?")
            params.append(start.astimezone(timezone.utc).isoformat())
        if end:
            clauses.append("timestamp <= ?")
            params.append(end.astimezone(timezone.utc).isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM log_events {where} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._log(row) for row in rows]

    def get_metrics(self) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        with self._connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM log_events").fetchone()[0])
            counts = {
                row["severity"]: int(row["count"])
                for row in db.execute(
                    "SELECT severity, COUNT(*) AS count FROM log_events GROUP BY severity"
                )
            }
            errors = counts.get("ERROR", 0) + counts.get("CRITICAL", 0)
            recent = int(
                db.execute("SELECT COUNT(*) FROM log_events WHERE timestamp >= ?", (cutoff,)).fetchone()[0]
            )
        return {
            "total_events": total,
            "error_rate": errors / total if total else 0.0,
            "events_per_second": recent / 60,
            "by_severity": counts,
        }

    def get_timeline(self, minutes: int = 60) -> list[dict[str, Any]]:
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        cutoff = end - timedelta(minutes=minutes - 1)
        with self._connect() as db:
            rows = db.execute(
                """SELECT substr(timestamp,1,16) AS minute, COUNT(*) AS total,
                   SUM(CASE WHEN severity IN ('ERROR','CRITICAL') THEN 1 ELSE 0 END) AS errors
                   FROM log_events WHERE timestamp >= ? GROUP BY minute ORDER BY minute""",
                (cutoff.isoformat(),),
            ).fetchall()
        counts = {row["minute"]: (row["total"], row["errors"]) for row in rows}
        points = []
        for index in range(minutes):
            bucket = cutoff + timedelta(minutes=index)
            total, errors = counts.get(bucket.strftime("%Y-%m-%dT%H:%M"), (0, 0))
            points.append({"bucket": bucket, "total": total, "errors": errors})
        average = sum(point["errors"] for point in points) / max(1, len(points))
        threshold = max(3, average * 2.5)
        for point in points:
            point["spike"] = point["errors"] >= threshold and point["errors"] > 0
        return points

    def list_services(self) -> list[str]:
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT DISTINCT service FROM log_events ORDER BY service")]

    def create_rule(self, rule: AlertRuleCreate) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO alert_rules(name,threshold,window_minutes,enabled,created_at) VALUES(?,?,?,?,?)",
                (rule.name, rule.threshold, rule.window_minutes, int(rule.enabled), now),
            )
            return dict(db.execute("SELECT * FROM alert_rules WHERE id=?", (cursor.lastrowid,)).fetchone())

    def list_rules(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM alert_rules ORDER BY id DESC")]

    def enabled_rules(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM alert_rules WHERE enabled=1")]

    def count_errors_since(self, since: datetime) -> int:
        with self._connect() as db:
            return int(
                db.execute(
                    "SELECT COUNT(*) FROM log_events WHERE severity IN ('ERROR','CRITICAL') AND timestamp >= ?",
                    (since.astimezone(timezone.utc).isoformat(),),
                ).fetchone()[0]
            )

    def recent_rule_alert(self, rule_id: int, since: datetime) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM triggered_alerts WHERE rule_id=? AND triggered_at >= ? LIMIT 1",
                (rule_id, since.astimezone(timezone.utc).isoformat()),
            ).fetchone()
        return row is not None

    def insert_alert(self, rule: dict[str, Any], count: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        message = f'{count} errors detected in the last {rule["window_minutes"]} minute(s) (threshold: {rule["threshold"]}).'
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO triggered_alerts(rule_id,rule_name,message,count,triggered_at) VALUES(?,?,?,?,?)",
                (rule["id"], rule["name"], message, count, now),
            )
            result = dict(db.execute("SELECT * FROM triggered_alerts WHERE id=?", (cursor.lastrowid,)).fetchone())
        result["triggered_at"] = datetime.fromisoformat(result["triggered_at"])
        return result

    def list_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM triggered_alerts ORDER BY triggered_at DESC, id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        results = [dict(row) for row in rows]
        for item in results:
            item["triggered_at"] = datetime.fromisoformat(item["triggered_at"])
        return results
