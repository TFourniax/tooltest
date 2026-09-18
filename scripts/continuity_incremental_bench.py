"""Diagnostic append-one/materialize cost; synthetic seeding is outside timings."""
from __future__ import annotations

import argparse
import contextlib
import json
import platform
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from continuity_bench import _event, _repo
from diffwitness import continuity_events as journal, continuity_state as state


def logical_rows(path: Path) -> dict:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        names = [r[0] for r in conn.execute("select name from sqlite_master where type='table' order by name")]
        return {name: sorted(conn.execute('select * from "' + name + '"').fetchall(), key=repr) for name in names}


def run(size: int) -> dict:
    with tempfile.TemporaryDirectory(prefix='dw-incremental-bench-') as td:
        repo = _repo(Path(td))
        paths = journal.continuity_paths(repo)
        paths.root.mkdir(parents=True, exist_ok=True)
        previous = None
        # Fixture construction is NOT a product append measurement. Full strict
        # journal validation occurs in rebuild_state before measuring any update.
        with paths.events.open('wb') as handle:
            for index in range(size):
                event = journal._candidate_from_spec(_event(index, size))
                event['prev_hash'] = previous
                event['event_id'] = journal._event_id(event)
                event['event_hash'] = previous = journal._event_hash(event)
                handle.write((journal._canonical(event) + '\n').encode('utf-8'))
        state.rebuild_state(repo)
        samples = []
        for index in range(3):
            started = time.perf_counter()
            journal.append_project_events(repo=repo, events=[_event(size + index, size + index + 1)])
            append = time.perf_counter() - started
            projected = 0
            project = state._upsert_entity
            def observe(conn, event):
                nonlocal projected
                projected += 1
                return project(conn, event)
            with patch.object(state, '_upsert_entity', side_effect=observe):
                started = time.perf_counter()
                path = state.ensure_state(repo)
                materialize = time.perf_counter() - started
            samples.append(dict(append_one_seconds=round(append, 6), ensure_state_seconds=round(materialize, 6),
                                projected_events=projected))
        actual = logical_rows(path)
        rebuilt = logical_rows(state.rebuild_state(repo))
        if actual != rebuilt:
            raise RuntimeError('incremental/rebuild logical tables differ')
        return dict(events=size, samples=samples, rebuild_equivalent=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', nargs='+', type=int, default=[10000, 50000, 100000])
    parser.add_argument('--json', type=Path, required=True)
    args = parser.parse_args()
    if any(size < 1 for size in args.events):
        parser.error('event counts must be positive')
    result = dict(schema_version='continuity-incremental-diagnostic-1', python=platform.python_version(),
                  platform=platform.system(), fixture_setup_timed=False, results=[])
    for size in args.events:
        result['results'].append(run(size))
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result['results'][-1]), flush=True)


if __name__ == '__main__':
    main()
