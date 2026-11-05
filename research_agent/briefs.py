from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .models import tokens, utc_now
from .retrieval import sentences
from .store import Store

DEFAULT_TOPICS = ["retrieval generation", "agent evaluation", "privacy security", "efficient inference"]


def md(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", text)


def daily_brief(store: Store, *, day: str | None = None, topics: list[str] | None = None) -> dict:
    day = day or utc_now()[:10]
    date.fromisoformat(day)
    topics = topics or DEFAULT_TOPICS
    if len(topics) > 10 or any(not isinstance(t, str) or not 1 <= len(t) <= 200 for t in topics):
        raise ValueError("Use at most ten topics of 1–200 characters each")
    changed = [p for p in store.all() if p["first_seen"][:10] == day or p["updated_at"][:10] == day]
    highlights = []
    for paper in changed[:20]:
        spans = sentences(paper["abstract"])
        quote = spans[0][2] if spans else paper["abstract"]
        highlights.append({"paper_id": paper["id"], "title": paper["title"], "url": paper["url"],
                           "quote": quote, "synthetic": paper["synthetic"],
                           "topics": [t for t in topics if set(tokens(t)) & set(tokens(paper["title"] + " " + paper["abstract"]))],
                           "published": paper["published"], "content_hash": paper["content_hash"]})
    return {"day": day, "generated_at": utc_now(), "new_or_changed": len(changed),
            "shown": len(highlights), "total_indexed": store.count(), "topics": topics,
            "synthetic": any(p["synthetic"] for p in changed), "highlights": highlights,
            "scope": "Papers first seen or changed locally on this UTC day; not necessarily published today.",
            "limitations": "Abstract-only, unverified research claims. Demo fixtures are fictional. No email or external delivery."}


def render_markdown(brief: dict) -> str:
    lines = [f"# Research brief · {brief['day']}", "", brief["scope"], "",
             f"{brief['new_or_changed']} new or changed records · {brief['total_indexed']} indexed · {brief['shown']} shown", ""]
    if brief["synthetic"]:
        lines.extend(["> SYNTHETIC DEMO: fictional papers are included. Do not cite them as research.", ""])
    if not brief["highlights"]:
        lines.extend(["No new or changed papers were recorded on this day.", ""])
    for index, paper in enumerate(brief["highlights"], 1):
        lines.extend([f"## {index}. {md(paper['title'])}", "",
                      f"{'Synthetic fixture' if paper['synthetic'] else 'arXiv abstract'} · Published {paper['published'][:10]}", "",
                      f"> {md(paper['quote'])}", "",
                      f"Source: {md(paper['url'])}",
                      f"Record: {paper['paper_id']} · Content SHA-256: {paper['content_hash']}",
                      "Topics: " + (", ".join(md(t) for t in paper["topics"]) or "Uncategorized"), ""])
    lines.extend(["## Reading checklist", "", "- Read the full paper before relying on a claim.",
                  "- Inspect the evaluation setup, baselines, limitations, and code availability.",
                  "- Confirm whether the result transfers to your own workload.", "", brief["limitations"], ""])
    return "\n".join(lines)


def write_brief(brief: dict, directory: str | Path) -> tuple[Path, Path]:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    # Explicit local output only; no delivery plugins or network behavior.
    stem = f"brief-{brief['day']}"
    markdown, structured = path / f"{stem}.md", path / f"{stem}.json"
    for target, text in ((markdown, render_markdown(brief)), (structured, json.dumps(brief, indent=2))):
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(target)
    return markdown, structured
