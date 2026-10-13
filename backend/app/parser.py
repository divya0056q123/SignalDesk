import re
from datetime import datetime, timezone

from .models import Severity

_ISO_LINE = re.compile(
    r"^(?P<timestamp>\S+)\s+(?P<severity>DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)"
    r"\s+(?:\[(?P<service>[^\]]+)\])?\s*(?:\[(?P<source>[^\]]+)\])?\s*:?\s*(?P<message>.*)$",
    re.IGNORECASE,
)
_LEVEL_LINE = re.compile(
    r"^(?P<severity>DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)"
    r"\s+(?:\[(?P<service>[^\]]+)\])?\s*(?:\[(?P<source>[^\]]+)\])?\s*:?\s*(?P<message>.*)$",
    re.IGNORECASE,
)
_APACHE_LINE = re.compile(
    r"^\S+\s+\S+\s+\S+\s+\[(?P<timestamp>[^\]]+)\]\s+\"(?P<request>[^\"]*)\"\s+"
    r"(?P<status>\d{3})\s+(?P<size>\S+)(?:\s+\"(?P<referer>[^\"]*)\")?"
)
_SYSLOG_LINE = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<time>\d\d:\d\d:\d\d)\s+"
    r"(?P<host>\S+)\s+(?P<service>[\w./-]+)(?:\[\d+\])?:\s*(?P<message>.*)$"
)
_LEVELS: dict[str, Severity] = {
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "FATAL": "CRITICAL",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


def _timestamp(value: str) -> datetime:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        for fmt in ("%d/%b/%Y:%H:%M:%S %z",):
            try:
                return datetime.strptime(value, fmt).astimezone(timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc)


def parse_line(line: str) -> dict[str, str | datetime]:
    """Parse common application/web log shapes; preserve every unmatched line."""
    text = line.rstrip("\r\n")
    match = _ISO_LINE.match(text)
    if match:
        values = match.groupdict()
        return {
            "timestamp": _timestamp(values["timestamp"]),
            "severity": _LEVELS[values["severity"].upper()],
            "service": (values["service"] or "application").strip(),
            "source": (values["source"] or "unknown").strip(),
            "message": values["message"],
        }

    match = _LEVEL_LINE.match(text)
    if match:
        values = match.groupdict()
        return {
            "timestamp": datetime.now(timezone.utc),
            "severity": _LEVELS[values["severity"].upper()],
            "service": (values["service"] or "application").strip(),
            "source": (values["source"] or "unknown").strip(),
            "message": values["message"],
        }

    match = _APACHE_LINE.match(text)
    if match:
        values = match.groupdict()
        status = int(values["status"])
        return {
            "timestamp": _timestamp(values["timestamp"]),
            "severity": "ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO",
            "service": "web",
            "source": "access",
            "message": f'{values["request"]} -> {status}',
        }

    match = _SYSLOG_LINE.match(text)
    if match:
        values = match.groupdict()
        current_year = datetime.now(timezone.utc).year
        try:
            parsed = datetime.strptime(
                f'{current_year} {values["month"]} {values["day"]} {values["time"]}',
                "%Y %b %d %H:%M:%S",
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            return {
                "timestamp": datetime.now(timezone.utc),
                "severity": "UNKNOWN",
                "service": "unparsed",
                "source": "raw",
                "message": text,
            }
        message = values["message"]
        severity = "ERROR" if re.search(r"\b(error|failed|failure)\b", message, re.I) else "INFO"
        return {
            "timestamp": parsed,
            "severity": severity,
            "service": values["service"],
            "source": values["host"],
            "message": message,
        }

    return {
        "timestamp": datetime.now(timezone.utc),
        "severity": "UNKNOWN",
        "service": "unparsed",
        "source": "raw",
        "message": text,
    }
