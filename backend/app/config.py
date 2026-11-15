import os
import secrets
from pathlib import Path

APP_ENV = os.getenv("APP_ENV", "development").lower()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", PROJECT_ROOT / "data" / "logs.db"))
SAMPLE_LOG_PATH = PROJECT_ROOT / "sample-data" / "application.log"
SAMPLE_DATA_ENABLED = os.getenv("SAMPLE_DATA_ENABLED", "true" if APP_ENV != "production" else "false").lower() == "true"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
# Shared secret that external apps send in the X-API-Key header to POST /api/ingest.
# Leave empty to keep the endpoint disabled.
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "")
# Optional Slack-compatible incoming-webhook URL for alert / anomaly notifications.
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").lower()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
MAX_INGEST_BATCH = int(os.getenv("MAX_INGEST_BATCH", "1000"))
MAX_INGEST_BODY_BYTES = int(os.getenv("MAX_INGEST_BODY_BYTES", str(10 * 1024 * 1024)))
# Database: SQLite file by default; set DATABASE_URL=postgresql://user:pass@host:5432/db to use PostgreSQL.
DATABASE_URL = os.getenv("DATABASE_URL", "")
INGEST_TENANT_ID = os.getenv("INGEST_TENANT_ID", "default")
BOOTSTRAP_TOKEN = os.getenv("BOOTSTRAP_TOKEN", "")
# Login. When AUTH_ENABLED=true every dashboard API call needs a bearer token.
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY") or (secrets.token_urlsafe(32) if APP_ENV != "production" else "")
ALLOW_REGISTRATION = os.getenv(
    "ALLOW_REGISTRATION", "true" if APP_ENV != "production" else "false"
).lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "ALLOWED_HOSTS", "*" if APP_ENV != "production" else ""
    ).split(",")
    if host.strip()
]
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173" if APP_ENV != "production" else "",
    ).split(",")
    if origin.strip()
]
