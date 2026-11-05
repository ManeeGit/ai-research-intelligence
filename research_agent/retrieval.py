from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .models import tokens, utc_now
from .store import Store


@dataclass
class SearchResult:
    paper: dict
    score: float
    matched_terms: list[str]

    def to_dict(self) -> dict:
        return {**self.paper, "score": round(self.score, 4), "matched_terms": self.matched_terms}


def search(store: Store, query: str, limit: int = 8) -> list[SearchResult]:
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 3000:
        raise ValueError("A question must contain 1–3000 characters")
    if not 1 <= limit <= 20:
        raise ValueError("Search limit must be between 1 and 20")
    terms = set(tokens(query))
    papers = store.all()
    if not terms or not papers:
        return []
    docs = [Counter(tokens(p["title"] + " " + p["title"] + " " + p["abstract"])) for p in papers]
    avg_length = sum(sum(doc.values()) for doc in docs) / len(docs)
    frequencies = {term: sum(term in doc for doc in docs) for term in terms}
    results = []
    for paper, doc in zip(papers, docs):
        matched = terms & set(doc)
        if not matched:
            continue
        score = 0.0
        for term in matched:
            count = doc[term]
            inverse = math.log(1 + (len(docs) - frequencies[term] + .5) / (frequencies[term] + .5))
            score += inverse * (count * 2.2) / (count + 1.2 * (.25 + .75 * sum(doc.values()) / avg_length))
        # Coverage makes a partial rare-token match less likely to dominate.
        score *= .5 + .5 * len(matched) / len(terms)
        results.append(SearchResult(paper, score, sorted(matched)))
    return sorted(results, key=lambda r: (-r.score, r.paper["id"]))[:limit]


def sentences(text: str) -> list[tuple[int, int, str]]:
    result = []
    for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", text):
        start, end = match.span()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start >= 20:
            result.append((start, end, text[start:end]))
    return result


def verify_citation(store: Store, citation: dict) -> bool:
    paper = store.get(citation.get("paper_id", ""))
    if paper is None:
        return False
    start, end = citation.get("start"), citation.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(paper["abstract"]):
        return False
    return (paper["abstract"][start:end] == citation.get("quote")
            and paper["content_hash"] == citation.get("content_hash")
            and paper["url"] == citation.get("url"))


def answer(store: Store, query: str, *, limit: int = 4, local_model: str | None = None) -> dict:
    results = search(store, query, limit=12)
    query_terms = set(tokens(query))
    citations = []
    min_overlap = min(2, len(query_terms))
    for result in results:
        candidates = []
        for start, end, sentence in sentences(result.paper["abstract"]):
            overlap = len(query_terms & set(tokens(sentence)))
            if overlap >= min_overlap:
                candidates.append((overlap, start, end, sentence))
        if not candidates:
            continue
        overlap, start, end, quote = max(candidates, key=lambda c: (c[0], -c[1]))
        paper = result.paper
        citations.append({"id": f"E{len(citations) + 1}", "paper_id": paper["id"],
                          "title": paper["title"], "url": paper["url"], "source": paper["source"],
                          "quote": quote, "start": start, "end": end,
                          "content_hash": paper["content_hash"], "synthetic": paper["synthetic"],
                          "published": paper["published"], "score": round(result.score, 4),
                          "matched_terms": result.matched_terms})
        if len(citations) == limit:
            break
    mode = "extractive"
    model_note = None
    if local_model and citations:
        from .local_model import select_evidence
        citations, model_note = select_evidence(query, citations, local_model)
        mode = "local-evidence-selection" if model_note is None else "extractive-fallback"
    if any(not verify_citation(store, c) for c in citations):
        raise ValueError("Citation integrity check failed; no answer was generated")
    return {"query": query, "status": "evidence_found" if citations else "insufficient_evidence",
            "summary": "Relevant source excerpts. These are retrieval matches, not independently validated conclusions."
            if citations else "I could not find enough matching evidence in the indexed abstracts. Try a narrower question or add an approved source.",
            "mode": mode, "model_note": model_note, "generated_at": utc_now(),
            "citations": citations, "synthetic": any(c["synthetic"] for c in citations),
            "limitations": ["Abstract-only coverage; full papers were not read.",
                            "Lexical matching can miss synonyms and does not establish scientific validity.",
                            "Synthetic demo records are not real publications."]}
