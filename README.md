# Real-Time Log Analyzer

Real-Time Log Analyzer is a local-first observability dashboard for ingesting, searching, and monitoring application logs. It ships with realistic sample events so the dashboard is useful on first launch.

## Highlights

- Live log ingestion over a WebSocket stream, with reconnect behavior in the browser.
- ISO application, Apache access, and common syslog parsing; unknown or malformed lines stay visible as searchable `UNKNOWN` events.
- Search, severity, service, and time-range filters, plus severity metrics and an error-volume timeline.
- Configurable error-burst rules with persisted trigger history.
- Bounded `.log` / `.txt` uploads, line-size checks, input validation, and parameterized SQLite queries.
- A bounded structured-ingestion request body, in addition to per-event and per-batch validation.
- A repository boundary that isolates storage operations from HTTP routes and alert evaluation.
- Responsive dark dashboard with keyboard-visible focus indicators and reduced-motion support.

## Major-project extensions

| Module | What it adds | Where |
|---|---|---|
| Anomaly detection | Learns "normal" log volume and flags unusual minutes with a robust z-score (median / MAD) instead of a fixed threshold | `backend/app/anomaly.py` |
| Log template mining | Groups thousands of messages into a few patterns (Drain-style masking + similarity merge) | `backend/app/clustering.py` |
| HTTP ingestion API | Other applications push structured events with account-scoped, revocable `X-API-Key` credentials (10 active keys/account) | `POST /api/ingest`, `GET/POST/DELETE /api/ingest-keys` |
| Log shipper | Dependency-free script that tails a file and forwards new lines | `backend/scripts/send_logs.py` |
| Notifications | Alerts and anomalies are posted to a Slack-compatible webhook | `backend/app/notifier.py` |
| Login and sessions | First-run admin setup, PBKDF2 password hashing, signed expiring tokens, login lockout, protected API and WebSocket | `backend/app/auth.py`, `frontend/src/AuthGate.tsx` |
| PostgreSQL option | Same repository interface backed by PostgreSQL (`DATABASE_URL`) | `backend/app/postgres_repository.py` |
| Evaluation harness | Measures precision / recall / F1 on synthetic incidents and labeled real Loghub BGL data | `backend/scripts/evaluate_detection.py`, `backend/scripts/evaluate_loghub.py` |
| Throughput benchmark | Reproducibly measures generated-log parsing plus SQLite persistence on a temporary database | `backend/scripts/benchmark_ingestion.py` |

Run the evaluation: `python backend/scripts/evaluate_detection.py` (50 synthetic runs, 5 injected incidents each):

| Method | Precision | Recall | F1 |
|---|---|---|---|
| Static threshold (original rule) | 0.355 | 1.000 | 0.517 |
| Robust z-score (median / MAD) | 0.865 | 0.988 | 0.917 |

The static rule catches every incident but raises many false alarms; the robust detector keeps recall while removing most of them. These numbers come from synthetic data, so a real deployment should be re-measured on real logs.

Measure local ingestion throughput (the script reports measured output rather than assuming a hardware-independent target):

```powershell
python backend\scripts\benchmark_ingestion.py --events 10000
```

This benchmark covers parsing and transaction-batched SQLite inserts in one process; it deliberately excludes HTTP, WebSocket clients, and webhook delivery. It prints the platform, processor, Python/SQLite versions, event count, elapsed time, and output. Include these values when reporting results; throughput is machine-specific. It uses an automatically cleaned temporary database and does not touch application data.

Reference run: 10,000 events in 0.490 s (20,414 events/s) on Windows 11, Ryzen 5 7520U, CPython 3.13.0, SQLite 3.45.3. This is one local run, not a portable performance guarantee.

Ship logs from another app:

```powershell
# Set INGEST_API_KEY and INGEST_TENANT_ID to an existing account in .env.
# Keep the key private, then restart the backend.
python backend\scripts\send_logs.py C:\path\to\app.log --service myapp --key my-secret --from-start
```

