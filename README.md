# Fieldnote · AI Research Intelligence

A local-first research agent that turns an explicitly chosen source collection into a searchable evidence library, verifiable answers, and daily reading briefs.

**Runs offline, with zero runtime dependencies.** Python 3.11+, SQLite, and a browser are enough. The default demo contains **12 fictional papers**, not real research. A language model is optional, never automatically downloaded, and never trusted to invent citations.

## In one minute

```bash
python3 -m research_agent demo
python3 -m research_agent ask "How can exact citation quotes and offsets be verified?"
python3 -m research_agent serve
```

Open **http://127.0.0.1:8765**. The dashboard has an overview, paper library, evidence search, and downloadable daily brief. Press Ctrl-C to stop. No daemon, account, key, or external communication is created.

Use `python3` from the repository root, or optionally install into a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --no-deps -e .
research-agent demo
```

Package installation may need setuptools from the normal Python package index. Running from the checkout does not require installation or internet access.

## What makes this an agent project

- **Bounded research loop:** collect → validate → deduplicate → retrieve → verify → brief. Finite scheduling and a persistent network budget make each run inspectable.
- **Evidence-first answering:** BM25 retrieves matching abstracts. Answers contain exact source quotations, character offsets, source URLs, and content SHA-256 hashes. Every citation is verified before release.
- **Optional local AI:** an already-installed Ollama model can choose and reorder known evidence IDs. Invalid, invented, or unavailable model output falls back to the verified baseline. The model has no tools.
- **Source tracking:** stable identifiers deduplicate repeated ingestion; changed abstracts update the same record. Daily briefs distinguish when a paper was ingested from when it was published.
- **Honest abstention:** insufficient lexical evidence produces an explicit “not enough evidence” response. This is a conservative heuristic, not a calibrated confidence estimate.
- **Useful interface:** responsive local dashboard, library filtering, evidence cards, cancellation, and local Markdown downloads. No CDN, tracking script, remote font, or client framework.
- **Reproducible evaluation:** 12 synthetic retrieval/abstention cases plus adversarial and integration tests. These regression results are not a real-world research-quality benchmark.

## Commands

```bash
# All state stays beneath the current directory by default.
python3 -m research_agent status
python3 -m research_agent search "BM25 lexical retrieval" --limit 5
python3 -m research_agent ask "What protects against prompt injection in retrieved documents?"
python3 -m research_agent brief --topic "agent evaluation" --out reports
python3 -m research_agent brief --day 2026-11-05
python3 -m research_agent evaluate

# Use a different database. Global --db goes before the subcommand.
python3 -m research_agent --db data/another.sqlite3 demo

# Two offline cycles, five minutes apart. No background process is installed.
python3 -m research_agent watch --cycles 2 --interval 300
```

The daily brief includes up to 20 new or changed records, with total/shown counts. It writes local `.md` and `.json` files. Re-running a day replaces that day's two report files. Citation hashes identify the exact indexed version; older full versions are not archived.

## Opt-in real research

Only the official HTTPS **arXiv API** is supported. Generic URL crawling, PDF downloading, private email, and folder scanning are intentionally absent.

1. Copy `examples/sources.json` to an untracked local location such as `data/sources.json`.
2. Review the query and limits, then change its `enabled` value to `true`.
3. Use a separate database so synthetic fixtures do not mix with real papers:

```bash
python3 -m research_agent --db data/live.sqlite3 ingest \
  --config data/sources.json --allow-network
python3 -m research_agent --db data/live.sqlite3 serve
```

This transmits the configured public research query to arXiv. **Do not put confidential project details or personal information into source queries.** The dashboard itself cannot enable sources or make source requests. Respect arXiv's [API guidance](https://info.arxiv.org/help/api/user-manual.html) and [terms](https://info.arxiv.org/help/api/tou.html). Source content remains subject to its original rights; this repository redistributes no real papers.

A reviewed local JSON file can be imported using the schema in `research_agent/fixtures/papers.json`:

```bash
python3 -m research_agent ingest --file path/to/reviewed-papers.json
```

There is no automatic monitoring until you explicitly run `watch`. See [scheduling](docs/SCHEDULING.md) for a finite live run and optional user-installed daily scheduling.

## Optional local model

The default uses **no model and no embeddings**, making it comfortable to start on an 8 GB laptop. If you already have a trusted Ollama runtime and a small local model installed:

```bash
python3 -m research_agent ask "How can local inference preserve evidence?" \
  --local-model qwen2.5:1.5b
```

This contacts only `http://127.0.0.1:11434`, disables proxies and redirects, sets a 2,048-token context, requests at most 128 output tokens, and unloads the model after the call. Choose a genuinely local, small quantized model; do not use a cloud-backed model or a runtime that forwards requests. The optional runtime is a separate trust boundary. Model availability, performance, and memory use depend on your installation and have **not** been measured by this project. See [architecture](docs/ARCHITECTURE.md).

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 -m research_agent demo
python3 -m research_agent evaluate
python3 -m compileall -q research_agent tests
node --check research_agent/static/app.js  # optional JS syntax check
```

An optional Playwright script exercises browser navigation, evidence, abstention, filtering, cancellation, history, downloads, XSS text rendering, and mobile layout:

```bash
# Requires an independently installed Playwright + Chromium; app runtime does not.
python3 tests/browser_smoke.py --url http://127.0.0.1:8765 --chromium /path/to/chromium
```

See [verification](docs/VERIFICATION.md) for what was actually tested and what remains unverified.

## Limits and privacy

This is a portfolio-quality starting point, **not an autonomous scientist or production search service**. It reads abstracts, not full papers; lexical overlap can miss synonyms and can retrieve irrelevant text. Exact quotations prove provenance, not truth. Contradictions, methodology, causality, novelty, and scientific quality are not adjudicated.

The server binds only to loopback and has no authentication. Do not expose it through a public tunnel or reverse proxy. Local databases and reports are not encrypted. Questions are not logged or saved by this application; optional runtimes and your browser have their own retention behavior. There are no email, Slack, publishing, payment, or arbitrary shell-execution tools. [Security model →](docs/SECURITY.md)

**License:** MIT for project code and synthetic fixtures. Third-party sources and optional model weights keep their own licenses.
