"""Applies the alert-condition thresholds (README's "Observability and audit trail" ->
"Alert conditions", logic in evals/alerts.py) to recent chat_audit_log rows. This is a
stand-in for a real metrics/alerting pipeline (Prometheus + Alertmanager or similar), which
doesn't exist in this project -- see README's "Alert conditions" for what a production version
would need instead. Run manually or on a cron; exits 1 if anything is at PAGE level.

Two of the six conditions are never computable with today's chat_audit_log schema or this
project's lack of production traffic -- see evals/alerts.py's AlertMetrics docstring. The other
four (cost, latency, error/guardrail rate, empty-result rate) are real, computed from live rows.

Requires DATABASE_URL to point at a reachable Postgres with real chat_audit_log traffic in it
(e.g. from using the app via `make dev` / `make up`) -- an empty table means every computable
condition reports `None` ("not computable"), not a false "all clear".

Usage:
  make alerts
  uv run python -m evals.check_alerts
"""

import asyncio
import sys

from sqlalchemy import func, select, text

from evals.alerts import AlertLevel, AlertMetrics, evaluate_alerts
from src.db import ChatAuditLog
from src.db.engine import get_session

ERROR_OUTCOMES = {"error", "guardrail_blocked"}


async def _rows_since(minutes: int) -> list[ChatAuditLog]:
    # The window boundary is computed with Postgres's own now() minus an interval, not a
    # Python-side datetime: created_at is TIMESTAMP WITHOUT TIME ZONE (server_default=func.now()
    # -- see src/db/models.py), and what that actually stores depends on the Postgres server's
    # `timezone` setting, not necessarily UTC. A client-computed UTC timestamp silently filtered
    # out every row when the two didn't agree (caught live: the server's `now()` ran ~4 hours
    # behind a naive `datetime.now(UTC)`). Computing the boundary in the same place the value
    # was written sidesteps the whole naive-vs-aware and which-timezone question.
    cutoff = func.now() - text(f"interval '{int(minutes)} minutes'")
    async for session in get_session():
        result = await session.execute(select(ChatAuditLog).where(ChatAuditLog.created_at >= cutoff))
        return list(result.scalars().all())
    return []  # pragma: no cover -- get_session always yields at least once


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


async def gather_alert_metrics() -> AlertMetrics:
    # Each window is its own query against func.now() rather than slicing one 30-minute batch
    # in Python, so every window agrees with the database's own clock independently -- no
    # client-side "now" enters the picture at all (see _rows_since's docstring).
    rows_30min = await _rows_since(30)
    rows_15min = await _rows_since(15)
    rows_10min = await _rows_since(10)
    rows_5min = await _rows_since(5)

    costs = [r.cost_usd for r in rows_15min if r.cost_usd is not None]
    # Cached/error/guardrail rows report duration_ms=0 or never ran the pipeline -- only a real
    # "success" row's duration reflects actual end-to-end latency.
    latencies = [r.duration_ms for r in rows_5min if r.outcome == "success"]
    errors_10min = sum(1 for r in rows_10min if r.outcome in ERROR_OUTCOMES)
    empty_30min = sum(1 for r in rows_30min if r.citations_count == 0 and r.outcome == "success")
    successful_30min = sum(1 for r in rows_30min if r.outcome == "success")

    return AlertMetrics(
        mean_cost_usd_15min=_mean(costs),
        p95_latency_ms_5min=_p95(latencies),
        error_or_guardrail_rate_10min=_rate(errors_10min, len(rows_10min)),
        router_fallback_rate_30min=None,  # not recorded in chat_audit_log today
        empty_result_rate_30min=_rate(empty_30min, successful_30min),
        judge_hallucination_rate_daily=None,  # no scheduled judge run against production traffic
    )


async def main() -> int:
    metrics = await gather_alert_metrics()
    alerts = evaluate_alerts(metrics)

    for a in alerts:
        marker = {AlertLevel.OK: "OK", AlertLevel.WARN: "WARN", AlertLevel.PAGE: "PAGE"}[a.level]
        print(f"[{marker}] {a.condition}: {a.detail}")

    paged = [a for a in alerts if a.level is AlertLevel.PAGE]
    if paged:
        print(f"\n{len(paged)} condition(s) at PAGE level.")
        return 1
    print("\nNo paging alerts.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
