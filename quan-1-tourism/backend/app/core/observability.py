"""Small dependency-free HTTP metrics and request logging helpers."""
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
from threading import Lock
from time import perf_counter
from uuid import uuid4

from fastapi import Request

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
_logger = logging.getLogger("quan1.http")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.propagate = False
_lock = Lock()
_counts: dict[tuple[str, str, int], int] = defaultdict(int)
_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
_duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)
_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


async def observe_request(request: Request, call_next):
    supplied = request.headers.get("x-request-id", "")
    request_id = supplied if _REQUEST_ID.fullmatch(supplied) else uuid4().hex
    token = request_id_context.set(request_id)
    started = perf_counter()
    status_code = 500
    route = "unmatched"
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        elapsed = max(0.0, perf_counter() - started)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        method = request.method.upper()
        with _lock:
            _counts[(method, route, status_code)] += 1
            _duration_sum[(method, route)] += elapsed
            for bucket in _BUCKETS:
                if elapsed <= bucket:
                    _duration_buckets[(method, route, bucket)] += 1
        _logger.info(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "event": "http_request_completed",
            "request_id": request_id,
            "method": method,
            "route": route,
            "status_code": status_code,
            "duration_ms": round(elapsed * 1000, 2),
        }, ensure_ascii=False))
        request_id_context.reset(token)


def render_http_metrics() -> str:
    lines = [
        "# HELP quan1_http_requests_total Completed HTTP requests.",
        "# TYPE quan1_http_requests_total counter",
    ]
    with _lock:
        counts = list(_counts.items())
        sums = list(_duration_sum.items())
        buckets = list(_duration_buckets.items())
    for (method, route, status), count in counts:
        lines.append(f'quan1_http_requests_total{{method="{_label(method)}",route="{_label(route)}",status="{status}"}} {count}')
    lines.extend((
        "# HELP quan1_http_request_duration_seconds HTTP request duration.",
        "# TYPE quan1_http_request_duration_seconds histogram",
    ))
    bucket_values = {(method, route, bucket): count for (method, route, bucket), count in buckets}
    routes = {(method, route) for method, route, _ in bucket_values} | {(method, route) for (method, route), _ in sums}
    for method, route in sorted(routes):
        # Include every boundary, plus +Inf, so Prometheus can calculate percentiles.
        for bucket in _BUCKETS:
            count = bucket_values.get((method, route, bucket), 0)
            lines.append(f'quan1_http_request_duration_seconds_bucket{{method="{_label(method)}",route="{_label(route)}",le="{bucket}"}} {count}')
        total = sum(count for (m, r, _status), count in counts if (m, r) == (method, route))
        duration_total = next((value for (m, r), value in sums if (m, r) == (method, route)), 0.0)
        lines.append(f'quan1_http_request_duration_seconds_bucket{{method="{_label(method)}",route="{_label(route)}",le="+Inf"}} {total}')
        lines.append(f'quan1_http_request_duration_seconds_sum{{method="{_label(method)}",route="{_label(route)}"}} {duration_total:.9f}')
        lines.append(f'quan1_http_request_duration_seconds_count{{method="{_label(method)}",route="{_label(route)}"}} {total}')
    return "\n".join(lines) + "\n"
