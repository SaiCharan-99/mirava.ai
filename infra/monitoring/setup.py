"""Guide 13: email channel, /health uptime check, log-based engine metrics, alert policies and the dashboard.

  uv run python -m infra.monitoring.setup mirava-ai-hack you@example.com

Idempotent by display name / id (existing resources are kept). Uses `gcloud auth print-access-token`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any

import httpx

MON = "https://monitoring.googleapis.com/v3"
LOG = "https://logging.googleapis.com/v2"
ENGINE_HOST = "world-engine-kfh7v3hvjq-el.a.run.app"
ENGINE_LOG = 'resource.type="cloud_run_revision" AND resource.labels.service_name="world-engine" AND jsonPayload.metric="engine"'
METRICS = {  # log-based metric → jsonPayload field, unit, description
    "engine_tick_p95_ms": ("tick_p95_ms", "ms", "world-engine tick p95 over the last 600 ticks (hourly)"),
    "engine_spend_today_usd": ("spend_today_usd", "USD", "background model spend today (governor)"),
    "engine_rendered_ratio": ("rendered_ratio", "1", "share of background model work rendered (not template)"),
    "engine_live_viewers": ("live_viewers", "1", "open /live connections"),
}


def _h() -> dict[str, str]:
    tok = subprocess.run([shutil.which("gcloud") or "gcloud", "auth", "print-access-token"], capture_output=True,
                         text=True, check=True).stdout.strip()
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "x-goog-user-project": sys.argv[1]}


def _ok(r: httpx.Response) -> dict[str, Any]:
    if r.status_code >= 400:
        raise SystemExit(f"{r.request.method} {r.request.url} → {r.status_code}: {r.text[:500]}")
    return r.json() if r.content else {}


def channel(c: httpx.Client, p: str, email: str) -> str:
    """Email notification channel."""
    for ch in _ok(c.get(f"{MON}/projects/{p}/notificationChannels")).get("notificationChannels", []):
        if ch.get("labels", {}).get("email_address") == email:
            return ch["name"]
    return _ok(c.post(f"{MON}/projects/{p}/notificationChannels", json={
        "type": "email", "displayName": "mirava alerts (email)", "labels": {"email_address": email}}))["name"]


def uptime(c: httpx.Client, p: str) -> str:
    """HTTPS check of world-engine /health every minute (500 when no tick for 120 s)."""
    for u in _ok(c.get(f"{MON}/projects/{p}/uptimeCheckConfigs")).get("uptimeCheckConfigs", []):
        if u["displayName"] == "world-engine-health":
            return u["name"]
    return _ok(c.post(f"{MON}/projects/{p}/uptimeCheckConfigs", json={
        "displayName": "world-engine-health", "period": "60s", "timeout": "10s",
        "monitoredResource": {"type": "uptime_url", "labels": {"project_id": p, "host": ENGINE_HOST}},
        "httpCheck": {"path": "/health", "port": 443, "useSsl": True, "validateSsl": True}}))["name"]


def log_metrics(c: httpx.Client, p: str) -> None:
    """Distribution log-based metrics from the engine's hourly `metrics` line."""
    have = {m["name"] for m in _ok(c.get(f"{LOG}/projects/{p}/metrics")).get("metrics", [])}
    for name, (field, unit, desc) in METRICS.items():
        if name in have:
            continue
        _ok(c.post(f"{LOG}/projects/{p}/metrics", json={
            "name": name, "description": desc, "filter": ENGINE_LOG,
            "valueExtractor": f"EXTRACT(jsonPayload.{field})",
            "metricDescriptor": {"metricKind": "DELTA", "valueType": "DISTRIBUTION", "unit": unit},
            "bucketOptions": {"exponentialBuckets": {"numFiniteBuckets": 32, "growthFactor": 1.6, "scale": 0.01}}}))


def _policy(name: str, doc: str, cond: dict[str, Any], ch: str) -> dict[str, Any]:
    return {"displayName": name, "combiner": "OR", "conditions": [cond], "notificationChannels": [ch],
            "documentation": {"content": doc, "mimeType": "text/markdown"}, "enabled": True}


