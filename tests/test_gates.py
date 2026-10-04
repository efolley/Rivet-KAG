"""Mini test suite for the release-gate threshold logic (evals/gates.py): every blocking
dimension from README's "Evaluation and release gates" table, the warn/block split for
latency/cost, and that a missing metric is reported honestly rather than silently passing or
auto-failing in the wrong direction.
"""

from evals.gates import GateMetrics, GateStatus, evaluate_gates

PASSING_METRICS = GateMetrics(
    retrieval_hit_rate=1.0,
    mean_judge_score=4.5,
    min_judge_score=4,
    mean_faithfulness_score=0.9,
    latency_p50_ms=1000,
    latency_p95_ms=3000,
    mean_cost_usd=0.05,
)


def test_all_dimensions_pass_with_healthy_metrics() -> None:
    report = evaluate_gates(PASSING_METRICS)
    assert not report.blocked
    assert not report.warned
    assert all(r.status is GateStatus.PASS for r in report.results)


def test_low_retrieval_hit_rate_blocks() -> None:
    report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "retrieval_hit_rate": 0.5}))
    assert report.blocked


def test_low_mean_judge_score_blocks() -> None:
    report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "mean_judge_score": 3.0}))
    assert report.blocked


def test_a_single_low_judge_score_blocks_even_if_the_mean_is_fine() -> None:
    report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "min_judge_score": 2}))
    assert report.blocked


def test_low_faithfulness_score_blocks() -> None:
    report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "mean_faithfulness_score": 0.3}))
    assert report.blocked


def test_latency_warns_then_blocks_at_higher_thresholds() -> None:
    warn_report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "latency_p50_ms": 3000}))
    assert warn_report.warned and not warn_report.blocked

    block_report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "latency_p50_ms": 6000}))
    assert block_report.blocked


def test_cost_warns_then_blocks_at_higher_thresholds() -> None:
    warn_report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "mean_cost_usd": 0.17}))
    assert warn_report.warned and not warn_report.blocked

    block_report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "mean_cost_usd": 0.25}))
    assert block_report.blocked


def test_missing_blocking_dimension_blocks_rather_than_silently_passing() -> None:
    # A blocking dimension's metric wasn't measured -- can't claim it passed.
    report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "retrieval_hit_rate": None}))
    assert report.blocked
    missing = next(r for r in report.results if r.dimension == "Retrieval quality")
    assert missing.status is GateStatus.BLOCK
    assert missing.value is None


def test_missing_warn_only_dimension_warns_rather_than_blocking() -> None:
    report = evaluate_gates(GateMetrics(**{**PASSING_METRICS.__dict__, "mean_cost_usd": None}))
    assert not report.blocked
    missing = next(r for r in report.results if r.dimension == "Cost")
    assert missing.status is GateStatus.WARN


def test_missing_hitl_metrics_pass_rather_than_block_or_warn() -> None:
    # No production traffic exists to sample HITL from -- this must never be the reason a
    # release is blocked.
    report = evaluate_gates(PASSING_METRICS)
    hitl_results = [r for r in report.results if r.dimension == "HITL"]
    assert len(hitl_results) == 2
    assert all(r.status is GateStatus.PASS for r in hitl_results)
    assert all(r.value is None for r in hitl_results)
