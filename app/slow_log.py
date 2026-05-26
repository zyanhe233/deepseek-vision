"""Slow-request diagnostic dumper.

When an upstream invocation exceeds `settings.slow_request_threshold_ms`
(measured by end-to-end duration), dump a JSON file with full request/response
metadata — useful for debugging latency issues.

Files are written to `<slow_request_log_dir>/<YYYYMMDD>/<request_id>.json`.
On startup a best-effort cleanup prunes day-dirs older than
`settings.slow_request_retention_days`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _day_dir(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return os.path.join(settings.slow_request_log_dir, now.strftime("%Y%m%d"))


def should_dump(duration_ms: Optional[int]) -> bool:
    if duration_ms is None:
        return False
    return duration_ms >= settings.slow_request_threshold_ms


def dump(
    *,
    request_id: str,
    model_id: str,
    stream: bool,
    duration_ms: int,
    request_size_bytes: Optional[int],
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    response_body: Any,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Write a single JSON dump for one slow request. Returns the file path, or None on failure."""
    try:
        day = _day_dir()
        os.makedirs(day, exist_ok=True)
        path = os.path.join(day, f"{request_id}.json")
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "model_id": model_id,
            "stream": stream,
            "duration_ms": duration_ms,
            "request_size_bytes": request_size_bytes,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "response_body": response_body,
        }
        if extra:
            payload["extra"] = extra
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        logger.warning(f"[SLOW] dumped request_id={request_id} duration={duration_ms}ms → {path}")
        return path
    except Exception as e:
        logger.error(f"[SLOW] failed to dump slow request {request_id}: {e}")
        return None


def cleanup_old_dumps() -> int:
    """Remove day-dirs older than retention window. Returns count removed."""
    try:
        root = settings.slow_request_log_dir
        if not os.path.isdir(root):
            return 0
        retain = max(0, settings.slow_request_retention_days)
        cutoff = time.time() - retain * 86400
        removed = 0
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if not os.path.isdir(full):
                continue
            try:
                if os.stat(full).st_mtime < cutoff:
                    shutil.rmtree(full, ignore_errors=True)
                    removed += 1
            except Exception:
                continue
        if removed:
            logger.info(f"[SLOW] cleanup removed {removed} old day-dirs under {root}")
        return removed
    except Exception as e:
        logger.error(f"[SLOW] cleanup failed: {e}")
        return 0
