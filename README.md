# SignalDesk — Real-Time Log Analyzer

SignalDesk is a local-first observability dashboard for ingesting, searching, and monitoring application logs. It ships with realistic sample events so the dashboard is useful on first launch.

## Highlights

- Live log ingestion over a WebSocket stream, with reconnect behavior in the browser.
- ISO application, Apache access, and common syslog parsing; unknown or malformed lines stay visible as searchable `UNKNOWN` events.
- Search, severity, service, and time-range filters, plus severity metrics and an error-volume timeline.
- Configurable error-burst rules with persisted trigger history.
- Bounded `.log` / `.txt` uploads, line-size checks, input validation, and parameterized SQLite queries.
- A repository boundary that isolates storage operations from HTTP routes and alert evaluation.
- Responsive dark dashboard with keyboard-visible focus indicators and reduced-motion support.

## Architecture

```text
.
├── backend/
│   ├── app/
│   │   ├── api.py            # HTTP routes, validation, upload limits
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

From the repository root, in PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open [http://localhost:5173](http://localhost:5173). The API is at [http://localhost:8000](http://localhost:8000), and interactive API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs). Stop the services with `Ctrl+C`; remove containers with `docker compose down`. Persisted log data remains in the named volume. To intentionally clear it, run `docker compose down --volumes`.

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
| `POST` | `/api/ingest/parse-preview` | Parse one line without storing it: `{"line":"..."}` |

Time values are ISO-8601. Uploads are decoded as UTF-8 with replacement for invalid byte sequences. Blank lines are ignored; individual lines over 100,000 characters are skipped and counted as rejected. Uploaded content is treated strictly as text and is never executed.

## WebSocket

Connect to `ws://localhost:8000/ws/logs` (or `wss://` behind TLS). The server pushes JSON events:

```json
{"type":"log","data":{"id":21,"timestamp":"2026-10-07T13:42:14+00:00","severity":"ERROR","service":"payments","source":"src/checkout.py","message":"provider timeout"}}
{"type":"alert","data":{"id":2,"rule_id":1,"rule_name":"Error burst","message":"6 errors detected in the last 5 minute(s) (threshold: 5).","count":6,"triggered_at":"2026-10-07T13:43:00+00:00"}}
```

The browser reconnects after a dropped connection. Alert rules trigger when the number of `ERROR` and `CRITICAL` events is **greater than** the configured threshold within the rolling window. A rule is deduplicated for the duration of its window after a trigger.

## Example data

`sample-data/application.log` contains ISO application events, multiple severities/services, an unrecognized raw line, and representative failure conditions. On an empty database, the backend seeds these events at startup with fresh timestamps so the initial timeline is populated. Use **Generate events** to add additional live entries or upload another text log.

## Screenshot checklist

For a portfolio README screenshot, capture:

- The full dashboard at desktop width with metric cards, event timeline, severity breakdown, live log stream, and alert activity visible.
- The alert-rule dialog with a configured threshold and time window.
- A filtered log table showing an error event and selected service.

## Resume bullet

Built SignalDesk, a real-time log monitoring dashboard with a FastAPI/WebSocket ingestion pipeline, multi-format parsing, searchable React UI, SQLite persistence, and configurable error-burst alerts.