Signed-in users can open **Account → Manage ingestion keys** to create and revoke account-scoped credentials. The plaintext value is shown only once; the database stores only its SHA-256 hash. Send the created value as the `X-API-Key` header to `POST /api/ingest`; incoming events are stored in the key owner's workspace. A user can have at most 10 active keys. Revoking a key immediately prevents further ingestion with it. The optional `INGEST_API_KEY` environment variable remains available for a deployment-wide integration.

### Real-dataset evaluation (Loghub BGL)

The reproducible small-sample results, protocol, limitations, and source provenance are documented in [docs/REAL_WORLD_EVALUATION.md](./docs/REAL_WORLD_EVALUATION.md). The evaluation uses the 2,000-line labeled BGL sample from Loghub, whose first column distinguishes alert from non-alert lines. Download the pinned sample and evaluate the production one-minute error-volume signal:

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/logpai/loghub/374038faa4ca122dd7ca0730372c0b78f76f8597/BGL/BGL_2k.log" `
  -OutFile "BGL_2k.log"
python backend\scripts\evaluate_loghub.py BGL_2k.log --metric errors
```

The small, sparse sample does **not** reproduce the strong synthetic benchmark result at one-minute resolution. Treat coarser buckets as a sensitivity analysis only, not as a replacement for the dashboard's default detector or a full-corpus result. The report discusses this negative result and the next experiment needed.

## Login

Authentication and registration are enabled in local development. New accounts provide an email address for verification and password recovery. Each account has a private workspace for logs, metrics, and alert rules. In the production Compose stack, open registration is disabled after the first account is created.

For a persistent secret across restarts, set `SECRET_KEY` in `.env` (generate it with `python -c "import secrets; print(secrets.token_urlsafe(32))"`):

```text
AUTH_ENABLED=true
SECRET_KEY=<long random string>
ALLOW_REGISTRATION=true
```

Development creates a process-local signing secret when `SECRET_KEY` is empty, so sessions expire on restart. Production fails closed unless a stable secret of at least 32 characters, secure SMTP settings, and an HTTPS `PUBLIC_BASE_URL` are configured. Browser sessions use an HttpOnly, SameSite=Strict cookie; cookie-authenticated writes and WebSocket connections validate the request origin. Sessions last 8 hours, and a username is locked for 60 seconds after five wrong passwords. Production also requires PostgreSQL, explicit host/origin allowlists, disabled sample data, and a bootstrap code for first-account setup. Email verification is required before production login. Serve it behind HTTPS.

Existing data from a pre-isolation database is assigned to its oldest account during the schema migration, preserving the previous shared workspace for that account. Back up the database before upgrading.

### Password recovery

When secure SMTP settings are configured, account holders can request a password-reset link from the sign-in page. Reset and email-verification tokens are single-use, expire after 30 minutes, and are stored only as hashes. Recovery responses do not disclose whether an address is registered. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_SECURITY`, and `PUBLIC_BASE_URL` through the deployment's secret manager; do not commit credentials to source control. Production requires secure SMTP and verified email before login. For local development without SMTP, users can still sign in, but web password recovery is disabled; administrators can reset passwords on the backend host:

```powershell
.\.venv\Scripts\python.exe backend\scripts\reset_password.py
```

