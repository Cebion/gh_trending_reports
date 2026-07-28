#!/usr/bin/env python3
"""Orchestrator entrypoint: discovery -> recheck -> classify -> promotion ->
render -> save state.

Usage: python run.py
Env: GH_TOKEN (required), GEMINI_API_KEY (required)
"""

import os
import sys
from datetime import datetime, timezone

from crawler import classify, config, discovery, github_api, promotion, recheck, render, state as state_mod


def main():
    gh_token = os.getenv("GH_TOKEN")
    gemini_api_key = os.getenv("GEMINI_API_KEY")

    if not gh_token:
        print("GH_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    if not gemini_api_key:
        print("GEMINI_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today_str = now_iso[:10]

    client = github_api.GitHubClient(gh_token)
    watchlist = state_mod.load_state()

    print("[run] discovering new candidate repos...")
    new_records = discovery.discover_new_repos(client, watchlist, now_iso=now_iso)
    new_ids = {str(r["id"]) for r in new_records}
    print(f"[run] found {len(new_records)} brand-new candidates")

    print("[run] rechecking previously tracked repos...")
    rechecked = recheck.recheck_tracked_repos(client, watchlist, new_ids, now_iso=now_iso)
    print(f"[run] rechecked {len(rechecked)} tracked repos")

    for record in new_records:
        state_mod.upsert_repo(watchlist, record["id"], record)

    # Repos left "pending" by a previous run (classifier outage, bad model
    # name, etc) must be retried every run -- otherwise a transient failure
    # permanently strands them, since discovery never re-returns an
    # already-tracked repo as "new".
    still_pending = state_mod.pending_records(watchlist, exclude_ids=new_ids)
    if still_pending:
        print(f"[run] retrying {len(still_pending)} previously-pending classifications...")

    to_classify = new_records + still_pending
    classify_ids = {str(r["id"]) for r in to_classify}

    print(f"[run] classifying {len(to_classify)} candidates...")
    classify.classify_new_repos(gemini_api_key, client, to_classify)

    print("[run] computing new/rising surfacing...")
    # classify_ids (not just new_ids) get the "New this week" treatment: a
    # repo resolved from pending is appearing in the visible report for the
    # first time just now, even though it was originally discovered earlier.
    promotion.mark_new_surfaced(watchlist, classify_ids, today_str)
    promoted = promotion.compute_promotions(watchlist, classify_ids, today_str)
    print(f"[run] promoted {len(promoted)} repos to 'Rising'")

    watchlist["last_run"] = now_iso
    state_mod.save_state(watchlist)

    print("[run] rendering report...")
    render.render_report(watchlist, today_str)

    print("[run] done")


if __name__ == "__main__":
    main()
