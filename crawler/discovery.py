"""Discovery: run all configured search queries, dedupe against the state
file by numeric repo id, and turn brand-new hits into fresh watchlist
records (not yet classified).
"""

import time
from datetime import datetime, timedelta, timezone

from . import config


def _cutoff_date():
    return (datetime.now(timezone.utc) - timedelta(days=config.LOOKBACK_DAYS)).strftime("%Y-%m-%d")


def _new_record(repo, source_query, now_iso):
    return {
        "id": repo["id"],
        "full_name": repo["full_name"],
        "url": repo["html_url"],
        "description": repo.get("description") or "",
        "primary_language": repo.get("language"),
        "topics": repo.get("topics", []),
        "created_at": repo.get("created_at"),
        "first_seen": now_iso,
        "last_checked": now_iso,
        "discovery_source": [source_query],
        "star_history": [
            {"date": now_iso[:10], "stars": repo.get("stargazers_count", 0)}
        ],
        "forks": repo.get("forks_count", 0),
        "is_fork": repo.get("fork", False),
        "is_archived": repo.get("archived", False),
        "pushed_at": repo.get("pushed_at"),
        "status": "active",
        "renamed_from": None,
        "classification": None,
        "surfaced": {
            "new_reported_at": None,
            "last_rising_reported_at": None,
            "last_rising_delta": None,
            "last_rising_growth_pct": None,
            "rising_baseline_stars": repo.get("stargazers_count", 0),
            "rising_baseline_date": now_iso[:10],
        },
    }


def discover_new_repos(client, state, now_iso=None):
    """Run every configured query and return a list of brand-new repo
    records (repo ids not already present in `state`). Repos already
    tracked are skipped here entirely -- they're refreshed by recheck.py
    instead, not re-discovered/re-classified."""
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    cutoff = _cutoff_date()

    new_records = {}  # keyed by id, so a repo hit by multiple queries is merged once
    known_ids = set(state["repos"].keys())

    for query in config.ALL_QUERIES:
        for repo in client.search_repositories(query, config.COMMON_QUALIFIERS, cutoff):
            repo_id = str(repo["id"])
            if repo_id in known_ids:
                continue

            if repo_id in new_records:
                sources = new_records[repo_id]["discovery_source"]
                if query not in sources:
                    sources.append(query)
                continue

            new_records[repo_id] = _new_record(repo, query, now_iso)

        time.sleep(config.SEARCH_QUERY_DELAY_SECONDS)

    return list(new_records.values())