Enter the account username, then enter and confirm the new password at the hidden prompts. The command uses the configured `DATABASE_PATH` or `DATABASE_URL`; run it with the same database configuration as the backend. For the production Compose stack, run it inside the backend container:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml exec backend python scripts/reset_password.py
```

Anyone able to run this command with database access can reset an account, so protect the server and database. Password changes invalidate all existing browser and WebSocket sessions; the account holder must sign in again.

Structured ingestion requests are limited to 10 MiB by default (`MAX_INGEST_BODY_BYTES`), independently of the event-count and field-size validation. Adjust this limit for your deployment while keeping an explicit upper bound.

## PostgreSQL

```powershell
# in .env: DATABASE_URL=postgresql://signaldesk:signaldesk@postgres:5432/signaldesk
docker compose --profile postgres up --build
```

Without Docker: `pip install -r backend\requirements-postgres.txt` and set `DATABASE_URL`. Leave it empty to keep using SQLite.

## Architecture

```mermaid
flowchart LR
    subgraph Sources[Log sources]
        FILE[Log file upload]
        SHIPPER[Local log shipper]
        CLIENT[External application]
        DEMO[Sample event generator]
    end
    subgraph Backend[FastAPI backend]
        API[REST API and validation]
        PARSER[Format parser and normalizer]
        INGEST[Batch ingestion service]
        ALERTS[Alert rules]
        ANOMALY[Anomaly detection]
        MINER[Log template miner]
        HUB[WebSocket event hub]
    end
    subgraph Storage[Persistence]
        SQLITE[(SQLite)]
        POSTGRES[(Optional PostgreSQL)]
    end
    subgraph Web[React dashboard]
        AUTH[Signup and login]
        UI[Metrics, charts, logs, alerts]
    end
    FILE --> API
    SHIPPER --> API
    CLIENT --> API
    DEMO --> API
    API --> PARSER --> INGEST
    INGEST --> SQLITE
    INGEST -. alternative .-> POSTGRES
    INGEST --> ALERTS
    INGEST --> ANOMALY
    INGEST --> MINER
    INGEST --> HUB
    HUB -->|live events| UI
    UI -->|REST queries| API
    AUTH -->|HttpOnly session cookie| API
```

### Data flow

1. Log files, the log shipper, external applications, or the sample generator submit events to the backend.
2. The API validates and parses log input, normalizes fields, and stores accepted events in a batch using SQLite or PostgreSQL.
3. Alert rules and anomaly detection evaluate incoming activity; the template miner groups similar messages into patterns.
4. New log events and detections are broadcast over WebSockets. The dashboard also queries REST endpoints for historical logs, metrics, and summaries.
5. The React interface displays live metrics, charts, searchable logs, anomalies, patterns, and alert activity.

```text
.
├── backend/
│   ├── app/
│   │   ├── api.py            # HTTP routes, validation, upload limits
│   │   ├── request_limits.py # Early request-body limits for structured ingestion
│   │   ├── alerts.py         # Error-window rule evaluation
│   │   ├── config.py         # Environment-backed local settings
│   │   ├── ingestion.py      # Parse → persist → publish workflow
│   │   ├── main.py           # FastAPI app factory, startup seed, WebSocket route
│   │   ├── models.py         # Typed API response and request models
│   │   ├── parser.py         # Application, Apache, syslog, and raw-line parser
│   │   ├── repository.py     # SQLite storage implementation / repository boundary
│   │   └── websocket.py      # Connected-client broadcast hub
│   ├── tests/                # Parser, filters, alert, upload, and WebSocket tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx           # Dashboard, filters, live updates, rule creation
│   │   ├── api.ts            # Typed HTTP/WebSocket helpers and query construction
│   │   ├── api.test.ts       # Frontend filter-query behavior
│   │   ├── styles.css        # Responsive dark dashboard styling
│   │   └── types.ts          # Shared frontend data contracts
│   ├── Dockerfile
│   └── vite.config.ts
├── sample-data/application.log
├── docker-compose.yml
└── .env.example
```

SQLite is used for local development and persists in `data/logs.db` (native) or the Compose `log-data` volume. Route and alert code consume the repository interface by convention; a PostgreSQL adapter can implement the same operations without changing the ingestion workflow.

## Run locally with Docker Compose

Requirements: Docker Engine/Desktop with Compose.

This Compose file is for local development only; it exposes the development frontend and API ports directly. For a public deployment, use the separate TLS-enabled setup below.

From the repository root, in PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open [http://localhost:5173](http://localhost:5173). The API is at [http://localhost:8000](http://localhost:8000), and interactive API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs). Stop the services with `Ctrl+C`; remove containers with `docker compose down`. Persisted log data remains in the named volume. To intentionally clear it, run `docker compose down --volumes`.

## Public deployment with HTTPS

The production Compose template uses PostgreSQL, a non-root backend container, a static frontend server, and Caddy for automatic HTTPS. It only publishes ports 80 and 443; the database and application containers are private to the Compose network. Point a DNS name to the server and allow inbound TCP ports 80 and 443 before starting.

In PowerShell, create the ignored environment file and generate unique random values for its secrets:

```powershell
Copy-Item .env.production.example .env.production
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Edit `.env.production`:

