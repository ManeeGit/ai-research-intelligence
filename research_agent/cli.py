from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .briefs import daily_brief, write_brief
from .evaluation import evaluate
from .retrieval import answer, search
from .scheduler import watch
from .sources import FIXTURES, ingest_sources, load_fixture
from .store import Store
from .web import serve


def output(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local-first research intelligence with verifiable evidence.")
    root.add_argument("--db", default="data/research.sqlite3", help="Local SQLite database (default: data/research.sqlite3)")
    sub = root.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Load 12 clearly labeled fictional research records")
    demo.add_argument("--out", default="reports")
    ingest = sub.add_parser("ingest", help="Import a reviewed local JSON file or approved arXiv queries")
    sources = ingest.add_mutually_exclusive_group(required=True)
    sources.add_argument("--file")
    sources.add_argument("--config")
    ingest.add_argument("--allow-network", action="store_true")
    query = sub.add_parser("ask", help="Return exact, verified evidence excerpts or abstain")
    query.add_argument("question")
    query.add_argument("--local-model", help="Optional already-installed Ollama model; loopback only")
    lookup = sub.add_parser("search", help="Rank local abstracts with BM25")
    lookup.add_argument("query")
    lookup.add_argument("--limit", type=int, default=8)
    brief = sub.add_parser("brief", help="Write a local daily Markdown and JSON research brief")
    brief.add_argument("--day", help="UTC ingestion day, YYYY-MM-DD; default today")
    brief.add_argument("--topic", action="append")
    brief.add_argument("--out", default="reports")
    watch_command = sub.add_parser("watch", help="Run a finite foreground watcher, offline by default")
    watch_command.add_argument("--cycles", type=int, default=1)
    watch_command.add_argument("--interval", type=float, default=900)
    watch_command.add_argument("--config")
    watch_command.add_argument("--allow-network", action="store_true")
    watch_command.add_argument("--out", default="reports")
    web = sub.add_parser("serve", help="Open a read-only loopback dashboard")
    web.add_argument("--port", type=int, default=8765)
    sub.add_parser("status", help="Inspect local index counts")
    sub.add_parser("evaluate", help="Run the bundled synthetic retrieval regression suite")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            serve(args.db, args.port)
            return 0
        if args.command == "watch":
            watch(args.db, args.out, cycles=args.cycles, interval=args.interval,
                  config=args.config, allow_network=args.allow_network, emit=output)
            return 0
        with Store(args.db) as store:
            if args.command == "demo":
                result = store.ingest(load_fixture(), "offline-fixture")
                paths = write_brief(daily_brief(store), args.out)
                output({"notice": "Synthetic demo only: no real papers, network calls, or model downloads.",
                        "ingestion": result, "brief": str(paths[0]), "next": "python -m research_agent serve"})
            elif args.command == "ingest":
                if args.file:
                    if args.allow_network:
                        raise ValueError("--allow-network is only valid with --config")
                    output(store.ingest(load_fixture(args.file), "local-json"))
                else:
                    output(ingest_sources(store, args.config, allow_network=args.allow_network))
            elif args.command == "ask":
                output(answer(store, args.question, local_model=args.local_model))
            elif args.command == "search":
                output([r.to_dict() for r in search(store, args.query, args.limit)])
            elif args.command == "brief":
                output({"files": [str(p) for p in write_brief(daily_brief(store, day=args.day, topics=args.topic), args.out)]})
            elif args.command == "evaluate":
                result = evaluate(store)
                output(result)
                return 0 if result["passed"] == result["total"] else 1
            elif args.command == "status":
                output(store.stats())
        return 0
    except KeyboardInterrupt:
        print("Stopped. No background watcher is running.", file=sys.stderr)
        return 130
    except (ValueError, TypeError, OSError, sqlite3.Error) as error:
        # Avoid echoing URLs, question text, or remote response bodies on errors.
        if isinstance(error, (ValueError, TypeError)) and not isinstance(error, json.JSONDecodeError):
            print(f"Error: {error}", file=sys.stderr)
        else:
            print(f"Error: {type(error).__name__}. Check local paths, configuration, or source availability.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
