"""LLM-as-a-judge: grades the full pipeline's answers (not just retrieval) against a reference
answer. Unlike evals/check_retrieval.py, which only checks whether the right source came back,
this checks whether the final, DeepAgents-generated answer is actually correct — golden-string
matching can't do that for free-text answers. See the README's "LLM-as-a-judge" section.

Requires ANTHROPIC_API_KEY (both the pipeline's answerer and the judge call Claude) and, for
retrieval to find anything, Milvus + Neo4j loaded via `make ingest`. This forces real retrieval
(USE_STUBS=false) regardless of the .env setting, since judging stub citations against real
reference answers would be meaningless.

Costs real money to run: one answering call plus one judging call per question.

Usage:
  make judge
  uv run python -m evals.judge
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, SecretStr

from src.config import get_settings
from src.pipeline.factory import build_pipeline
from src.schemas import ChatRequest

QUESTIONS_PATH = Path(__file__).parent / "golden_questions.json"
PASS_THRESHOLD = 4

JUDGE_SYSTEM_PROMPT = """You are grading a knowledge assistant's answer against a reference \
answer. Score 1-5: 5 = fully correct and consistent with the reference, 3 = partially correct \
or missing an important detail, 1 = wrong or contradicts the reference. The assistant may use \
different words than the reference and still score 5 if the facts match. `passed` is true only \
for scores of 4 or 5."""


class JudgeVerdict(BaseModel):
    score: Literal[1, 2, 3, 4, 5] = Field(description="1 (wrong) to 5 (fully correct)")
    passed: bool = Field(description=f"true if the answer is acceptable to ship (score >= {PASS_THRESHOLD})")
    rationale: str = Field(description="one sentence explaining the score")


def build_judge(settings: Any) -> Any:
    llm = ChatAnthropic(
        model_name=settings.llm_model,
        api_key=SecretStr(settings.anthropic_api_key),
        temperature=0,
        max_tokens_to_sample=300,
        timeout=20,
        stop=None,
    )
    return llm.with_structured_output(JudgeVerdict)


async def judge_answer(judge: Any, question: str, reference: str, actual: str) -> JudgeVerdict:
    result = await judge.ainvoke(
        [
            SystemMessage(JUDGE_SYSTEM_PROMPT),
            HumanMessage(f"Question: {question}\nReference answer: {reference}\nAssistant's answer: {actual}"),
        ]
    )
    if not isinstance(result, JudgeVerdict):
        raise TypeError(f"unexpected judge output type: {type(result)!r}")
    return result


async def run_judge(settings: Any) -> list[tuple[str, JudgeVerdict]]:
    """Runs the real pipeline + judge over every golden question with a reference_answer.
    Returns (question, verdict) pairs -- the reusable core evals/release_gates.py calls
    directly, separate from this module's own print-and-exit CLI below."""
    questions = [q for q in json.loads(QUESTIONS_PATH.read_text()) if q.get("reference_answer")]
    if not questions:
        sys.exit("No golden questions have a reference_answer to judge.")

    pipeline = build_pipeline(settings)
    judge = build_judge(settings)

    results = []
    for q in questions:
        response = await pipeline.run(ChatRequest(session_id="eval-judge", message=q["question"]))
        verdict = await judge_answer(judge, q["question"], q["reference_answer"], response.answer)
        results.append((q["question"], verdict))
    return results


async def main() -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is required: the answerer and the judge both call Claude.")
    settings = settings.model_copy(update={"use_stubs": False})

    results = await run_judge(settings)
    for question, verdict in results:
        status = "PASS" if verdict.passed else "FAIL"
        print(f"[{status}] {question}\n       score={verdict.score} {verdict.rationale}")

    scores = [verdict.score for _, verdict in results]
    passed = sum(1 for s in scores if s >= PASS_THRESHOLD)
    mean = sum(scores) / len(scores)
    print(f"\n{passed}/{len(scores)} passed, mean score {mean:.1f}/5")
    return 0 if passed == len(scores) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