- Set `APP_DOMAIN` to the DNS name pointing to your server.
- Replace `SECRET_KEY`, `BOOTSTRAP_TOKEN`, `POSTGRES_ADMIN_PASSWORD`, and `APP_DB_PASSWORD` with distinct random values. The DB password is URL-safe so Compose can construct the PostgreSQL connection string.
- Enter `BOOTSTRAP_TOKEN` in the first-account setup form. Remove it from the deployment environment after creating the account; it is only required again if the database has no users.
- Keep `.env.production` private and out of source control. For a cloud service, use its secret manager instead of a checked-in file.
- Leave `INGEST_API_KEY` empty unless machine ingestion is needed. If enabled, set it only after the account exists and set `INGEST_TENANT_ID` to that account's username.

Start the stack:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml up --build -d
```

Open `https://<APP_DOMAIN>` and create the first account using the setup code. Further registrations are closed by default. Check readiness at `https://<APP_DOMAIN>/api/health`; it verifies database connectivity. Update with the same Compose command after taking a database backup.

This is a hardened single-host deployment template, not a claim of production certification. Before serving real users, configure cloud-managed secrets and independent encrypted backups, test restores, monitor logs/availability, set resource limits and a recovery plan, and review the exact deployed configuration. A read-only review of the source snapshot before the GCP template was added found no reportable vulnerabilities; it did not inspect a live deployment or the new cloud infrastructure. The in-memory login throttling and WebSocket fan-out are single-process only; do not scale backend replicas until these are moved to shared infrastructure. Email recovery, per-account machine-ingestion credentials, and formal compliance controls are not included.

### Google Cloud configuration

A separate Terraform template is available in [deploy/gcp](./deploy/gcp/README.md). It prepares Cloud Run, Cloud SQL, Secret Manager, SMTP-based account email, and a verified custom domain. It is not applied from this repository; review the plan and pricing before provisioning. The template caps the backend at one instance because login throttling and WebSocket fan-out are not yet shared across replicas. Cloud SQL backups and point-in-time recovery are enabled, but independent encrypted exports and restore drills still require operator setup. The template cannot be considered a live deployment until it is applied and verified in your GCP project.

## Run without Docker

Requirements: Python 3.11+ (standard CPython build) and Node.js 20+. The command below selects standard CPython 3.13; substitute another installed 3.11+ version if needed. Free-threaded Python builds may not have wheels for all dependencies yet.

Open two PowerShell terminals at the repository root.

**Backend terminal:**

```powershell
py -3.13 -m venv .venv-rtla
.\.venv-rtla\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Set-Location backend
uvicorn app.main:app --reload
```

**Frontend terminal:**

```powershell
Set-Location frontend
npm install
npm run dev
```

