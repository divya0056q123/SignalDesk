import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol

from .models import AlertRuleCreate


class UserExistsError(Exception):
    """Raised when a username is already registered (storage-independent)."""


class EmailAlreadyUsedError(Exception):
    """Raised when an email address is already associated with an account."""


class IngestKeyLimitError(Exception):
    """Raised when an account already has the maximum number of active ingestion keys."""


class LogRepository(Protocol):
    def initialize(self) -> None: ...
    def health_check(self) -> None: ...
    def count_logs(self, tenant_id: str = "default") -> int: ...
    def insert_log(self, event: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]: ...
    def insert_logs(self, events: list[dict[str, Any]], tenant_id: str = "default") -> list[dict[str, Any]]: ...
    def query_logs(self, **filters: Any) -> list[dict[str, Any]]: ...
    def get_metrics(self, tenant_id: str = "default") -> dict[str, Any]: ...
    def get_timeline(self, minutes: int = 60, tenant_id: str = "default") -> list[dict[str, Any]]: ...
    def list_services(self, tenant_id: str = "default") -> list[str]: ...
    def create_rule(self, rule: AlertRuleCreate, tenant_id: str = "default") -> dict[str, Any]: ...
    def list_rules(self, tenant_id: str = "default") -> list[dict[str, Any]]: ...
    def enabled_rules(self, tenant_id: str = "default") -> list[dict[str, Any]]: ...
    def count_errors_since(self, since: datetime, tenant_id: str = "default") -> int: ...
    def recent_rule_alert(self, rule_id: int, since: datetime, tenant_id: str = "default") -> bool: ...
    def insert_alert(self, rule: dict[str, Any], count: int, tenant_id: str = "default") -> dict[str, Any]: ...
    def list_alerts(self, limit: int = 50, tenant_id: str = "default") -> list[dict[str, Any]]: ...
    def logs_since(self, since: datetime, limit: int = 5000, tenant_id: str = "default") -> list[dict[str, Any]]: ...
    def count_users(self) -> int: ...
    def create_user(self, username: str, password_hash: str, email: str) -> dict[str, Any]: ...
    def create_first_user(self, username: str, password_hash: str, email: str) -> dict[str, Any] | None: ...
    def get_user(self, username: str) -> dict[str, Any] | None: ...
    def get_user_by_email(self, email: str, verified_only: bool = True) -> dict[str, Any] | None: ...
    def update_user_email(self, username: str, email: str) -> None: ...
    def mark_email_verified(self, username: str) -> bool: ...
    def update_user_password(self, username: str, password_hash: str) -> bool: ...
    def issue_auth_token(self, username: str, purpose: str, token_hash: str, expires_at: datetime) -> None: ...
    def consume_auth_token(self, token_hash: str, purpose: str, now: datetime) -> str | None: ...
    def create_ingest_key(self, username: str, key_id: str, name: str, key_hash: str, created_at: datetime, limit: int) -> None: ...
    def list_ingest_keys(self, username: str) -> list[dict[str, Any]]: ...
    def revoke_ingest_key(self, username: str, key_id: str) -> bool: ...
    def get_ingest_key_owner(self, key_hash: str) -> str | None: ...


