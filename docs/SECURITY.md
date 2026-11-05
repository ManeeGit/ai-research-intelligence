# Security and privacy

## Safe defaults

- Offline synthetic fixtures are the only default source.
- Live ingestion needs both an enabled config entry and an explicit network flag.
- Sources are fixed to `https://export.arxiv.org/api/query`; no generic fetcher or crawler exists.
- All resolved source addresses must be globally routable. The connection is pinned to a validated address and TLS still verifies the official hostname.
- Redirects and proxy environment variables are not used for source/model requests.
- Quotas are reserved before requests, including failed requests. arXiv queries are separated by at least three seconds within a run.
- Only bounded UTF-8 Atom XML is accepted; DOCTYPE/entities and unexpected roots/identifiers are rejected.
- SQLite writes use parameterized statements and an immediate transaction before checking corpus capacity.
- Source text is data, never instructions. No shell, messaging, payment, or deployment tools exist.
- Model output selects existing IDs only; unknown or malformed selections fall back.
- Browser source content is rendered using `textContent`, never inserted as HTML.
- Dashboard access requires a loopback Host and, if present, matching Origin. POST requires JSON and a custom header. CORS is not enabled. CSP prevents external scripts, frames, and connections.
- Source ingestion and model selection are CLI-only. The dashboard exposes neither capability.
- Watchers are finite, exclusive, foreground processes. Failure stops the current run and releases its lock.

## User responsibilities

Keep source queries public and non-sensitive: arXiv receives them when you enable ingestion. The application does not scan personal folders or contacts. Local JSON import means you are deliberately adding that file's contents to a plaintext local database and subsequent briefs.

Trust the optional Ollama runtime and use local model weights. Loopback transport is not proof that the other process never sends data externally. Do not use cloud-backed models. No credentials should be put in model names, source queries, titles, or abstracts.

Data at rest is not encrypted. Anyone with access to your local files can read the index and reports. Use ordinary OS permissions and disk encryption for your needs. Questions are not persisted or logged by this app, but terminal history, shell output, browser state, runtime logs, and OS diagnostics are outside its retention controls.

Do not expose the loopback server publicly, change its binding to a public interface, or place it behind a tunnel. It has no accounts or authorization system. It is a single-user development app.

## Limits

Citation checks establish that the quoted text appears in the indexed record. They do not authenticate the author, establish factual truth, validate experiments, or replace peer review. Metadata imported from a local file is not independently authenticated.

Rate limits are local safety budgets, not tamper-proof quotas. A user controlling the database/config can change or reset them. Locks require manual inspection after a process is forcibly killed; stale locks are never automatically overridden.

The program does not prevent another local process from editing files, racing with file writes, or impersonating a local model endpoint. It is not a sandbox for malicious local users.

## Reporting a problem

Describe the affected version, minimal reproduction, and expected behavior in a private report to the repository owner. Do not include credentials, private datasets, or confidential queries in public issues. No security contact email is invented by this project.
