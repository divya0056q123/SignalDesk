"""Compare SignalDesk's robust detector with the original static threshold.

Generates synthetic per-minute error counts (Poisson noise + slow daily drift)
with *known* injected incidents, then measures precision / recall / F1 for both
methods. Run:  python scripts/evaluate_detection.py
"""
from __future__ import annotations

import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.anomaly import detect_anomalies, static_threshold_baseline  # noqa: E402


def poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def make_series(seed: int, minutes: int = 240, incidents: int = 5):
    rng = random.Random(seed)
    start = datetime(2026, 1, 1)
    truth: set[int] = set()
    while len(truth) < incidents:
        centre = rng.randrange(20, minutes - 5)
        if all(abs(centre - t) > 15 for t in truth):
            truth.add(centre)
    points = []
    for i in range(minutes):
        base = 2 + 1.5 * math.sin(i / 40)  # slow drift in "normal" load
        value = poisson(rng, max(0.2, base))
        if i in truth:
            value += rng.randint(9, 20)  # injected incident
        points.append({"bucket": start + timedelta(minutes=i), "errors": value})
    return points, truth


def score(predicted: set[int], truth: set[int]):
    tp = len(predicted & truth)
    fp = len(predicted - truth)
    fn = len(truth - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def main(runs: int = 50) -> None:
    totals = {"static": [0.0, 0.0, 0.0], "robust": [0.0, 0.0, 0.0]}
    for seed in range(runs):
        points, truth = make_series(seed)
        index = {p["bucket"]: i for i, p in enumerate(points)}
        robust = {index[a["bucket"]] for a in detect_anomalies(points, "errors")}
        static = set(static_threshold_baseline(points, "errors"))
        for name, pred in (("static", static), ("robust", robust)):
            for j, value in enumerate(score(pred, truth)):
                totals[name][j] += value / runs
    print(f"{runs} synthetic runs, 240 min each, 5 injected incidents per run\n")
    print(f"{'method':<22}{'precision':>10}{'recall':>9}{'F1':>8}")
    labels = {"static": "static threshold", "robust": "robust z (median/MAD)"}
    for name in ("static", "robust"):
        p, r, f = totals[name]
        print(f"{labels[name]:<22}{p:>10.3f}{r:>9.3f}{f:>8.3f}")


if __name__ == "__main__":
    main()
