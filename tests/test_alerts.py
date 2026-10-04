"""Mini test suite for the alert-condition logic (evals/alerts.py): every condition from
README's "Observability and audit trail" -> "Alert conditions" table, the warn/page split, and
that a `None` metric is reported as "not computable" instead of silently OK.
"""

from evals.alerts import AlertLevel, AlertMetrics, evaluate_alerts


def test_healthy_metrics_are_all_ok() -> None:
    metrics = AlertMetrics(
        mean_cost_usd_15min=0.05,
        p95_latency_ms_5min=2000,
        error_or_guardrail_rate_10min=0.0,
        router_fallback_rate_30min=0.0,
        empty_result_rate_30min=0.0,
        judge_hallucination_rate_daily=0.0,
    )
    alerts = evaluate_alerts(metrics)
    assert all(a.level is AlertLevel.OK for a in alerts)


def test_cost_warns_then_pages_at_higher_thresholds() -> None:
    warn = next(a for a in evaluate_alerts(AlertMetrics(mean_cost_usd_15min=0.20)) if "cost" in a.condition.lower())
    assert warn.level is AlertLevel.WARN

    page = next(a for a in evaluate_alerts(AlertMetrics(mean_cost_usd_15min=0.35)) if "cost" in a.condition.lower())
    assert page.level is AlertLevel.PAGE


def test_latency_warns_then_pages_at_higher_thresholds() -> None:
    warn = next(a for a in evaluate_alerts(AlertMetrics(p95_latency_ms_5min=7000)) if "latency" in a.condition.lower())
    assert warn.level is AlertLevel.WARN

    page = next(a for a in evaluate_alerts(AlertMetrics(p95_latency_ms_5min=16000)) if "latency" in a.condition.lower())
    assert page.level is AlertLevel.PAGE


def test_error_rate_warns_then_pages_at_higher_thresholds() -> None:
    alerts_warn = evaluate_alerts(AlertMetrics(error_or_guardrail_rate_10min=0.05))
    warn = next(a for a in alerts_warn if "5xx" in a.condition)
    assert warn.level is AlertLevel.WARN

    alerts_page = evaluate_alerts(AlertMetrics(error_or_guardrail_rate_10min=0.15))
    page = next(a for a in alerts_page if "5xx" in a.condition)
    assert page.level is AlertLevel.PAGE


def test_router_fallback_rate_only_warns_never_pages() -> None:
    # README's table gives this condition a Warn tier only, no Page tier.
    alerts = evaluate_alerts(AlertMetrics(router_fallback_rate_30min=0.99))
    fallback = next(a for a in alerts if "fallback" in a.condition.lower())
    assert fallback.level is AlertLevel.WARN


def test_judge_hallucination_rate_pages_past_five_percent() -> None:
    alerts = evaluate_alerts(AlertMetrics(judge_hallucination_rate_daily=0.10))
    hallucination = next(a for a in alerts if "hallucination" in a.condition.lower())
    assert hallucination.level is AlertLevel.PAGE


def test_missing_metrics_are_reported_as_not_computable_not_silently_ok() -> None:
    alerts = evaluate_alerts(AlertMetrics())
    assert all(a.value is None for a in alerts)
    assert all(a.level is AlertLevel.OK for a in alerts)
    assert all("not computable" in a.detail or "not implemented" in a.detail for a in alerts)


def test_guardrail_trip_rate_warns_above_3x_baseline() -> None:
    alerts = evaluate_alerts(AlertMetrics(guardrail_trip_rate_vs_baseline=3.5))
    guardrail = next(a for a in alerts if "guardrail trip" in a.condition.lower())
    assert guardrail.level is AlertLevel.WARN


def test_cache_hit_rate_warns_below_half_of_baseline() -> None:
    alerts = evaluate_alerts(AlertMetrics(cache_hit_rate_vs_baseline=0.3))
    cache = next(a for a in alerts if "cache hit" in a.condition.lower())
    assert cache.level is AlertLevel.WARN

    alerts_ok = evaluate_alerts(AlertMetrics(cache_hit_rate_vs_baseline=0.9))
    cache_ok = next(a for a in alerts_ok if "cache hit" in a.condition.lower())
    assert cache_ok.level is AlertLevel.OK