def policies(c: httpx.Client, p: str, ch: str, check_id: str) -> None:
    """World stalled (uptime fails 5 min), api 5xx burst, spend over the daily cap."""
    have = {x["displayName"] for x in _ok(c.get(f"{MON}/projects/{p}/alertPolicies")).get("alertPolicies", [])}
    want = [
        _policy("world-engine stalled (tick lag > 2 min)",
                "`/health` returns 500 when no tick happened for 120 s. Check `GET /state`, Cloud Run logs; restart or `make restore-demo`.",
                {"displayName": "uptime /health failing",
                 "conditionThreshold": {
                     "filter": f'metric.type="monitoring.googleapis.com/uptime_check/check_passed" AND resource.type="uptime_url" AND metric.label.check_id="{check_id}"',
                     "aggregations": [{"alignmentPeriod": "60s", "perSeriesAligner": "ALIGN_NEXT_OLDER",
                                       "crossSeriesReducer": "REDUCE_COUNT_FALSE", "groupByFields": ["resource.label.*"]}],
                     "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "300s"}}, ch),
        _policy("mirava-api 5xx burst",
                "More than 10 server errors in 5 minutes on mirava-api.",
                {"displayName": "api 5xx",
                 "conditionThreshold": {
                     "filter": 'metric.type="run.googleapis.com/request_count" AND resource.type="cloud_run_revision" AND resource.label.service_name="mirava-api" AND metric.label.response_code_class="5xx"',
                     "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_SUM",
                                       "crossSeriesReducer": "REDUCE_SUM"}],
                     "comparison": "COMPARISON_GT", "thresholdValue": 10, "duration": "0s"}}, ch),
        _policy("model spend over daily cap",
                "Background spend today passed $15 (governor cap). Check `GET /state` budget and OpenRouter key usage.",
                {"displayName": "spend today > $15",
                 "conditionThreshold": {
                     "filter": 'metric.type="logging.googleapis.com/user/engine_spend_today_usd" AND resource.type="cloud_run_revision"',
                     "aggregations": [{"alignmentPeriod": "600s", "perSeriesAligner": "ALIGN_PERCENTILE_99",
                                       "crossSeriesReducer": "REDUCE_MAX"}],
                     "comparison": "COMPARISON_GT", "thresholdValue": 15, "duration": "0s"}}, ch),
    ]
    for pol in want:
        if pol["displayName"] not in have:
            _ok(c.post(f"{MON}/projects/{p}/alertPolicies", json=pol))


def _tile(title: str, flt: str, aligner: str = "ALIGN_PERCENTILE_95", reducer: str = "REDUCE_MAX",
          period: str = "600s") -> dict[str, Any]:
    return {"title": title, "xyChart": {"dataSets": [{"plotType": "LINE", "timeSeriesQuery": {"timeSeriesFilter": {
        "filter": flt, "aggregation": {"alignmentPeriod": period, "perSeriesAligner": aligner,
                                       "crossSeriesReducer": reducer}}}}]}}


def dashboard(c: httpx.Client, p: str, check_id: str) -> None:
    """Tick p95, spend, rendered ratio, viewers, uptime, Cloud Run instances + CPU."""
    for d in _ok(c.get(f"{MON[:-3]}/v1/projects/{p}/dashboards")).get("dashboards", []):
        if d["displayName"] == "mirava world":
            return
    u = lambda m: f'metric.type="logging.googleapis.com/user/{m}" AND resource.type="cloud_run_revision"'  # noqa: E731
    run = 'resource.type="cloud_run_revision" AND resource.label.service_name="world-engine"'
    tiles = [
        _tile("Tick p95 (ms)", u("engine_tick_p95_ms")),
        _tile("Spend today (USD, simulated world)", u("engine_spend_today_usd")),
        _tile("Rendered ratio", u("engine_rendered_ratio")),
        _tile("Live viewers", u("engine_live_viewers")),
        _tile("/health uptime (passed)", f'metric.type="monitoring.googleapis.com/uptime_check/check_passed" AND '
              f'resource.type="uptime_url" AND metric.label.check_id="{check_id}"', "ALIGN_FRACTION_TRUE", "REDUCE_MEAN", "60s"),
        _tile("world-engine instances", f'metric.type="run.googleapis.com/container/instance_count" AND {run}',
              "ALIGN_MAX", "REDUCE_SUM", "60s"),
        _tile("world-engine CPU", f'metric.type="run.googleapis.com/container/cpu/utilizations" AND {run}',
              "ALIGN_PERCENTILE_95", "REDUCE_MAX", "60s"),
        _tile("mirava-api requests by class", 'metric.type="run.googleapis.com/request_count" AND '
              'resource.type="cloud_run_revision" AND resource.label.service_name="mirava-api"', "ALIGN_RATE", "REDUCE_SUM", "60s"),
    ]
    _ok(c.post(f"{MON[:-3]}/v1/projects/{p}/dashboards", json={
        "displayName": "mirava world", "gridLayout": {"columns": "2", "widgets": tiles}}))


def main() -> None:
    """Create everything for guide 13."""
    p, email = sys.argv[1], sys.argv[2]
    with httpx.Client(headers=_h(), timeout=30) as c:
        ch = channel(c, p, email)
        up = uptime(c, p)
        check_id = up.rsplit("/", 1)[-1]
        log_metrics(c, p)
        policies(c, p, ch, check_id)
        dashboard(c, p, check_id)
    print({"channel": ch, "uptime": up, "metrics": list(METRICS), "policies": 3, "dashboard": "mirava world"})


if __name__ == "__main__":
    main()
