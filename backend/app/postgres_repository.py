"""PostgreSQL implementation of the same repository interface as SQLiteRepository.

Selected by setting DATABASE_URL (postgresql://user:pass@host:5432/dbname).
Requires ``psycopg[binary]`` (see requirements-postgres.txt). Timestamps are stored as
timestamptz, so time-bucketing uses date_trunc instead of SQLite string slicing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .models import AlertRuleCreate
from .repository import EmailAlreadyUsedError, IngestKeyLimitError, UserExistsError


class PostgresRepository:
    def __init__(self, dsn: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on optional dependency
            raise RuntimeError("PostgreSQL support needs: pip install -r backend/requirements-postgres.txt") from exc
        self._psycopg = psycopg
        self._dict_row = dict_row
        self.dsn = dsn

    def _connect(self):
        return self._psycopg.connect(self.dsn, row_factory=self._dict_row, autocommit=True)

    def initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS log_events (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    timestamp TIMESTAMPTZ NOT NULL,
                    severity TEXT NOT NULL,
                    service TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON log_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_logs_severity ON log_events(severity);
                CREATE INDEX IF NOT EXISTS idx_logs_service ON log_events(service);
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id SERIAL PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    name TEXT NOT NULL,
                    threshold INTEGER NOT NULL,
                    window_minutes INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    session_version INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                    purpose TEXT NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
                    expires_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ingest_keys (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS triggered_alerts (
                    id SERIAL PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    rule_id INTEGER NOT NULL REFERENCES alert_rules(id),
                    rule_name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    triggered_at TIMESTAMPTZ NOT NULL
                );
                ALTER TABLE log_events ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
                ALTER TABLE alert_rules ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
                ALTER TABLE triggered_alerts ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_purpose ON auth_tokens(username, purpose);
                CREATE INDEX IF NOT EXISTS idx_logs_tenant_timestamp ON log_events(tenant_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_rules_tenant ON alert_rules(tenant_id, enabled);
                CREATE INDEX IF NOT EXISTS idx_alerts_tenant_time ON triggered_alerts(tenant_id, triggered_at);
                """
            )
            first_user = db.execute("SELECT username FROM users ORDER BY id LIMIT 1").fetchone()
            if first_user:
                for table in ("log_events", "alert_rules", "triggered_alerts"):
                    db.execute(
                        f"UPDATE {table} SET tenant_id=%s WHERE tenant_id='default'",
                        (first_user["username"],),
                    )

    def health_check(self) -> None:
        with self._connect() as db:
            db.execute("SELECT 1").fetchone()

    def create_ingest_key(
        self, username: str, key_id: str, name: str, key_hash: str, created_at: datetime, limit: int
    ) -> None:
        with self._connect() as db:
            with db.transaction():
                db.execute("SELECT username FROM users WHERE username=%s FOR UPDATE", (username,))
                count = db.execute(
                    "SELECT COUNT(*) AS n FROM ingest_keys WHERE username=%s", (username,)
                ).fetchone()["n"]
                if count >= limit:
                    raise IngestKeyLimitError
                db.execute(
                    "INSERT INTO ingest_keys(id, username, name, key_hash, created_at) VALUES (%s, %s, %s, %s, %s)",
                    (key_id, username, name, key_hash, created_at),
                )

    def list_ingest_keys(self, username: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return db.execute(
                "SELECT id, name, created_at FROM ingest_keys WHERE username=%s ORDER BY created_at DESC, id",
                (username,),
            ).fetchall()

    def revoke_ingest_key(self, username: str, key_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM ingest_keys WHERE id=%s AND username=%s", (key_id, username))
            return cursor.rowcount > 0

    def get_ingest_key_owner(self, key_hash: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT username FROM ingest_keys WHERE key_hash=%s", (key_hash,)).fetchone()
            return row["username"] if row else None

    # ---- logs -------------------------------------------------------------
    def count_logs(self, tenant_id: str = "default") -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) AS n FROM log_events WHERE tenant_id=%s", (tenant_id,)).fetchone()["n"])

    def insert_log(self, event: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
        return self.insert_logs([event], tenant_id)[0]

    def insert_logs(self, events: list[dict[str, Any]], tenant_id: str = "default") -> list[dict[str, Any]]:
        if not events:
            return []
        with self._connect() as db:
            with db.transaction():
                return [
                    db.execute(
                        "INSERT INTO log_events(tenant_id,timestamp,severity,service,source,message) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                        (tenant_id, event["timestamp"], event["severity"], event["service"], event["source"], event["message"]),
                    ).fetchone()
                    for event in events
                ]

    def query_logs(self, *, search=None, severity=None, service=None, start=None, end=None, limit=100, offset=0,
                   tenant_id="default"):
        clauses: list[str] = ["tenant_id = %s"]
        params: list[Any] = [tenant_id]
        if search:
            clauses.append("(message ILIKE %s OR service ILIKE %s OR source ILIKE %s)")
            params.extend([f"%{search}%"] * 3)
        if severity:
            clauses.append("severity = %s")
            params.append(severity.upper())
        if service:
            clauses.append("service = %s")
            params.append(service)
        if start:
            clauses.append("timestamp >= %s")
            params.append(start)
        if end:
            clauses.append("timestamp <= %s")
            params.append(end)
        where = f"WHERE {' AND '.join(clauses)}"
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._connect() as db:
            return db.execute(
                f"SELECT * FROM log_events {where} ORDER BY timestamp DESC, id DESC LIMIT %s OFFSET %s", params
            ).fetchall()

    def logs_since(self, since: datetime, limit: int = 5000, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._connect() as db:
            return db.execute(
                "SELECT * FROM log_events WHERE tenant_id=%s AND timestamp >= %s ORDER BY timestamp DESC, id DESC LIMIT %s",
                (tenant_id, since, max(1, min(limit, 20000))),
            ).fetchall()

    def get_metrics(self, tenant_id: str = "default") -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        with self._connect() as db:
            counts = {r["severity"]: int(r["n"]) for r in db.execute(
                "SELECT severity, COUNT(*) AS n FROM log_events WHERE tenant_id=%s GROUP BY severity", (tenant_id,)
            )}
            recent = int(db.execute(
                "SELECT COUNT(*) AS n FROM log_events WHERE tenant_id=%s AND timestamp >= %s", (tenant_id, cutoff)
            ).fetchone()["n"])
        total = sum(counts.values())
        errors = counts.get("ERROR", 0) + counts.get("CRITICAL", 0)
        return {"total_events": total, "error_rate": errors / total if total else 0.0,
                "events_per_second": recent / 60, "by_severity": counts}

    def get_timeline(self, minutes: int = 60, tenant_id: str = "default") -> list[dict[str, Any]]:
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        cutoff = end - timedelta(minutes=minutes - 1)
        with self._connect() as db:
            rows = db.execute(
                """SELECT date_trunc('minute', timestamp) AS minute, COUNT(*) AS total,
                   SUM(CASE WHEN severity IN ('ERROR','CRITICAL') THEN 1 ELSE 0 END) AS errors
                   FROM log_events WHERE tenant_id=%s AND timestamp >= %s GROUP BY minute ORDER BY minute""",
                (tenant_id, cutoff),
            ).fetchall()
        counts = {r["minute"].astimezone(timezone.utc): (int(r["total"]), int(r["errors"])) for r in rows}
        points = []
        for index in range(minutes):
            bucket = cutoff + timedelta(minutes=index)
            total, errors = counts.get(bucket, (0, 0))
            points.append({"bucket": bucket, "total": total, "errors": errors})
        average = sum(p["errors"] for p in points) / max(1, len(points))
        threshold = max(3, average * 2.5)
        for p in points:
            p["spike"] = p["errors"] >= threshold and p["errors"] > 0
        return points

    def list_services(self, tenant_id: str = "default") -> list[str]:
        with self._connect() as db:
            return [r["service"] for r in db.execute(
                "SELECT DISTINCT service FROM log_events WHERE tenant_id=%s ORDER BY service", (tenant_id,)
            )]

    # ---- alert rules ------------------------------------------------------
    @staticmethod
    def _iso(row: dict[str, Any], *fields: str) -> dict[str, Any]:
        # The API layer expects ISO strings for rule.created_at (as SQLite returns them).
        for field in fields:
            if isinstance(row.get(field), datetime):
                row[field] = row[field].isoformat()
        return row

    def create_rule(self, rule: AlertRuleCreate, tenant_id: str = "default") -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "INSERT INTO alert_rules(tenant_id,name,threshold,window_minutes,enabled,created_at) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                (tenant_id, rule.name, rule.threshold, rule.window_minutes, int(rule.enabled), datetime.now(timezone.utc)),
            ).fetchone()
        return self._iso(row, "created_at")

    def list_rules(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM alert_rules WHERE tenant_id=%s ORDER BY id DESC", (tenant_id,)).fetchall()
        return [self._iso(r, "created_at") for r in rows]

    def enabled_rules(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._connect() as db:
            return db.execute(
                "SELECT * FROM alert_rules WHERE tenant_id=%s AND enabled=1", (tenant_id,)
            ).fetchall()

    def count_errors_since(self, since: datetime, tenant_id: str = "default") -> int:
        with self._connect() as db:
            return int(db.execute(
                "SELECT COUNT(*) AS n FROM log_events WHERE tenant_id=%s AND severity IN ('ERROR','CRITICAL') AND timestamp >= %s",
                (tenant_id, since),
            ).fetchone()["n"])

    def recent_rule_alert(self, rule_id: int, since: datetime, tenant_id: str = "default") -> bool:
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM triggered_alerts WHERE tenant_id=%s AND rule_id=%s AND triggered_at >= %s LIMIT 1",
                (tenant_id, rule_id, since),
            ).fetchone() is not None

    def insert_alert(self, rule: dict[str, Any], count: int, tenant_id: str = "default") -> dict[str, Any]:
        message = f'{count} errors detected in the last {rule["window_minutes"]} minute(s) (threshold: {rule["threshold"]}).'
        with self._connect() as db:
            return db.execute(
                "INSERT INTO triggered_alerts(tenant_id,rule_id,rule_name,message,count,triggered_at) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                (tenant_id, rule["id"], rule["name"], message, count, datetime.now(timezone.utc)),
            ).fetchone()

    def list_alerts(self, limit: int = 50, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._connect() as db:
            return db.execute(
                "SELECT * FROM triggered_alerts WHERE tenant_id=%s ORDER BY triggered_at DESC, id DESC LIMIT %s",
                (tenant_id, max(1, min(limit, 200))),
            ).fetchall()

    # ---- users ------------------------------------------------------------
    def count_users(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])

    def create_user(self, username: str, password_hash: str, email: str) -> dict[str, Any]:
        try:
            with self._connect() as db:
                return db.execute(
                    "INSERT INTO users(username,password_hash,email,created_at) VALUES(%s,%s,%s,%s) RETURNING *",
                    (username, password_hash, email, datetime.now(timezone.utc)),
                ).fetchone()
        except self._psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "idx_users_email_unique":
                raise EmailAlreadyUsedError(email) from exc
            raise UserExistsError(username) from exc

    def create_first_user(self, username: str, password_hash: str, email: str) -> dict[str, Any] | None:
        with self._connect() as db:
            with db.transaction():
                db.execute("LOCK TABLE users IN EXCLUSIVE MODE")
                if db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]:
                    return None
                user = db.execute(
                    "INSERT INTO users(username,password_hash,email,created_at) VALUES(%s,%s,%s,%s) RETURNING *",
                    (username, password_hash, email, datetime.now(timezone.utc)),
                ).fetchone()
                for table in ("log_events", "alert_rules", "triggered_alerts"):
                    db.execute(
                        f"UPDATE {table} SET tenant_id=%s WHERE tenant_id='default'",
                        (username,),
                    )
                return user

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return db.execute("SELECT * FROM users WHERE username=%s", (username,)).fetchone()

    def get_user_by_email(self, email: str, verified_only: bool = True) -> dict[str, Any] | None:
        query = "SELECT * FROM users WHERE email=%s"
        params: tuple[Any, ...] = (email,)
        if verified_only:
            query += " AND email_verified=TRUE"
        with self._connect() as db:
            return db.execute(query, params).fetchone()

    def update_user_email(self, username: str, email: str) -> None:
        try:
            with self._connect() as db:
                with db.transaction():
                    db.execute(
                        "UPDATE users SET email=%s, email_verified=FALSE WHERE username=%s",
                        (email, username),
                    )
                    db.execute("DELETE FROM auth_tokens WHERE username=%s", (username,))
        except self._psycopg.errors.UniqueViolation as exc:
            raise EmailAlreadyUsedError(email) from exc

    def mark_email_verified(self, username: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("UPDATE users SET email_verified=TRUE WHERE username=%s", (username,))
            return cursor.rowcount == 1

    def update_user_password(self, username: str, password_hash: str) -> bool:
        with self._connect() as db:
            with db.transaction():
                cursor = db.execute(
                    "UPDATE users SET password_hash=%s, session_version=session_version+1 WHERE username=%s",
                    (password_hash, username),
                )
                db.execute("DELETE FROM auth_tokens WHERE username=%s", (username,))
                return cursor.rowcount == 1

    def issue_auth_token(self, username: str, purpose: str, token_hash: str, expires_at: datetime) -> None:
        with self._connect() as db:
            with db.transaction():
                db.execute("DELETE FROM auth_tokens WHERE username=%s AND purpose=%s", (username, purpose))
                db.execute(
                    "INSERT INTO auth_tokens(token_hash,username,purpose,expires_at) VALUES(%s,%s,%s,%s)",
                    (token_hash, username, purpose, expires_at),
                )

    def consume_auth_token(self, token_hash: str, purpose: str, now: datetime) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "DELETE FROM auth_tokens WHERE token_hash=%s AND purpose=%s AND expires_at>%s RETURNING username",
                (token_hash, purpose, now),
            ).fetchone()
        return str(row["username"]) if row else None
