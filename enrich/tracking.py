"""Usage logging and enrichment snapshot helpers."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from config import API_USAGE_JSONL, ENRICHMENT_DIR


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", str(value or "").strip())
    return cleaned[:120] or "unknown"


def log_api_usage(
    *,
    provider: str,
    endpoint: str,
    status: str,
    lead_id: str = "",
    domain: str = "",
    duration_ms: int | None = None,
    fields_returned: list[str] | None = None,
    result_count: int | None = None,
    estimated_credits: float | None = None,
    estimated_tokens: int | None = None,
    error: str = "",
) -> None:
    """Append a non-secret usage record to data/api_usage.jsonl."""
    os.makedirs(os.path.dirname(API_USAGE_JSONL), exist_ok=True)
    record = {
        "timestamp": utc_now(),
        "provider": provider,
        "endpoint": endpoint,
        "status": status,
        "lead_id": lead_id or "",
        "domain": domain or "",
        "duration_ms": duration_ms,
        "fields_returned": fields_returned or [],
        "result_count": result_count,
        "estimated_credits": estimated_credits,
        "estimated_tokens": estimated_tokens,
        "error": str(error or "")[:500],
    }
    with open(API_USAGE_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_provider_snapshot(
    *,
    lead_id: str,
    provider: str,
    endpoint: str,
    request_ref: str = "",
    normalized: dict[str, Any] | None = None,
    raw: dict[str, Any] | list[Any] | None = None,
    errors: list[str] | None = None,
) -> str:
    """Persist provider response context outside prospects.json and return the file path."""
    lead_dir = os.path.join(ENRICHMENT_DIR, safe_name(lead_id))
    os.makedirs(lead_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = os.path.join(lead_dir, f"{stamp}_{safe_name(provider)}_{safe_name(endpoint)}.json")
    payload = {
        "timestamp": utc_now(),
        "lead_id": lead_id,
        "provider": provider,
        "endpoint": endpoint,
        "request_ref": request_ref,
        "normalized": normalized or {},
        "raw": raw,
        "errors": errors or [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def read_usage_summary() -> dict[str, Any]:
    """Summarize usage records by provider for today, month, and all time."""
    today = datetime.now(timezone.utc).date().isoformat()
    month = today[:7]
    summary: dict[str, Any] = {
        "today": {},
        "month": {},
        "all_time": {},
        "recent_errors": [],
        "records": 0,
    }
    buckets = {
        "today": defaultdict(_empty_usage_bucket),
        "month": defaultdict(_empty_usage_bucket),
        "all_time": defaultdict(_empty_usage_bucket),
    }

    if not os.path.exists(API_USAGE_JSONL):
        return summary

    with open(API_USAGE_JSONL, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            summary["records"] += 1
            provider = record.get("provider") or "unknown"
            stamp = record.get("timestamp") or ""
            for name, bucket_map in buckets.items():
                if name == "today" and not stamp.startswith(today):
                    continue
                if name == "month" and not stamp.startswith(month):
                    continue
                _add_usage_record(bucket_map[provider], record)
            if record.get("status") not in ("ok", "success", "skipped") and record.get("error"):
                summary["recent_errors"].append(record)

    for key, bucket_map in buckets.items():
        summary[key] = {provider: dict(bucket) for provider, bucket in bucket_map.items()}
    summary["recent_errors"] = summary["recent_errors"][-10:][::-1]
    return summary


def _empty_usage_bucket() -> dict[str, Any]:
    return {
        "calls": 0,
        "success": 0,
        "errors": 0,
        "estimated_credits": 0.0,
        "estimated_tokens": 0,
        "duration_ms": 0,
    }


def _add_usage_record(bucket: dict[str, Any], record: dict[str, Any]) -> None:
    bucket["calls"] += 1
    if record.get("status") in ("ok", "success", "skipped", "empty"):
        bucket["success"] += 1
    else:
        bucket["errors"] += 1
    bucket["estimated_credits"] += float(record.get("estimated_credits") or 0)
    bucket["estimated_tokens"] += int(record.get("estimated_tokens") or 0)
    bucket["duration_ms"] += int(record.get("duration_ms") or 0)
