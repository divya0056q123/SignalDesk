"""Robust anomaly detection for per-minute log volume.

Method: for every minute, compare the observed count with the *median* of the
preceding window and scale the difference by the *median absolute deviation*
(MAD). Median/MAD are used instead of mean/standard deviation because a single
earlier spike would otherwise inflate the baseline and hide the next one.

    robust_z = 0.6745 * (x - median) / max(MAD, floor)

A minute is anomalous when robust_z >= z_threshold and x >= min_count.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Sequence

NORMAL_CONSISTENCY = 0.6745  # makes MAD comparable to a standard deviation


@dataclass(frozen=True)
class DetectorConfig:
    window: int = 30          # how many previous minutes form the baseline
    min_history: int = 5      # need at least this many points before judging
    z_threshold: float = 3.5  # Iglewicz & Hoaglin's recommended cut-off
    high_threshold: float = 6.0
    min_count: int = 3        # ignore tiny absolute values (0 -> 2 is not an incident)
    mad_floor: float = 1.0    # stops division by zero on flat/zero baselines


def robust_score(value: float, history: Sequence[float], config: DetectorConfig) -> tuple[float, float]:
    """Return (robust z-score, expected value) of ``value`` against ``history``."""
    centre = median(history)
    mad = median(abs(h - centre) for h in history)
    score = NORMAL_CONSISTENCY * (value - centre) / max(mad, config.mad_floor)
    return score, float(centre)


def detect_anomalies(
    points: Sequence[dict[str, Any]],
    metric: str = "errors",
    config: DetectorConfig | None = None,
) -> list[dict[str, Any]]:
    """Scan timeline points (``bucket`` + numeric ``metric``) and return anomalies.

    Baseline excludes previously flagged minutes so one incident does not
    teach the detector that incidents are normal.
    """
    config = config or DetectorConfig()
    values = [float(p[metric]) for p in points]
    cleaned: list[float] = []      # history with flagged points replaced by their expectation
    found: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        history = cleaned[-config.window:]
        if len(history) < config.min_history:
            cleaned.append(value)
            continue
        score, expected = robust_score(value, history, config)
        if score >= config.z_threshold and value >= config.min_count:
            found.append(
                {
                    "bucket": points[index]["bucket"],
                    "metric": metric,
                    "observed": int(value),
                    "expected": round(expected, 2),
                    "score": round(score, 2),
                    "level": "high" if score >= config.high_threshold else "medium",
                }
            )
            cleaned.append(expected)
        else:
            cleaned.append(value)
    return found


def static_threshold_baseline(points: Sequence[dict[str, Any]], metric: str = "errors") -> list[int]:
    """The original SignalDesk rule (mean * 2.5, min 3). Kept for evaluation only."""
    values = [float(p[metric]) for p in points]
    average = sum(values) / max(1, len(values))
    threshold = max(3.0, average * 2.5)
    return [i for i, v in enumerate(values) if v >= threshold and v > 0]
