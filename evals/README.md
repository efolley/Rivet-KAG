Live, manual, credential-requiring eval/ops scripts — never part of CI (see CLAUDE.md's
development philosophy). `golden_questions.json` (30 questions) is the shared golden set.

- `check_retrieval.py` (`make eval`) — live retrieval-accuracy check against Milvus + Neo4j.
- `judge.py` (`make judge`) — simple 1-5 LLM-as-a-judge score against the real pipeline.
- `deepeval_suite.py` (`make deepeval`) — the DeepEval upgrade: `GEval` (correctness) and
  `FaithfulnessMetric` (citation faithfulness) against the real pipeline.
- `release_gates.py` (`make gates`) — runs retrieval + judge + deepeval, applies the threshold
  table in README's "Evaluation and release gates", exits non-zero on any blocking gate.
- `check_alerts.py` (`make alerts`) — reads recent `chat_audit_log` rows and applies the
  threshold table in README's "Observability and audit trail" -> "Alert conditions".

The actual gate/alert *decision logic* (`evals/gates.py`, `evals/alerts.py`) is pure and has no
live dependencies — it's unit-tested in the normal offline suite (`tests/test_gates.py`,
`tests/test_alerts.py`), unlike the scripts above that gather its inputs.
