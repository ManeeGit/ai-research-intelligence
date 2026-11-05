from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import MAX_PAPERS, Paper, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY, external_id TEXT NOT NULL, source TEXT NOT NULL,
    title TEXT NOT NULL, abstract TEXT NOT NULL, authors TEXT NOT NULL,
    published TEXT NOT NULL, url TEXT NOT NULL, synthetic INTEGER NOT NULL,
    content_hash TEXT NOT NULL, first_seen TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestions (
    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, source TEXT NOT NULL,
    added INTEGER NOT NULL, updated INTEGER NOT NULL, unchanged INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    day TEXT NOT NULL, source TEXT NOT NULL, count INTEGER NOT NULL,
    PRIMARY KEY (day, source)
);
CREATE INDEX IF NOT EXISTS idx_published ON papers(published);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.execute("PRAGMA busy_timeout=5000")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def ingest(self, papers: list[Paper], source_label: str = "local") -> dict:
        if len(papers) > 500:
            raise ValueError("An ingestion may contain at most 500 papers")
        added = updated = unchanged = 0
        now = utc_now()
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            existing = {r["id"]: r["content_hash"] for r in self.conn.execute(
                "SELECT id, content_hash FROM papers")}
            new_ids = {p.key for p in papers} - set(existing)
            if len(existing) + len(new_ids) > MAX_PAPERS:
                raise ValueError(f"Local index is capped at {MAX_PAPERS} papers")
            for paper in papers:
                old_hash = existing.get(paper.key)
                if old_hash == paper.content_hash:
                    unchanged += 1
                    continue
                record = (paper.key, paper.external_id, paper.source, paper.title,
                          paper.abstract, json.dumps(paper.authors), paper.published,
                          paper.url, int(paper.synthetic), paper.content_hash, now, now)
                self.conn.execute("""INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                    abstract=excluded.abstract, authors=excluded.authors,
                    published=excluded.published, url=excluded.url,
                    synthetic=excluded.synthetic, content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at""", record)
                if old_hash is None:
                    added += 1
                else:
                    updated += 1
                existing[paper.key] = paper.content_hash
            self.conn.execute("INSERT INTO ingestions(started_at,source,added,updated,unchanged) VALUES(?,?,?,?,?)",
                              (now, source_label, added, updated, unchanged))
        return {"added": added, "updated": updated, "unchanged": unchanged, "total": self.count()}

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    def all(self) -> list[dict]:
        return [self._row(row) for row in self.conn.execute("SELECT * FROM papers ORDER BY published DESC, id")]

    def get(self, paper_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row) -> dict:
        result = dict(row)
        result["authors"] = json.loads(result["authors"])
        result["synthetic"] = bool(result["synthetic"])
        return result

    def stats(self) -> dict:
        papers = self.all()
        run = self.conn.execute("SELECT * FROM ingestions ORDER BY id DESC LIMIT 1").fetchone()
        return {"papers": len(papers), "synthetic": sum(p["synthetic"] for p in papers),
                "sources": len({p["source"] for p in papers}),
                "last_ingestion": dict(run) if run else None,
                "mode": "offline-first", "max_papers": MAX_PAPERS}

    def reserve_request(self, source: str, daily_limit: int, day: str | None = None):
        """Reserve quota before network IO; failures also consume quota."""
        day = day or utc_now()[:10]
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT count FROM requests WHERE day=? AND source=?", (day, source)).fetchone()
            if row and row[0] >= daily_limit:
                raise ValueError("Daily source request budget exhausted")
            self.conn.execute("INSERT INTO requests(day,source,count) VALUES(?,?,1) "
                              "ON CONFLICT(day,source) DO UPDATE SET count=count+1", (day, source))
