"""DeepEval suite: the "planned upgrade" from README's "LLM-as-a-judge" section. Unlike
evals/judge.py's single 1-5 correctness score, this runs two framework metrics per question —
`GEval` (a fuller correctness rubric vs. the reference answer) and `FaithfulnessMetric` (are the
answer's claims actually supported by the retrieved context, i.e. hallucination/citation
faithfulness) — each scored 0-1 by a judge LLM.

Requires ANTHROPIC_API_KEY (the pipeline's answerer and the judge both call Claude) and, for
retrieval to find anything, Milvus + Neo4j loaded via `make ingest`. Also requires the `eval`
dependency group (`uv sync --group eval` or `make deepeval`) -- deepeval is NOT installed by
default; see pyproject.toml's `addopts = "-p no:deepeval"` for why that matters (its pytest
plugin calls load_dotenv() during plugin loading, before conftest.py can stop it).

Costs real money to run: one answering call, plus one GEval call and one FaithfulnessMetric
call (itself 1+ calls to extract then verify claims) per question.

Usage:
  make deepeval
  uv run --group eval python -m evals.deepeval_suite
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from src.config import Settings, get_settings
from src.pipeline.factory import build_pipeline
from src.schemas import ChatRequest

QUESTIONS_PATH = Path(__file__).parent / "golden_questions.json"

# Judge independence (README's "LLM-as-a-judge"): default to a different, pricier tier than the
# Haiku-class model the answerer typically runs, to reduce self-preference bias.
DEFAULT_JUDGE_MODEL = "claude-sonnet-5"


@dataclass
class QuestionResult:
    question: str
    geval_score: float
    geval_reason: str
    faithfulness_score: float
    faithfulness_reason: str


@dataclass
class DeepEvalSuiteResult:
    results: list[QuestionResult]

    @property
    def mean_geval_score(self) -> float:
        return sum(r.geval_score for r in self.results) / len(self.results)

    @property
    def mean_faithfulness_score(self) -> float:
        return sum(r.faithfulness_score for r in self.results) / len(self.results)


class AnthropicJudgeModel:
    """A deepeval.models.DeepEvalBaseLLM wrapping ChatAnthropic, so the judge is Claude (same
    provider/quality bar as evals/judge.py) rather than deepeval's OpenAI-shaped defaults. No
    `generate_with_schema` override: the base class's default tries `generate(prompt,
    schema=...)`, catches the TypeError since this model doesn't accept that kwarg, and falls
    back to plain `generate(prompt)` -- deepeval then extracts JSON from the text itself, which
    is the standard pattern for a custom (non-"native") judge model."""

    def __init__(self, model_name: str, api_key: str) -> None:
        # Deliberately NOT a DeepEvalBaseLLM subclass at import time -- that base class is only
        # importable with the `eval` dependency group installed, and this module's own light
        # bits (QuestionResult, DeepEvalSuiteResult) should stay importable without it. See
        # build_judge_model() below, where the real subclass is constructed behind the import.
        self._model_name = model_name
        self._api_key = api_key
        self.name = model_name
        self.model = self.load_model()

    def load_model(self) -> ChatAnthropic:
        return ChatAnthropic(
            model_name=self._model_name,
            api_key=SecretStr(self._api_key),
            temperature=0,
            max_tokens_to_sample=1024,
            timeout=30,
            stop=None,
        )

    def generate(self, prompt: str) -> str:
        result = self.model.invoke(prompt)
        return str(result.content)

    async def a_generate(self, prompt: str) -> str:
        result = await self.model.ainvoke(prompt)
        return str(result.content)

    def get_model_name(self) -> str:
        return self._model_name


def build_judge_model(settings: Settings, model_name: str = DEFAULT_JUDGE_MODEL) -> Any:
    from deepeval.models import DeepEvalBaseLLM

    # Mix the real DeepEvalBaseLLM base in only now, so importing this module doesn't require
    # the `eval` group -- only actually running the suite does.
    cls = type("AnthropicJudgeModel", (AnthropicJudgeModel, DeepEvalBaseLLM), {})
    return cls(model_name, settings.anthropic_api_key)


async def run_deepeval_suite(settings: Settings, judge_model_name: str = DEFAULT_JUDGE_MODEL) -> DeepEvalSuiteResult:
    """Runs the real pipeline + GEval + FaithfulnessMetric over every golden question with a
    reference_answer. The reusable core evals/release_gates.py calls directly, separate from
    this module's own print-and-exit CLI below."""
    from deepeval.metrics import FaithfulnessMetric, GEval
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    questions = [q for q in json.loads(QUESTIONS_PATH.read_text()) if q.get("reference_answer")]
    if not questions:
        sys.exit("No golden questions have a reference_answer to evaluate.")

    pipeline = build_pipeline(settings)
    judge_model = build_judge_model(settings, judge_model_name)

    correctness = GEval(
        name="Correctness",
        criteria=(
            "Determine whether the actual output is factually correct and consistent with the "
            "expected output. Different wording is fine as long as the facts match."
        ),
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
        model=judge_model,
        threshold=0.7,
    )
    faithfulness = FaithfulnessMetric(threshold=0.8, model=judge_model, include_reason=True)

    results: list[QuestionResult] = []
    for q in questions:
        response = await pipeline.run(ChatRequest(session_id="eval-deepeval", message=q["question"]))
        retrieval_context: list[str | Any] = [c.snippet for c in response.citations] or ["(no context was retrieved)"]
        test_case = LLMTestCase(
            input=q["question"],
            actual_output=response.answer,
            expected_output=q["reference_answer"],
            retrieval_context=retrieval_context,
        )
        correctness.measure(test_case)
        faithfulness.measure(test_case)
        results.append(
            QuestionResult(
                question=q["question"],
                geval_score=correctness.score or 0.0,
                geval_reason=correctness.reason or "",
                faithfulness_score=faithfulness.score or 0.0,
                faithfulness_reason=faithfulness.reason or "",
            )
        )

    return DeepEvalSuiteResult(results=results)


async def main() -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is required: the answerer and the judge both call Claude.")
    settings = settings.model_copy(update={"use_stubs": False})

    suite = await run_deepeval_suite(settings)
    for r in suite.results:
        print(
            f"[{r.question}]\n"
            f"       correctness={r.geval_score:.2f} {r.geval_reason}\n"
            f"       faithfulness={r.faithfulness_score:.2f} {r.faithfulness_reason}"
        )

    print(
        f"\nMean correctness (GEval): {suite.mean_geval_score:.2f}/1.0\n"
        f"Mean faithfulness: {suite.mean_faithfulness_score:.2f}/1.0"
    )
    return 0 if suite.mean_geval_score >= 0.7 and suite.mean_faithfulness_score >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
