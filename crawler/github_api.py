"""Thin GitHub REST API client: search with pagination, fetch-by-id (for
rename-safe rechecking), README fetch, and shared rate-limit/backoff
handling. The original script had none of this -- a single non-200 response
just got skipped silently.
"""

import base64
import time

import requests

from . import config

API_ROOT = "https://api.github.com"


class GitHubClient:
    def __init__(self, token, session=None):
        self.token = token
        self.session = session or requests.Session()
        # Tracked per rate-limit bucket -- GitHub's core (5000/hr) and search
        # (30/min) resources are independent, and a response's rate-limit
        # headers only ever describe the bucket the endpoint it hit belongs
        # to. Conflating them into one counter previously meant a nearly-
        # exhausted *search* reading (normal after a few queries) got
        # misread as the *core* budget being low, triggering pointless
        # multi-second sleeps before unrelated core-endpoint calls.
        self._remaining = {"core": None, "search": None}
        self._reset = {"core": None, "search": None}

    def _headers(self, accept="application/vnd.github.v3+json"):
        headers = {"Accept": accept}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    def _sleep_if_budget_low(self, resource):
        remaining = self._remaining.get(resource)
        reset = self._reset.get(resource)
        buffer = (
            config.SEARCH_RATE_LIMIT_REMAINING_BUFFER
            if resource == "search"
            else config.RATE_LIMIT_REMAINING_BUFFER
        )
        if remaining is not None and remaining < buffer:
            wait = max(0, (reset or 0) - time.time()) + 1
            if wait > 0:
                print(f"[github_api] {resource} rate limit low ({remaining} left), sleeping {wait:.0f}s")
                time.sleep(wait)

    def _track_rate_limit(self, response, resource):
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining is not None and reset is not None:
            try:
                self._remaining[resource] = int(remaining)
                self._reset[resource] = int(reset)
            except ValueError:
                pass

    def _request(self, method, url, params=None, accept=None, allow_404=False, resource="core"):
        """Issue a request with exponential backoff on 403/429/5xx, honoring
        Retry-After when present. Returns the Response, or None on a 404
        when allow_404=True. `resource` selects which rate-limit bucket
        ("core" or "search") this endpoint counts against."""
        self._sleep_if_budget_low(resource)
        headers = self._headers(accept) if accept else self._headers()

        last_exc = None
        for attempt in range(config.MAX_RETRIES + 1):
            try:
                response = self.session.request(method, url, headers=headers, params=params, timeout=30)
            except requests.RequestException as exc:
                last_exc = exc
                delay = config.BACKOFF_BASE_SECONDS * (2 ** attempt)
                print(f"[github_api] request error ({exc}), retrying in {delay}s")
                time.sleep(delay)
                continue

            self._track_rate_limit(response, resource)

            if response.status_code == 404 and allow_404:
                return None

            if response.status_code in (403, 429) or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    delay = float(retry_after)
                else:
                    delay = config.BACKOFF_BASE_SECONDS * (2 ** attempt)
                print(
                    f"[github_api] {response.status_code} on {url}, "
                    f"retrying in {delay}s (attempt {attempt + 1}/{config.MAX_RETRIES})"
                )
                time.sleep(delay)
                continue

            return response

        if last_exc:
            raise last_exc
        return response  # last (failing) response after exhausting retries

    def search_repositories(self, query, extra_qualifiers, cutoff_date):
        """Yield repo dicts for one search query, walking pagination up to
        GitHub's 1000-result cap. Logs a warning if the cap is hit (signal
        that the query has become too broad and should be narrowed)."""
        full_query = f"{query} {extra_qualifiers} created:>{cutoff_date}"
        page = 1
        total_seen = 0

        while True:
            params = {
                "q": full_query,
                "sort": "stars",
                "order": "desc",
                "per_page": config.PER_PAGE,
                "page": page,
            }
            response = self._request(
                "GET", f"{API_ROOT}/search/repositories", params=params, resource="search"
            )

            if response is None or response.status_code != 200:
                status = response.status_code if response is not None else "no response"
                print(f"[github_api] search failed for query {full_query!r}: {status}")
                return

            data = response.json()
            items = data.get("items")
            if items is None:
                print(f"[github_api] unexpected search response for {full_query!r}: {data}")
                return

            for repo in items:
                yield repo
            total_seen += len(items)

            if len(items) < config.PER_PAGE:
                break
            if total_seen >= config.SEARCH_RESULT_CAP:
                print(f"[github_api] query hit the {config.SEARCH_RESULT_CAP}-result cap: {full_query!r}")
                break

            page += 1
            time.sleep(config.SEARCH_QUERY_DELAY_SECONDS)

    def get_repo_by_id(self, repo_id):
        """Fetch a repo by its stable numeric id. Unlike GET /repos/{owner}/{repo},
        this survives renames/transfers -- the response's full_name reflects
        the repo's current name. Returns None on 404 (deleted or no longer
        visible to this token)."""
        response = self._request("GET", f"{API_ROOT}/repositories/{repo_id}", allow_404=True)
        if response is None:
            return None
        if response.status_code != 200:
            print(f"[github_api] unexpected status fetching repo id {repo_id}: {response.status_code}")
            return None
        return response.json()

    def get_readme_excerpt(self, full_name, max_chars=None):
        """Fetch the repo's README as raw text, truncated. Returns "" if
        there is no README or it can't be fetched."""
        max_chars = max_chars or config.README_EXCERPT_CHARS
        response = self._request(
            "GET",
            f"{API_ROOT}/repos/{full_name}/readme",
            accept="application/vnd.github.raw+json",
            allow_404=True,
        )
        if response is None or response.status_code != 200:
            return ""

        content_type = response.headers.get("Content-Type", "")
        if "application/vnd.github.raw" in content_type or content_type.startswith("text/"):
            text = response.text
        else:
            # Fell back to the JSON representation (base64-encoded content).
            try:
                data = response.json()
                text = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            except (ValueError, KeyError):
                return ""

        return text[:max_chars]
