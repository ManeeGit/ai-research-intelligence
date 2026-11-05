# Bounded monitoring

Nothing in installation or `demo` enables a scheduler. The program does not install a background daemon, modify launch agents, or create remote automations.

## Foreground run

```bash
# Offline demo, one cycle by default.
python3 -m research_agent watch

# Reviewed source config, up to eight cycles spaced one hour apart.
python3 -m research_agent --db data/live.sqlite3 watch \
  --config data/sources.json --allow-network --cycles 8 --interval 3600
```

Press Ctrl-C to cancel. Each successful cycle ingests the configured queries and writes that UTC day's local brief. An error stops the run immediately; no automatic infinite retries occur. Failed network calls count against the daily source budget.

A watcher lock lives next to the database. If a process is forcibly killed and leaves a stale lock, verify there is no active watcher for that database, then remove only that lock yourself. Do not delete locks just because another run is busy.

The polling limit is 24 cycles, intervals of at least five minutes, and no more than 24 hours of scheduled waits per invocation. Network operation time is additional. Normal arXiv work should use much lower frequency, such as once per day.

## Optional daily scheduling

If you want ongoing daily work on your own machine, use your OS scheduler to run **one cycle** each day. This repository includes no installer and has not installed anything for you. Review the command, source data disclosure, file permissions, working directory, and output retention first.

For example, a user-managed cron entry could invoke an existing virtual environment with absolute paths:

```cron
0 9 * * * cd /absolute/path/to/ai-research-intelligence && /absolute/path/to/.venv/bin/python -m research_agent --db data/live.sqlite3 watch --config data/sources.json --allow-network --cycles 1 --out reports
```

This is documentation, not a command executed by the project. Cron uses the scheduler machine's timezone, while brief dates and request budgets use UTC. Laptop sleep or shutdown prevents runs; nothing can monitor while the machine is off. A cloud host needs its own reviewed setup and security controls. There is no automatic email or notification delivery.
