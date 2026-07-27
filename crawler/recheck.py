"""Recheck: refresh already-tracked repos' current star count, fork/archived
status, and last-push recency. Uses GET /repositories/{id} so renames and
transfers are picked up transparently instead of 404ing like a
GET /repos/{owner}/{repo} lookup would after a rename.
"""

from datetime import datetime, timezone

from . import config


def _due_for_recheck(record, today):
    """Skip the weekly recheck for long-inactive records once the watchlist
    is large enough that this matters -- keeps the recheck pass within API
    budget. New/active records are always rechecked."""
    if record["status"] not in config.RECHECK_INACTIVE_STATUSES:
        return True

    last_checked = record.get("last_checked")
    if not last_checked:
        return True

    last_checked_date = datetime.fromisoformat(last_checked.replace("Z", "+00:00")).date()
    return (today - last_checked_date).days >= config.RECHECK_INACTIVE_INTERVAL_DAYS


def recheck_tracked_repos(client, state, freshly_discovered_ids, now_iso=None):
    """Mutates state in place. Returns the list of repo ids that were
    actually rechecked this run (for logging/summary purposes)."""
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date()
    today_str = now_iso[:10]

    rechecked = []

    for repo_id, record in state["repos"].items():
        if repo_id in freshly_discovered_ids:
            continue  # just created this run, nothing to refresh yet
        if not _due_for_recheck(record, today):
            continue

        repo = client.get_repo_by_id(repo_id)
        rechecked.append(repo_id)

        if repo is None:
            record["status"] = "deleted_or_private"
            record["last_checked"] = now_iso
            continue

        if repo["full_name"] != record["full_name"]:
            record["renamed_from"] = record["full_name"]
            record["full_name"] = repo["full_name"]
            record["url"] = repo["html_url"]

        record["description"] = repo.get("description") or record["description"]
        record["primary_language"] = repo.get("language")
        record["topics"] = repo.get("topics", record.get("topics", []))
        record["forks"] = repo.get("forks_count", record["forks"])
        record["is_archived"] = repo.get("archived", False)
        record["pushed_at"] = repo.get("pushed_at")
        record["status"] = "archived" if record["is_archived"] else "active"
        record["last_checked"] = now_iso

        current_stars = repo.get("stargazers_count", 0)
        history = record["star_history"]
        if not history or history[-1]["date"] != today_str:
            history.append({"date": today_str, "stars": current_stars})
        else:
            history[-1]["stars"] = current_stars

    return rechecked
