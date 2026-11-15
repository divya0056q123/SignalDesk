"""Tiny log shipper: tail a file and forward new lines to SignalDesk's HTTP ingestion API.

    python scripts/send_logs.py /var/log/myapp.log --service myapp --key YOUR_KEY
Uses only the standard library, so it can run on any server without installing anything.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request

LEVEL = re.compile(r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b", re.IGNORECASE)
MAP = {"WARN": "WARNING", "FATAL": "CRITICAL"}


def classify(line: str) -> str:
    match = LEVEL.search(line)
    if not match:
        return "INFO"
    level = match.group(1).upper()
    return MAP.get(level, level)


def post(url: str, key: str, events: list[dict]) -> None:
    request = urllib.request.Request(
        url, data=json.dumps({"events": events}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": key}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--service", default="shipper")
    parser.add_argument("--key", required=True)
    parser.add_argument("--url", default="http://localhost:8000/api/ingest")
    parser.add_argument("--batch", type=int, default=50)
    parser.add_argument("--from-start", action="store_true", help="send existing content first")
    args = parser.parse_args()
    with open(args.path, encoding="utf-8", errors="replace") as handle:
        if not args.from_start:
            handle.seek(0, 2)
        buffer: list[dict] = []
        while True:
            line = handle.readline()
            if line.strip():
                buffer.append({"message": line.strip()[:100_000], "severity": classify(line),
                               "service": args.service, "source": args.path})
            if len(buffer) >= args.batch or (buffer and not line):
                post(args.url, args.key, buffer)
                buffer = []
            if not line:
                time.sleep(0.5)


if __name__ == "__main__":
    main()