Visit [http://localhost:5173](http://localhost:5173). The frontend dev server proxies `/api` and `/ws` to `http://localhost:8000`. To move the SQLite database, set `DATABASE_PATH` before starting the backend. `MAX_UPLOAD_BYTES` defaults to 5 MiB.

## Tests

Run from the repository root:

```powershell
& .\.venv-rtla\Scripts\python.exe -m pytest backend\tests -q
Set-Location frontend
npm ci
npm test
npm run build
npm audit --audit-level=moderate
```

Backend tests cover common and unknown parsing, query filters and validation, upload handling, alert triggering, and WebSocket delivery. Frontend Vitest tests cover active filter serialization and time-range boundaries.

## API

All HTTP endpoints are under `/api`.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Service health |
| `GET` | `/api/logs` | Paginated logs; optional `search`, `severity`, `service`, `start`, `end`, `limit`, `offset` |
| `GET` | `/api/metrics` | Total events, error rate (0–1 fraction), rolling 60-second events/second, severity counts |
| `GET` | `/api/timeline?minutes=60` | Per-minute event/error buckets with spike flags |
| `GET` | `/api/services` | Distinct service names |
| `POST` | `/api/logs/generate?count=20` | Generate 1–500 sample events |
| `POST` | `/api/logs/upload` | Multipart upload of `.log` or `.txt` (5 MiB default max) |
| `GET` | `/api/alerts/rules` | List alert rules |
| `POST` | `/api/alerts/rules` | Create a rule: `{"name":"Error burst","threshold":5,"window_minutes":5}` |
| `GET` | `/api/alerts` | Recent triggered alerts |
| `GET` | `/api/anomalies?minutes=60` | Statistically unusual minutes (error and total volume) with score and expected value |
| `GET` | `/api/clusters?minutes=60&limit=10` | Message templates ranked by severity and frequency |
| `GET` | `/api/auth/status` | Whether login is on and whether first-run setup is needed |
| `POST` | `/api/auth/register` | Create the first admin (or users when registration is open) |
| `POST` | `/api/auth/login` | Sign in and set an HttpOnly session cookie |
| `POST` | `/api/ingest` | Batch of structured events (`X-API-Key` required; disabled until `INGEST_API_KEY` is set) |
| `POST` | `/api/ingest/parse-preview` | Parse one line without storing it: `{"line":"..."}` |

Time values are ISO-8601. Uploads are decoded as UTF-8 with replacement for invalid byte sequences. Blank lines are ignored; individual lines over 100,000 characters are skipped and counted as rejected. Uploaded content is treated strictly as text and is never executed.

## WebSocket

Connect to `ws://localhost:8000/ws/logs` locally (or `wss://` behind TLS). The server pushes JSON events:

```json
{"type":"log","data":{"id":21,"timestamp":"2026-10-07T13:42:14+00:00","severity":"ERROR","service":"payments","source":"src/checkout.py","message":"provider timeout"}}
{"type":"alert","data":{"id":2,"rule_id":1,"rule_name":"Error burst","message":"6 errors detected in the last 5 minute(s) (threshold: 5).","count":6,"triggered_at":"2026-10-07T13:43:00+00:00"}}
```

The browser reconnects after a dropped connection. Alert rules trigger when the number of `ERROR` and `CRITICAL` events is **greater than** the configured threshold within the rolling window. A rule is deduplicated for the duration of its window after a trigger.

The stream also pushes `{"type":"anomaly","data":{...}}` when a new anomaly is detected.

## Example data

`sample-data/application.log` contains ISO application events, multiple severities/services, an unrecognized raw line, and representative failure conditions. On an empty database, the backend seeds these events at startup with fresh timestamps so the initial timeline is populated. Use **Generate events** to add additional live entries or upload another text log.

## Screenshot checklist

For a portfolio README screenshot, capture:

- The full dashboard at desktop width with metric cards, event timeline, severity breakdown, live log stream, and alert activity visible.
- The alert-rule dialog with a configured threshold and time window.
- A filtered log table showing an error event and selected service.

## Resume bullet

Built Real-Time Log Analyzer, a real-time log monitoring platform (FastAPI, WebSocket, React) with multi-format parsing, an API-key HTTP ingestion endpoint, robust statistical anomaly detection (precision 0.87 vs 0.36 for a static threshold on synthetic benchmarks), log-template clustering, and webhook alerting.
