"""Load/save the persistent watchlist state file (data/watchlist.json).

This file is the single source of truth across runs: every repo ever
discovered, its star history, its LLM classification, and when it was last
shown in the report. It is committed to `main` by the workflow and must
never be written into the `build/` output directory that gets published to
`gh-pages`.
"""

import json
import os
import tempfile

from . import config

SCHEMA_VERSION = 1


def new_state():
    return {"schema_version": SCHEMA_VERSION, "last_run": None, "repos": {}}


def load_state(path=None):
    path = path or config.STATE_PATH
    if not os.path.exists(path):
        return new_state()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("last_run", None)
    data.setdefault("repos", {})
    return data


def save_state(state, path=None):
    """Write the state file atomically so a killed job can't leave a
    half-written/corrupt watchlist behind."""
    path = path or config.STATE_PATH
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".watchlist-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def get_repo(state, repo_id):
    return state["repos"].get(str(repo_id))


def upsert_repo(state, repo_id, record):
    state["repos"][str(repo_id)] = record


def pending_records(state, exclude_ids=frozenset()):
    """Records with no classification yet, or a prior classification attempt
    that failed and fell back to pending. Excludes ids already handled
    elsewhere this run (e.g. brand-new discoveries, tracked separately) to
    avoid double-processing. These must be retried every run -- otherwise a
    transient classifier outage (bad model name, API downtime) permanently
    strands whatever was being discovered at the time."""
    return [
        record
        for repo_id, record in state["repos"].items()
        if repo_id not in exclude_ids
        and (record.get("classification") is None or record["classification"].get("relevant") is None)
    ]
