"""Applies the release-gate thresholds (README's "Evaluation and release gates", logic in
evals/gates.py) to a live run of retrieval + judge + DeepEval against the golden set. Exits 1 if
any gate blocks.

Requires ANTHROPIC_API_KEY, Milvus + Neo4j loaded via `make ingest`, and the `eval` dependency
group (`uv sync --group eval`). Costs real money (judge.py's pass plus deepeval_suite.py's
pass). HITL metrics are never measured here -- there's no production traffic in this project to
sample from; see evals/gates.py.

Usage:
  make gates
  uv run --group eval python -m evals.release_gates
"""

import asyncio
import json
import statistics
import sys
import time

from evals import judge
from evals.check_retrieval import QUESTIONS_PATH, run_retrieval_check
from evals.deepeval_suite import run_deepeval_suite
from evals.gates import GateMetrics, GateStatus, evaluate_gates
from src.config import Settings, get_settings
from src.pipeline.factory import build_pipeline
from src.schemas import ChatRequest


async def _measure_latency_and_cost(settings: Settings) -> tuple[list[float], list[float]]:
    """Runs the pipeline once per golden question (reusing the shared golden set) purely to
    sample end-to-end latency and per-request cost -- judge.py and deepeval_suite.py each also
    run the pipeline, but their job is correctness, not timing, so this is a separate pass
    rather than threading latency/cost collection into both."""
    questions = json.loads(QUESTIONS_PATH.read_text())
    pipeline = build_pipeline(settings)

    latencies: list[float] = []
    costs: list[float] = []
    for q in questions:
        start = time.perf_counter()
        response = await pipeline.run(ChatRequest(session_id="eval-gates", message=q["question"]))
        latencies.append((time.perf_counter() - start) * 1000)
        if response.total_cost_usd is not None:
            costs.append(response.total_cost_usd)
    return latencies, costs


def _percentile(values: list[float], pct: float) -> float:
    values = sorted(values)
    idx = min(len(values) - 1, int(len(values) * pct))
    return values[idx]


async def main() -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is required: the answerer, router and judges all call Claude.")
    settings = settings.model_copy(update={"use_stubs": False})

    print("Running retrieval check...")
    retrieval_results = await run_retrieval_check()
    retrieval_hit_rate = sum(1 for _, ok, _ in retrieval_results if ok) / len(retrieval_results)

    print("Running LLM-as-a-judge...")
    judge_results = await judge.run_judge(settings)
    judge_scores = [v.score for _, v in judge_results]

    print("Running DeepEval suite (GEval + FaithfulnessMetric)...")
    deepeval_result = await run_deepeval_suite(settings)

    print("Measuring latency and cost...")
    latencies, costs = await _measure_latency_and_cost(settings)

    metrics = GateMetrics(
        retrieval_hit_rate=retrieval_hit_rate,
        mean_judge_score=statistics.mean(judge_scores),
        min_judge_score=min(judge_scores),
        mean_faithfulness_score=deepeval_result.mean_faithfulness_score,
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
        mean_cost_usd=statistics.mean(costs) if costs else None,
    )
    report = evaluate_gates(metrics)

    print("\n=== Release gate report ===")
    for r in report.results:
        marker = {GateStatus.PASS: "PASS", GateStatus.WARN: "WARN", GateStatus.BLOCK: "BLOCK"}[r.status]
        print(f"[{marker}] {r.dimension} — {r.metric_name}: {r.detail}")

    if report.blocked:
        print("\nBLOCKED: one or more blocking gates failed.")
        return 1
    if report.warned:
        print("\nPASSED with warnings.")
        return 0
    print("\nPASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
