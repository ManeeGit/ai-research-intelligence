# Verification record

Verified on 2026-11-05 in a Linux cloud workspace with Python 3.12.14. No work was performed on a user's Mac.

## Passed

- **44 unit, integration, and security tests**, including synthetic retrieval, abstention, exact quote/hash/offset/URL verification, stale citation rejection, deduplication, changed records, concurrent corpus limits, daily briefs, persistent quotas, failed-request accounting, disabled-source behavior, finite scheduling, lock cleanup, XML entity/encoding defenses, pinned TLS hostname behavior, redirect rejection, malformed HTTP handling, local-model fallback, loopback HTTP APIs, Host/Origin checks, CSRF request requirements, and fixed static routes.
- **12/12 synthetic evaluation cases**, comprising 9 answerable questions and 3 deliberately unsupported questions. Recall at 3: 9/9; unsupported-question abstention: 3/3; emitted quote checks passed. These are small deterministic regression results, not real-world accuracy claims.
- Offline demo → SQLite ingestion → cited answer → daily Markdown/JSON brief → evaluation.
- Python bytecode compilation and JavaScript syntax check.
- Python wheel built successfully without runtime dependencies. Included fixture and frontend package assets were inspected, and the wheel's module entry point was exercised from a clean extraction.
- A focused read-only code review found and prompted fixes for malformed model JSON, non-UTF-8 XML entity declarations, concurrent capacity checks, and a navigation edge case. This is not a formal security certification.

A single Python process ingesting the 12-record demo, answering one question, and running the evaluation peaked at **15,744 KiB resident memory** on this Linux host. This is a fixture-scale observation only, excludes any browser/model, and is not a Mac performance benchmark or a worst-case bound.

## Not verified

- **Browser rendering and interaction QA.** A Playwright smoke test is included, but Chromium could not start because the cloud environment denied its process socket. The same issue remained after the permitted execution escalation. No screenshot or visual pass is claimed. Static frontend assets are served successfully; those HTTP checks do not prove browser behavior.
- **Live arXiv availability/integration.** Parsing, URL restrictions, TLS connection construction, redirects, budgets, and network-error behavior were tested offline with mocks. No live source request was made.
- **Actual Ollama inference.** Model responses and failure modes were mocked. No model was downloaded, run, or benchmarked.
- **macOS execution or an 8 GB Mac hardware benchmark.** Defaults were designed to avoid heavy models, but this build was tested on Linux only.
- **Remote CI, GitHub publication, deployment, or a daily scheduled run.** The workflow and scheduling instructions are provided; this build did not publish or schedule them.

## Reproduce

```bash
python3 -m unittest discover -s tests -v
python3 -m research_agent demo
python3 -m research_agent evaluate
python3 -m compileall -q research_agent tests
node --check research_agent/static/app.js
```

On a machine where a local Chromium is available, start `python3 -m research_agent serve`, then run the optional browser script described in the README. Its prerequisites are separate from the app's zero-dependency runtime.
