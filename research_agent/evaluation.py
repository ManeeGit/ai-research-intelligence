from __future__ import annotations

from pathlib import Path

from .retrieval import answer, search, verify_citation
from .sources import read_json
from .store import Store

EVALUATION = Path(__file__).parent / "fixtures" / "evaluation.json"


def evaluate(store: Store, cases_path: str | Path = EVALUATION) -> dict:
    cases = read_json(cases_path)["cases"]
    rows = []
    for case in cases:
        response = answer(store, case["query"])
        retrieved = search(store, case["query"], limit=3)
        recall = case.get("expected_external_id") in {r.paper["external_id"] for r in retrieved}
        abstains = response["status"] == "insufficient_evidence"
        citations_ok = all(verify_citation(store, c) for c in response["citations"])
        passed = citations_ok and (abstains if case["expect_abstain"] else (recall and not abstains))
        rows.append({"id": case["id"], "passed": passed, "abstained": abstains,
                     "recall_at_3": recall if not case["expect_abstain"] else None,
                     "citations_valid": citations_ok, "citation_count": len(response["citations"])})
    answerable = [r for r in rows if r["recall_at_3"] is not None]
    unanswerable = [r for r in rows if r["recall_at_3"] is None]
    return {"scope": "Synthetic regression suite only; not a scientific quality or real-world accuracy benchmark.",
            "cases": rows, "passed": sum(r["passed"] for r in rows), "total": len(rows),
            "recall_at_3": sum(r["recall_at_3"] for r in answerable) / len(answerable) if answerable else 0,
            "abstention_rate": sum(r["abstained"] for r in unanswerable) / len(unanswerable) if unanswerable else 0,
            "citation_validity": all(r["citations_valid"] for r in rows)}
