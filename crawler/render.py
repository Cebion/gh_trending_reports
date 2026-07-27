"""Build the New / Rising / Archive / Excluded sections from state and
render the Jinja2 report template to build/index.html.
"""

import os

from jinja2 import Environment, FileSystemLoader

from . import config


def _current_stars(record):
    history = record.get("star_history") or []
    return history[-1]["stars"] if history else 0


def _is_pending(record):
    classification = record.get("classification")
    return classification is None or classification.get("relevant") is None


def _is_relevant(record):
    classification = record.get("classification")
    return bool(classification) and classification.get("relevant") is True and (
        classification.get("confidence", 0) >= config.RELEVANT_CONFIDENCE_THRESHOLD
    )


def _is_excluded(record):
    classification = record.get("classification")
    if classification is None or classification.get("relevant") is None:
        return False
    if classification.get("relevant") is False:
        return True
    # relevant=True but below the display confidence threshold ("borderline")
    return classification.get("confidence", 0) < config.RELEVANT_CONFIDENCE_THRESHOLD


def _view(record):
    """Flatten a state record into the fields the template needs."""
    classification = record.get("classification") or {}
    surfaced = record["surfaced"]
    current = _current_stars(record)
    return {
        "full_name": record["full_name"],
        "url": record["url"],
        "description": record["description"],
        "primary_language": record.get("primary_language"),
        "stars": current,
        # These reflect the growth that *earned* a "Rising" promotion this
        # run (captured by promotion.py before it resets the baseline) --
        # not a live recompute against the current (already-reset) baseline,
        # which would always show +0.
        "star_delta": surfaced.get("last_rising_delta") or 0,
        "growth_pct": surfaced.get("last_rising_growth_pct"),
        "created_at": record.get("created_at"),
        "first_seen": record.get("first_seen"),
        "last_rising_reported_at": surfaced.get("last_rising_reported_at"),
        "pushed_at": record.get("pushed_at"),
        "category": classification.get("category"),
        "confidence": classification.get("confidence"),
        "reason": classification.get("reason"),
    }


def build_sections(state, today_str):
    repos = state["repos"].values()

    new_repos = [r for r in repos if r["surfaced"].get("new_reported_at") == today_str]
    rising_repos = [
        r for r in repos if r["surfaced"].get("last_rising_reported_at") == today_str
    ]
    archive_repos = [r for r in repos if _is_relevant(r)]
    excluded_repos = [r for r in repos if _is_excluded(r)]
    pending_repos = [r for r in repos if _is_pending(r)]

    archive_repos.sort(key=_current_stars, reverse=True)
    new_repos.sort(key=_current_stars, reverse=True)
    rising_repos.sort(key=lambda r: _view(r)["star_delta"], reverse=True)

    return {
        "new": [_view(r) for r in new_repos],
        "rising": [_view(r) for r in rising_repos],
        "archive": [_view(r) for r in archive_repos],
        "excluded": [_view(r) for r in excluded_repos],
        "summary": {
            "new_count": len(new_repos),
            "rising_count": len(rising_repos),
            "tracked_relevant_count": len(archive_repos),
            "pending_count": len(pending_repos),
            "excluded_count": len(excluded_repos),
        },
    }


def render_report(state, today_str, output_path=None):
    output_path = output_path or config.BUILD_INDEX_PATH
    sections = build_sections(state, today_str)

    env = Environment(loader=FileSystemLoader(config.TEMPLATE_DIR))
    template = env.get_template(config.TEMPLATE_NAME)
    html = template.render(run_date=today_str, **sections)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
