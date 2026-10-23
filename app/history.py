"""
Run history: one record per Android translation run / iOS add, persisted in
run_history.json next to config.json, so a run that was interrupted (app
closed, crash, Sheet upload failed) can be resumed or retried later.

A record is written with status "running" the moment a run starts. Anything
still "running" when the app next launches can't be alive any more, so
mark_stale_running() flips it to "interrupted".
"""

import json
import os
import threading
import time
import uuid

import config

MAX_RUNS = 100
_lock = threading.Lock()


def _path():
    return os.path.join(config.get_config_dir(), "run_history.json")


def _load():
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(runs):
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(runs[-MAX_RUNS:], f, indent=2)


def start_run(record):
    """Stores a new run as status 'running' and returns its id."""
    run = dict(record)
    run["id"] = uuid.uuid4().hex[:12]
    run["started"] = time.time()
    run["finished"] = None
    run["status"] = "running"
    with _lock:
        runs = _load()
        runs.append(run)
        _save(runs)
    return run["id"]


def update_run(run_id, mutate):
    """Applies mutate(record) to the run under the lock and saves it."""
    with _lock:
        runs = _load()
        for run in runs:
            if run.get("id") == run_id:
                mutate(run)
                _save(runs)
                return


def finish_run(run_id, status, **fields):
    def _m(run):
        run["status"] = status
        run["finished"] = time.time()
        run.update(fields)
    update_run(run_id, _m)


def mark_stale_running():
    with _lock:
        runs = _load()
        changed = False
        for run in runs:
            if run.get("status") == "running":
                run["status"] = "interrupted"
                run["finished"] = run.get("finished") or time.time()
                changed = True
        if changed:
            _save(runs)


def list_runs():
    """Newest first."""
    with _lock:
        return list(reversed(_load()))


def delete_run(run_id):
    with _lock:
        _save([r for r in _load() if r.get("id") != run_id])


def clear_all():
    with _lock:
        _save([])
