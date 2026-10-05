"""Mini test suite for evals/check_alerts.py's pure aggregation helpers (mean/p95/rate) -- the
part that's offline-testable. Querying chat_audit_log itself needs a live Postgres and is only
exercised by running the script manually (`make alerts`).
"""

from evals.check_alerts import _mean, _p95, _rate


def test_mean_of_empty_list_is_none_not_zero() -> None:
    assert _mean([]) is None


def test_mean_computes_the_average() -> None:
    assert _mean([1.0, 2.0, 3.0]) == 2.0


def test_p95_of_empty_list_is_none() -> None:
    assert _p95([]) is None


def test_p95_picks_the_95th_percentile_index() -> None:
    values = [float(i) for i in range(1, 101)]  # 1..100
    assert _p95(values) == 96.0


def test_rate_of_zero_denominator_is_none_not_zero_or_error() -> None:
    assert _rate(0, 0) is None


def test_rate_computes_the_ratio() -> None:
    assert _rate(3, 12) == 0.25
