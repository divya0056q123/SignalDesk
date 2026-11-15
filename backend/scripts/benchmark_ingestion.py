"""Measure parsing and SQLite persistence throughput on generated application logs.

Run from the repository root: python backend/scripts/benchmark_ingestion.py --events 10000
"""
from __future__ import annotations

import argparse
import platform
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.parser import parse_line  # noqa: E402
from app.repository import SQLiteRepository  # noqa: E402


def benchmark(events: int) -> tuple[float, float]:
    start = datetime.now(timezone.utc).replace(microsecond=0)
    lines = [
        f"{(start + timedelta(milliseconds=index)).isoformat()} "
        f"ERROR [payments] [checkout.py] provider timeout after {index % 10 + 1}s order={index}"
        for index in range(events)
    ]
    with tempfile.TemporaryDirectory(prefix="signaldesk-benchmark-") as directory:
        repository = SQLiteRepository(Path(directory) / "benchmark.db")
        repository.initialize()
        started = time.perf_counter()
        repository.insert_logs([parse_line(line) for line in lines])
        elapsed = time.perf_counter() - started
        stored = repository.count_logs()
        if stored != events:
            raise RuntimeError(f"Expected to persist {events} events, found {stored}")
    return elapsed, events / elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=10_000, help="number of generated log events")
    args = parser.parse_args()
    if args.events < 1:
        parser.error("--events must be a positive integer")
    elapsed, throughput = benchmark(args.events)
    print(f"Events: {args.events}")
    print(f"Environment: {platform.platform()} | Python {platform.python_version()} | SQLite {sqlite3.sqlite_version}")
    print(f"Processor: {platform.processor() or 'not reported'}")
    print("Path: regex parsing + transaction-batched SQLite inserts (no HTTP/WebSocket overhead)")
    print(f"Elapsed: {elapsed:.3f} s")
    print(f"Throughput: {throughput:.0f} events/s")


if __name__ == "__main__":
    main()
