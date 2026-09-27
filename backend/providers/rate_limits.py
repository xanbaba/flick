"""Read retry guidance without retaining response bodies or credentials."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx


class RateLimitError(RuntimeError):
    def __init__(self, retry_after_s: float | None, quota_ids: list[str]) -> None:
        super().__init__("provider rate limited the request (HTTP 429)")
        self.retry_after_s = retry_after_s
        self.quota_ids = quota_ids


def _seconds(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        seconds = float(value.removesuffix("s"))
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def rate_limit_error(response: httpx.Response) -> RateLimitError:
    delays: list[float] = []
    retry_header = response.headers.get("retry-after")
    seconds = _seconds(retry_header)
    if seconds is not None:
        delays.append(seconds)
    elif retry_header:
        try:
            retry_at = parsedate_to_datetime(retry_header)
            if retry_at.tzinfo is not None:
                delays.append(max(0.0, (retry_at - datetime.now(UTC)).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            # A malformed optional hint must not conceal the HTTP 429.
            retry_at = None

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    details = error.get("details", []) if isinstance(error, dict) else []
    quota_ids: list[str] = []
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
            delay = _seconds(detail.get("retryDelay"))
            if delay is not None:
                delays.append(delay)
        if detail.get("@type") == "type.googleapis.com/google.rpc.QuotaFailure":
            violations = detail.get("violations", [])
            for violation in violations if isinstance(violations, list) else []:
                if isinstance(violation, dict) and isinstance(violation.get("quotaId"), str):
                    quota_ids.append(violation["quotaId"])
    return RateLimitError(max(delays) if delays else None, quota_ids)
