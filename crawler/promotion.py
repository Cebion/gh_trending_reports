"""'Rising' resurfacing logic and the shared surfaced/baseline bookkeeping
used for both new and rising repos.

Anti-spam mechanism: the growth baseline resets to the current star count
every time a repo is surfaced (as New or as Rising). A repo with slow,
steady linear growth therefore can't re-qualify every single week -- it has
to post fresh growth past its *new* baseline, which naturally takes many
weeks for a slow grower to cross again.
"""

from . import config


def _is_relevant(record):
    classification = record.get("classification")
    return bool(classification) and classification.get("relevant") is True and (
        classification.get("confidence", 0) >= config.RELEVANT_CONFIDENCE_THRESHOLD
    )


def _current_stars(record):
    history = record.get("star_history") or []
    return history[-1]["stars"] if history else 0


def mark_new_surfaced(state, new_repo_ids, today_str):
    """Mark freshly-discovered, LLM-approved repos as surfaced this run so
    the renderer's 'New this week' section picks them up, and set their
    rising baseline to today's star count (the point growth is measured
    from going forward)."""
    for repo_id in new_repo_ids:
        record = state["repos"].get(str(repo_id))
        if record is None or not _is_relevant(record):
            continue

        record["surfaced"]["new_reported_at"] = today_str
        record["surfaced"]["rising_baseline_stars"] = _current_stars(record)
        record["surfaced"]["rising_baseline_date"] = today_str


def compute_promotions(state, freshly_discovered_ids, today_str):
    """Evaluate every previously-tracked, still-relevant, still-active repo
    for 'Rising' promotion. Mutates state in place (resets baseline, stamps
    last_rising_reported_at) and returns the list of promoted repo ids."""
    promoted = []

    for repo_id, record in state["repos"].items():
        if repo_id in freshly_discovered_ids:
            continue
        if record["status"] != "active":
            continue
        if not _is_relevant(record):
            continue

        baseline = record["surfaced"].get("rising_baseline_stars") or 0
        current = _current_stars(record)
        delta = current - baseline
        ratio = current / max(baseline, 1)

        should_promote = delta >= config.RISING_ABS_MIN_DELTA and (
            ratio >= config.RISING_GROWTH_RATIO_THRESHOLD
            or delta >= config.RISING_ABS_HIGH_DELTA
        )

        if should_promote:
            # Capture the delta/growth that *earned* the promotion before
            # resetting the baseline below -- otherwise the report would
            # always show "+0" since current == the freshly-reset baseline.
            record["surfaced"]["last_rising_delta"] = delta
            record["surfaced"]["last_rising_growth_pct"] = round((ratio - 1) * 100)
            record["surfaced"]["last_rising_reported_at"] = today_str
            record["surfaced"]["rising_baseline_stars"] = current
            record["surfaced"]["rising_baseline_date"] = today_str
            promoted.append(repo_id)

    return promoted
