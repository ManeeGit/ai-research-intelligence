"""Opt-in finite foreground watcher. There is no background daemon installer."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .briefs import daily_brief, write_brief
from .sources import FIXTURES, ingest_sources, load_fixture
from .store import Store


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ValueError("A watcher lock already exists; stop the other watcher or inspect a stale lock manually") from error
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def watch(database: str | Path, output: str | Path, *, cycles: int = 1,
          interval: float = 900, config: str | Path | None = None,
          allow_network: bool = False, fixture: str | Path = FIXTURES,
          sleep: Callable[[float], None] = time.sleep,
          emit: Callable[[dict], None] = lambda value: None) -> list[dict]:
    if type(cycles) is not int or not 1 <= cycles <= 24:
        raise ValueError("Watch cycles must be between 1 and 24")
    if not 300 <= interval <= 86400:
        raise ValueError("Watch interval must be between 300 and 86400 seconds")
    if (cycles - 1) * interval > 86400:
        raise ValueError("A watcher run may span at most 24 hours of waits")
    if config is not None and not allow_network:
        raise ValueError("Live watching requires explicit --allow-network")
    if config is None and allow_network:
        raise ValueError("--allow-network requires a reviewed source config")
    database = Path(database).resolve()
    reports = []
    with exclusive_lock(database.with_suffix(database.suffix + ".watch.lock")):
        for cycle in range(cycles):
            # Any failure stops this run. Request quota is persistent, not reset on retries.
            with Store(database) as store:
                if config:
                    ingested = ingest_sources(store, config, allow_network=True)
                else:
                    ingested = [store.ingest(load_fixture(fixture), "offline-fixture")]
                brief = daily_brief(store)
                paths = write_brief(brief, output)
            event = {"cycle": cycle + 1, "cycles": cycles, "ingestion": ingested,
                     "brief": str(paths[0]), "network": bool(config)}
            reports.append(event)
            emit(event)
            if cycle + 1 < cycles:
                sleep(interval)
    return reports