class SQLiteRepository:
    """SQLite implementation of the storage boundary; replaceable by another repository."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS log_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
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
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    name TEXT NOT NULL,
                    threshold INTEGER NOT NULL,
                    window_minutes INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    email_verified INTEGER NOT NULL DEFAULT 0,
                    session_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                    purpose TEXT NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ingest_keys (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS triggered_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    rule_id INTEGER NOT NULL,
                    rule_name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    triggered_at TEXT NOT NULL,
                    FOREIGN KEY(rule_id) REFERENCES alert_rules(id)
                );
                """
            )
            user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
            if "email" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN email TEXT")
            if "email_verified" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
            if "session_version" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email IS NOT NULL"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_purpose ON auth_tokens(username, purpose)")
            for table in ("log_events", "alert_rules", "triggered_alerts"):
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if "tenant_id" not in columns:
                    db.execute(
                        f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
                    )
            db.execute("CREATE INDEX IF NOT EXISTS idx_logs_tenant_timestamp ON log_events(tenant_id, timestamp)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_rules_tenant ON alert_rules(tenant_id, enabled)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_alerts_tenant_time ON triggered_alerts(tenant_id, triggered_at)")
            first_user = db.execute("SELECT username FROM users ORDER BY id LIMIT 1").fetchone()
            if first_user:
                for table in ("log_events", "alert_rules", "triggered_alerts"):
                    db.execute(
                        f"UPDATE {table} SET tenant_id=? WHERE tenant_id='default'",
                        (first_user["username"],),
                    )

    def create_ingest_key(
        self, username: str, key_id: str, name: str, key_hash: str, created_at: datetime, limit: int
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "SELECT COUNT(*) FROM ingest_keys WHERE username=?", (username,)
            ).fetchone()[0]
            if count >= limit:
                raise IngestKeyLimitError
            db.execute(
                "INSERT INTO ingest_keys(id, username, name, key_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (key_id, username, name, key_hash, created_at.isoformat()),
            )

    def list_ingest_keys(self, username: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, name, created_at FROM ingest_keys WHERE username=? ORDER BY created_at DESC, id",
                (username,),
            ).fetchall()
            return [dict(row) for row in rows]

    def revoke_ingest_key(self, username: str, key_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM ingest_keys WHERE id=? AND username=?", (key_id, username)
            )
            return cursor.rowcount > 0

    def get_ingest_key_owner(self, key_hash: str) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT username FROM ingest_keys WHERE key_hash=?", (key_hash,)
            ).fetchone()
            return row["username"] if row else None

    def health_check(self) -> None:
        with self._connect() as db:
            db.execute("SELECT 1").fetchone()

    def count_logs(self, tenant_id: str = "default") -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM log_events WHERE tenant_id=?", (tenant_id,)).fetchone()[0])

    def insert_log(self, event: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
        return self.insert_logs([event], tenant_id)[0]

    def insert_logs(self, events: list[dict[str, Any]], tenant_id: str = "default") -> list[dict[str, Any]]:
        if not events:
            return []
        with self._connect() as db:
            inserted = []
            for event in events:
                timestamp = event["timestamp"]
                if isinstance(timestamp, datetime):
                    timestamp = timestamp.astimezone(timezone.utc).isoformat()
                cursor = db.execute(
                    "INSERT INTO log_events(tenant_id,timestamp,severity,service,source,message) VALUES(?,?,?,?,?,?)",
                    (tenant_id, timestamp, event["severity"], event["service"], event["source"], event["message"]),
                )
                inserted.append(dict(db.execute(
                    "SELECT * FROM log_events WHERE id=?", (cursor.lastrowid,)
                ).fetchone()))
            return inserted

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
        tenant_id: str = "default",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
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

    def get_metrics(self, tenant_id: str = "default") -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        with self._connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM log_events WHERE tenant_id=?", (tenant_id,)).fetchone()[0])
            counts = {
                row["severity"]: int(row["count"])
                for row in db.execute(
                    "SELECT severity, COUNT(*) AS count FROM log_events WHERE tenant_id=? GROUP BY severity",
                    (tenant_id,),
                )
            }
            errors = counts.get("ERROR", 0) + counts.get("CRITICAL", 0)
            recent = int(
                db.execute(
                    "SELECT COUNT(*) FROM log_events WHERE tenant_id=? AND timestamp >= ?",
                    (tenant_id, cutoff),
                ).fetchone()[0]
            )
        return {
            "total_events": total,
            "error_rate": errors / total if total else 0.0,
            "events_per_second": recent / 60,
            "by_severity": counts,
        }

    def get_timeline(self, minutes: int = 60, tenant_id: str = "default") -> list[dict[str, Any]]:
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        cutoff = end - timedelta(minutes=minutes - 1)
        with self._connect() as db:
            rows = db.execute(
                """SELECT substr(timestamp,1,16) AS minute, COUNT(*) AS total,
                   SUM(CASE WHEN severity IN ('ERROR','CRITICAL') THEN 1 ELSE 0 END) AS errors
                   FROM log_events WHERE tenant_id=? AND timestamp >= ? GROUP BY minute ORDER BY minute""",
                (tenant_id, cutoff.isoformat()),
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

    def list_services(self, tenant_id: str = "default") -> list[str]:
        with self._connect() as db:
            return [
                row[0] for row in db.execute(
                    "SELECT DISTINCT service FROM log_events WHERE tenant_id=? ORDER BY service",
                    (tenant_id,),
                )
            ]

    def create_rule(self, rule: AlertRuleCreate, tenant_id: str = "default") -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO alert_rules(tenant_id,name,threshold,window_minutes,enabled,created_at) VALUES(?,?,?,?,?,?)",
                (tenant_id, rule.name, rule.threshold, rule.window_minutes, int(rule.enabled), now),
            )
            return dict(db.execute("SELECT * FROM alert_rules WHERE id=?", (cursor.lastrowid,)).fetchone())

    def list_rules(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM alert_rules WHERE tenant_id=? ORDER BY id DESC", (tenant_id,)
            )]

    def enabled_rules(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM alert_rules WHERE tenant_id=? AND enabled=1", (tenant_id,)
            )]

    def count_errors_since(self, since: datetime, tenant_id: str = "default") -> int:
        with self._connect() as db:
            return int(
                db.execute(
                    "SELECT COUNT(*) FROM log_events WHERE tenant_id=? AND severity IN ('ERROR','CRITICAL') AND timestamp >= ?",
                    (tenant_id, since.astimezone(timezone.utc).isoformat()),
                ).fetchone()[0]
            )

    def recent_rule_alert(self, rule_id: int, since: datetime, tenant_id: str = "default") -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM triggered_alerts WHERE tenant_id=? AND rule_id=? AND triggered_at >= ? LIMIT 1",
                (tenant_id, rule_id, since.astimezone(timezone.utc).isoformat()),
            ).fetchone()
        return row is not None

    def insert_alert(self, rule: dict[str, Any], count: int, tenant_id: str = "default") -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        message = f'{count} errors detected in the last {rule["window_minutes"]} minute(s) (threshold: {rule["threshold"]}).'
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO triggered_alerts(tenant_id,rule_id,rule_name,message,count,triggered_at) VALUES(?,?,?,?,?,?)",
                (tenant_id, rule["id"], rule["name"], message, count, now),
            )
            result = dict(db.execute("SELECT * FROM triggered_alerts WHERE id=?", (cursor.lastrowid,)).fetchone())
        result["triggered_at"] = datetime.fromisoformat(result["triggered_at"])
        return result

    def list_alerts(self, limit: int = 50, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM triggered_alerts WHERE tenant_id=? ORDER BY triggered_at DESC, id DESC LIMIT ?",
                (tenant_id, max(1, min(limit, 200))),
            ).fetchall()
        results = [dict(row) for row in rows]
        for item in results:
            item["triggered_at"] = datetime.fromisoformat(item["triggered_at"])
        return results

    def logs_since(self, since: datetime, limit: int = 5000, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM log_events WHERE tenant_id=? AND timestamp >= ? ORDER BY timestamp DESC, id DESC LIMIT ?",
                (tenant_id, since.astimezone(timezone.utc).isoformat(), max(1, min(limit, 20000))),
            ).fetchall()
        return [self._log(row) for row in rows]

    def count_users(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, username: str, password_hash: str, email: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as db:
                cursor = db.execute(
                    "INSERT INTO users(username,password_hash,email,created_at) VALUES(?,?,?,?)",
                    (username, password_hash, email, now),
                )
                return dict(db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())
        except sqlite3.IntegrityError as exc:
            if "users.email" in str(exc):
                raise EmailAlreadyUsedError(email) from exc
            raise UserExistsError(username) from exc

    def create_first_user(self, username: str, password_hash: str, email: str) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                return None
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,email,created_at) VALUES(?,?,?,?)",
                (username, password_hash, email, now),
            )
            db.execute("UPDATE log_events SET tenant_id=? WHERE tenant_id='default'", (username,))
            db.execute("UPDATE alert_rules SET tenant_id=? WHERE tenant_id='default'", (username,))
            db.execute("UPDATE triggered_alerts SET tenant_id=? WHERE tenant_id='default'", (username,))
            return dict(db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str, verified_only: bool = True) -> dict[str, Any] | None:
        query = "SELECT * FROM users WHERE email=?"
        params: tuple[Any, ...] = (email,)
        if verified_only:
            query += " AND email_verified=1"
        with self._connect() as db:
            row = db.execute(query, params).fetchone()
        return dict(row) if row else None

    def update_user_email(self, username: str, email: str) -> None:
        try:
            with self._connect() as db:
                db.execute(
                    "UPDATE users SET email=?, email_verified=0 WHERE username=?",
                    (email, username),
                )
                db.execute("DELETE FROM auth_tokens WHERE username=?", (username,))
        except sqlite3.IntegrityError as exc:
            raise EmailAlreadyUsedError(email) from exc

    def mark_email_verified(self, username: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("UPDATE users SET email_verified=1 WHERE username=?", (username,))
        return cursor.rowcount == 1

    def update_user_password(self, username: str, password_hash: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE users SET password_hash=?, session_version=session_version+1 WHERE username=?",
                (password_hash, username),
            )
            db.execute("DELETE FROM auth_tokens WHERE username=?", (username,))
        return cursor.rowcount == 1

    def issue_auth_token(self, username: str, purpose: str, token_hash: str, expires_at: datetime) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM auth_tokens WHERE username=? AND purpose=?", (username, purpose))
            db.execute(
                "INSERT INTO auth_tokens(token_hash,username,purpose,expires_at) VALUES(?,?,?,?)",
                (token_hash, username, purpose, expires_at.astimezone(timezone.utc).isoformat()),
            )

    def consume_auth_token(self, token_hash: str, purpose: str, now: datetime) -> str | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT username FROM auth_tokens WHERE token_hash=? AND purpose=? AND expires_at>?",
                (token_hash, purpose, now.astimezone(timezone.utc).isoformat()),
            ).fetchone()
            db.execute("DELETE FROM auth_tokens WHERE token_hash=?", (token_hash,))
        return str(row["username"]) if row else None
