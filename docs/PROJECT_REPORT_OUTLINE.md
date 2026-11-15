# Real-Time Log Analyzer — Major Project Report Outline

**Title:** Real-Time Log Analyzer: Log Monitoring with Statistical Anomaly Detection and Log Pattern Mining

## 1. Abstract (150 words)
Modern applications emit thousands of log lines per minute. Fixed alert thresholds either miss incidents or flood engineers with false alarms, and raw logs hide the few underlying problems. Real-Time Log Analyzer ingests logs in real time (WebSocket, file upload, authenticated HTTP API), parses multiple formats, detects anomalies with a median/MAD robust z-score, and groups messages into templates. On synthetic benchmarks with injected incidents it raised precision from 0.36 (static threshold) to 0.87 while keeping recall at 0.99.

## 2. Problem statement
- Static thresholds ignore normal load changes, so they produce false positives.
- Operators read thousands of near-identical lines instead of a few distinct problems.
- Small teams cannot afford heavy platforms (ELK, Splunk, Datadog).

## 3. Objectives
1. Real-time ingestion from files, uploads and other applications.
2. Detect abnormal error/volume behaviour automatically.
3. Summarise logs into a small set of patterns.
4. Notify the team (dashboard + webhook).
5. Evaluate detection quality against a baseline.
6. Secure the system (login, API keys) and support a production database (PostgreSQL).

## 4. Literature survey (draft in `LITERATURE_SURVEY_DRAFT.md`; verify citations and rewrite in your words)
- Iglewicz & Hoaglin (1993), *How to Detect and Handle Outliers* — modified z-score with MAD (used here, cut-off 3.5).
- He et al. (2017), *Drain: An Online Log Parsing Approach with Fixed Depth Tree* — basis of the template miner.
- Du et al. (2017), *DeepLog* — LSTM log anomaly detection (future work).
- He et al. (2016/2020), *Loghub / Tools and Benchmarks for Automated Log Parsing* — datasets for real evaluation.
- Existing tools to compare: ELK stack, Grafana Loki, Graylog.

## 5. System design
Architecture diagram (README), data-flow diagram (ingest → parse → store → detect → broadcast/notify), ER diagram (log_events, alert_rules, triggered_alerts), API table.

## 6. Methodology
- Parsing: regex for ISO, Apache, syslog; unknown lines preserved.
- Anomaly detection: per-minute buckets; baseline = median of previous 30 minutes; score = 0.6745 × (x − median) / max(MAD, 1); flag if score ≥ 3.5 and count ≥ 3; flagged minutes are excluded from the baseline.
- Template mining: mask numbers/IPs/UUIDs/durations, bucket by (token count, first token), merge when ≥ 60% of tokens match, differing tokens become `<*>`.

## 7. Implementation
Stack, module list, screenshots (dashboard, anomaly panel, error patterns, alert rule dialog), Docker deployment.

## 8. Testing and evaluation
- Unit/API tests (parser, anomaly, clustering, ingestion auth, filters).
- Detection benchmark: `backend/scripts/evaluate_detection.py` (table in README).
- Real data: `docs/REAL_WORLD_EVALUATION.md` records the reproducible Loghub BGL 2k evaluation and its negative one-minute-resolution result. This is a sparse sample, not the full corpus; do not claim it proves generalization. Full-corpus evaluation and event-pattern analysis remain future experiments.
- Throughput: run `backend/scripts/benchmark_ingestion.py --events 10000`; report the machine, Python/SQLite versions, event count, measured events/s, and benchmark scope. It measures parsing plus transaction-batched SQLite persistence only, not network or WebSocket overhead.
- Concurrency/security checks: verify first-account registration closes atomically, oversized structured requests receive HTTP 413, and malformed timestamps remain visible without being presented as current-time events.

## 9. Limitations
Synthetic evaluation is not representative of real alert labels; the small BGL sample is sparse and anomaly-volume detection has low recall at the production one-minute resolution; single-node SQLite; minute-level granularity; clustering is rule-based, not learned.

## 10. Future work
PostgreSQL/ClickHouse backend, message queue, user accounts and multi-tenant projects, deep-learning sequence models, Kubernetes deployment.
