"""LLM classification of newly-discovered repos via the Gemini REST API
(plain requests, no SDK -- matches the project's existing minimalism).

Batches multiple repos per call to keep real request volume low (~10-25
calls/week for the ~100-300 candidates/week this pipeline expects), well
within Gemini's free tier. Failures degrade gracefully to a "pending"
classification rather than crashing the run -- a repo left pending is
simply retried next week since it's already tracked in the state file.
"""

import json
import time
from datetime import datetime, timezone

import requests

from . import config


class ClassificationError(Exception):
    """Recoverable classification failure (parse error, mismatched batch
    response, transient outage) -- worth retrying/splitting/falling back to
    pending on a per-repo basis."""


class FatalClassificationError(ClassificationError):
    """Non-retryable failure that will fail identically for every batch this
    run (bad API key, invalid/deprecated model name, etc). Retrying or
    splitting into smaller batches cannot help and only wastes hours -- this
    must abort the whole classification pass immediately instead of being
    rediscovered batch-by-batch."""


def _pending_classification():
    return {
        "relevant": None,
        "confidence": None,
        "category": None,
        "reason": "classification pending (Gemini call failed or was unparseable)",
        "model": config.GEMINI_MODEL,
        "classified_at": None,
        "classifier_schema_version": config.CLASSIFIER_SCHEMA_VERSION,
    }


def _build_input(record, readme_excerpt):
    stars = record["star_history"][-1]["stars"] if record["star_history"] else 0
    return {
        "full_name": record["full_name"],
        "description": record["description"],
        "topics": record.get("topics", []),
        "primary_language": record.get("primary_language"),
        "stars": stars,
        "readme_excerpt": readme_excerpt,
    }


def _call_gemini(api_key, batch_inputs, session):
    url = config.GEMINI_API_URL.format(model=config.GEMINI_MODEL)
    body = {
        "system_instruction": {"parts": [{"text": config.CLASSIFIER_SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": json.dumps(batch_inputs)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": config.CLASSIFIER_RESPONSE_SCHEMA,
        },
    }

    last_exc = None
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            response = session.post(
                url,
                params={"key": api_key},
                json=body,
                timeout=60,
            )
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(config.BACKOFF_BASE_SECONDS * (2 ** attempt))
            continue

        # 401/403/404 mean the API key or model name itself is bad -- the
        # exact same request will fail the exact same way on every retry and
        # every other batch this run, so fail fast instead of retrying.
        if response.status_code in (401, 403, 404):
            raise FatalClassificationError(
                f"Gemini call failed with a non-retryable error -- check GEMINI_API_KEY and "
                f"whether model {config.GEMINI_MODEL!r} still exists: "
                f"{response.status_code} {response.text[:300]}"
            )

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else config.BACKOFF_BASE_SECONDS * (2 ** attempt)
            print(f"[classify] Gemini {response.status_code}, retrying in {delay}s")
            time.sleep(delay)
            continue

        if response.status_code != 200:
            raise ClassificationError(f"Gemini call failed: {response.status_code} {response.text[:300]}")

        return response.json()

    raise ClassificationError(f"Gemini call failed after retries: {last_exc}")


def _parse_response(payload, expected_names):
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        verdicts = json.loads(text)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ClassificationError(f"could not parse Gemini response: {exc}")

    if not isinstance(verdicts, list):
        raise ClassificationError("Gemini response was not a JSON array")

    by_name = {}
    for verdict in verdicts:
        if not isinstance(verdict, dict) or "full_name" not in verdict:
            raise ClassificationError(f"malformed verdict entry: {verdict!r}")
        by_name[verdict["full_name"]] = verdict

    missing = expected_names - set(by_name.keys())
    if missing:
        raise ClassificationError(f"Gemini response missing verdicts for: {missing}")

    return by_name


def _classify_batch(api_key, records_with_readmes, session, allow_split=True):
    """records_with_readmes: list of (record, readme_excerpt) tuples.
    Returns {full_name: verdict_dict}. Never raises -- unclassifiable repos
    are simply absent from the returned dict, and the caller fills those in
    with a pending classification."""
    if not records_with_readmes:
        return {}

    batch_inputs = [_build_input(record, readme) for record, readme in records_with_readmes]
    expected_names = {record["full_name"] for record, _ in records_with_readmes}

    try:
        payload = _call_gemini(api_key, batch_inputs, session)
        return _parse_response(payload, expected_names)
    except FatalClassificationError:
        raise  # not batch-content-specific -- splitting/retrying won't help, let it propagate
    except ClassificationError as exc:
        print(f"[classify] batch of {len(records_with_readmes)} failed: {exc}")

        if allow_split and len(records_with_readmes) > 1:
            mid = len(records_with_readmes) // 2
            left = _classify_batch(api_key, records_with_readmes[:mid], session, allow_split=False)
            right = _classify_batch(api_key, records_with_readmes[mid:], session, allow_split=False)
            return {**left, **right}

        return {}


def classify_new_repos(api_key, github_client, records):
    """records: list of newly-discovered watchlist records (dicts), mutated
    in place -- each gets a `classification` dict, either a real verdict or
    a pending placeholder."""
    if not records:
        return

    session = requests.Session()
    now_iso = datetime.now(timezone.utc).isoformat()

    records_with_readmes = [
        (record, github_client.get_readme_excerpt(record["full_name"]))
        for record in records
    ]

    verdicts_by_name = {}
    for i in range(0, len(records_with_readmes), config.CLASSIFY_BATCH_SIZE):
        batch = records_with_readmes[i : i + config.CLASSIFY_BATCH_SIZE]
        try:
            verdicts_by_name.update(_classify_batch(api_key, batch, session))
        except FatalClassificationError as exc:
            # This will fail identically for every remaining batch (bad key,
            # dead model, ...) -- stop immediately rather than rediscovering
            # the same fatal error dozens of times over. Everything not yet
            # classified falls back to "pending" below and gets retried next
            # run once the underlying config issue is fixed.
            print(f"[classify] {exc}")
            print(
                f"[classify] aborting classification for this run -- "
                f"{len(records) - len(verdicts_by_name)} repos left pending"
            )
            break
        if i + config.CLASSIFY_BATCH_SIZE < len(records_with_readmes):
            time.sleep(config.CLASSIFY_BATCH_DELAY_SECONDS)

    for record in records:
        verdict = verdicts_by_name.get(record["full_name"])
        if verdict is None:
            record["classification"] = _pending_classification()
            continue

        record["classification"] = {
            "relevant": bool(verdict.get("relevant")),
            "confidence": float(verdict.get("confidence", 0)),
            "category": verdict.get("category"),
            "reason": verdict.get("reason", ""),
            "model": config.GEMINI_MODEL,
            "classified_at": now_iso,
            "classifier_schema_version": config.CLASSIFIER_SCHEMA_VERSION,
        }
