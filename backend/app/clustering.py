"""Log template mining (a compact, Drain-style parser).

Thousands of log lines usually come from a few dozen code statements that only
differ in variable parts (ids, durations, IPs). This module masks those parts,
then groups messages whose remaining tokens are similar, so the UI can show
"payment provider timeout after <*>" x 412 instead of 412 separate rows.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Iterable

WILDCARD = "<*>"
_MASKS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), WILDCARD),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), WILDCARD),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), WILDCARD),
    (re.compile(r"\b\d+(?:\.\d+)?(?:ms|s|m|h|kb|mb|gb|%)?\b", re.IGNORECASE), WILDCARD),
    (re.compile(r"=\S+"), "=" + WILDCARD),
]
_SEVERITY_RANK = {"UNKNOWN": 0, "DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}


def mask(message: str) -> list[str]:
    text = message.strip()
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text.split()


def _similarity(template: list[str], tokens: list[str]) -> float:
    same = sum(1 for a, b in zip(template, tokens) if a == b or a == WILDCARD)
    return same / len(tokens)


class TemplateMiner:
    def __init__(self, similarity: float = 0.6):
        self.similarity = similarity
        # Tokens-count + first token narrows the search, as in Drain's prefix tree.
        self._buckets: dict[tuple[int, str], list[dict[str, Any]]] = {}

    def add(self, event: dict[str, Any]) -> dict[str, Any]:
        tokens = mask(event["message"]) or [WILDCARD]
        key = (len(tokens), tokens[0])
        best, best_score = None, 0.0
        for cluster in self._buckets.setdefault(key, []):
            score = _similarity(cluster["tokens"], tokens)
            if score > best_score:
                best, best_score = cluster, score
        if best is None or best_score < self.similarity:
            best = {
                "tokens": tokens, "count": 0, "severity": "UNKNOWN", "services": set(),
                "first_seen": event["timestamp"], "last_seen": event["timestamp"],
                "example": event["message"], "example_id": event.get("id"),
            }
            self._buckets[key].append(best)
        else:  # merge: differing positions become wildcards
            best["tokens"] = [a if a == b else WILDCARD for a, b in zip(best["tokens"], tokens)]
        best["count"] += 1
        best["services"].add(event["service"])
        if _SEVERITY_RANK.get(event["severity"], 0) > _SEVERITY_RANK[best["severity"]]:
            best["severity"] = event["severity"]
        best["first_seen"] = min(best["first_seen"], event["timestamp"])
        best["last_seen"] = max(best["last_seen"], event["timestamp"])
        return best

    def clusters(self) -> list[dict[str, Any]]:
        results = []
        for group in self._buckets.values():
            for c in group:
                template = " ".join(c["tokens"])
                results.append(
                    {
                        "id": hashlib.sha1(template.encode()).hexdigest()[:10],
                        "template": template,
                        "count": c["count"],
                        "severity": c["severity"],
                        "services": sorted(c["services"]),
                        "first_seen": c["first_seen"],
                        "last_seen": c["last_seen"],
                        "example": c["example"],
                    }
                )
        return results


def cluster_events(events: Iterable[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    """Cluster events and rank them: severe + frequent patterns first."""
    miner = TemplateMiner()
    for event in sorted(events, key=lambda e: e["timestamp"]):
        miner.add(event)
    ranked = sorted(
        miner.clusters(),
        key=lambda c: (_SEVERITY_RANK.get(c["severity"], 0) >= 4, c["count"]),
        reverse=True,
    )
    return ranked[: max(1, limit)]
