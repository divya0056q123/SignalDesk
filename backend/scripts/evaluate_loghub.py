"""Evaluate anomaly detection on the labeled BGL supercomputer log (Loghub).

BGL lines start with a label: "-" means normal, anything else is an alert
(a human-labelled fault). We turn the log into a per-minute series and ask:
can the detector find the minutes that contain alerts, using only log volume?

Download the small labeled sample and run:
    Invoke-WebRequest https://raw.githubusercontent.com/logpai/loghub/374038faa4ca122dd7ca0730372c0b78f76f8597/BGL/BGL_2k.log -OutFile BGL_2k.log
    python backend/scripts/evaluate_loghub.py BGL_2k.log --metric errors

Ground truth : a minute is anomalous if it contains >= 1 alert-labelled line.
Signal       : number of ERROR/FATAL/SEVERE/FAILURE lines per minute (or all lines with --metric total).
Methods      : (a) a mean-based threshold over the preceding 60 minutes,
               (b) the robust median/MAD detector.
The 2k sample is sparse and is not a substitute for evaluation on the complete BGL corpus.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.anomaly import DetectorConfig, detect_anomalies  # noqa: E402

ERROR_LEVELS = {"ERROR", "FATAL", "SEVERE", "FAILURE"}


def read_bgl(path: Path, max_lines: int | None, bucket_minutes: int):
    """Return (errors_by_minute, total_by_minute, alert_minutes) as dicts keyed by minute-start datetimes."""
    errors: dict[datetime, int] = defaultdict(int)
    total: dict[datetime, int] = defaultdict(int)
    alerts: set[datetime] = set()
    skipped = 0
    bucket_seconds = bucket_minutes * 60
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle):
            if max_lines is not None and number >= max_lines:
                break
            parts = line.split(None, 9)
            if len(parts) < 9 or not parts[1].isdigit():
                skipped += 1
                continue
            bucket = datetime.fromtimestamp(int(parts[1]) // bucket_seconds * bucket_seconds, tz=timezone.utc)
            total[bucket] += 1
            if parts[8].upper() in ERROR_LEVELS:
                errors[bucket] += 1
            if parts[0] != "-":
                alerts.add(bucket)
    return errors, total, alerts, skipped


def rolling_static(values: list[int], window: int) -> set[int]:
    """Apply a mean-based threshold using only the preceding time buckets."""
    flagged, running = set(), 0
    for i, value in enumerate(values):
        history_size = min(i, window)
        mean = running / history_size if history_size else 0.0
        if value > 0 and value >= max(3.0, 2.5 * mean):
            flagged.add(i)
        running += value
        if i >= window:
            running -= values[i - window]
    return flagged


def prf(pred: set[int], truth: set[int]):
    tp, fp, fn = len(pred & truth), len(pred - truth), len(truth - pred)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return tp, fp, fn, p, r, f


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path)
    ap.add_argument("--max-lines", type=int, default=None)
    ap.add_argument("--metric", choices=["errors", "total"], default="errors")
    ap.add_argument("--bucket-minutes", type=int, default=1)
    args = ap.parse_args()
    if args.max_lines is not None and args.max_lines < 1:
        ap.error("--max-lines must be positive")
    if args.bucket_minutes < 1:
        ap.error("--bucket-minutes must be positive")

    errors, total, alerts, skipped = read_bgl(args.path, args.max_lines, args.bucket_minutes)
    if not total:
        sys.exit("No BGL lines parsed - is this a raw BGL log from Loghub?")
    start, end = min(total), max(total)
    bucket_delta = timedelta(minutes=args.bucket_minutes)
    buckets = int((end - start) // bucket_delta) + 1
    series = errors if args.metric == "errors" else total
    points = [{"bucket": start + bucket_delta * i, args.metric: series.get(start + bucket_delta * i, 0)}
              for i in range(buckets)]
    index = {p["bucket"]: i for i, p in enumerate(points)}
    truth = {index[m] for m in alerts}
    print(f"{sum(total.values()):,} lines, {buckets:,} {args.bucket_minutes}-minute buckets "
          f"from {start.isoformat()} to {end.isoformat()}, {len(truth):,} labeled-alert buckets "
          f"({len(truth) / buckets:.3%}), {skipped} unparsable lines skipped")
    print(f"Signal: {args.metric}; ground truth: any non-'-' BGL alert label in the bucket\n")

    values = [p[args.metric] for p in points]
    results = {"static rule (rolling 60 min)": rolling_static(
        values, max(1, round(60 / args.bucket_minutes))
    )}
    detector_window = max(5, round(30 / args.bucket_minutes))
    for z in (3.5, 5.0, 8.0):
        found = detect_anomalies(
            points,
            args.metric,
            DetectorConfig(window=detector_window, z_threshold=z),
        )
        results[f"robust z >= {z}"] = {index[a["bucket"]] for a in found}

    print(f"{'method':<30}{'flagged':>9}{'TP':>7}{'FP':>8}{'FN':>8}{'prec':>8}{'recall':>8}{'F1':>7}")
    for name, pred in results.items():
        tp, fp, fn, p, r, f = prf(pred, truth)
        print(f"{name:<30}{len(pred):>9}{tp:>7}{fp:>8}{fn:>8}{p:>8.3f}{r:>8.3f}{f:>7.3f}")


if __name__ == "__main__":
    main()
