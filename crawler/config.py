"""Central configuration/constants for the crawler pipeline."""

import os

# --- Paths -------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(REPO_ROOT, "data", "watchlist.json")
TEMPLATE_DIR = os.path.join(REPO_ROOT, "templates")
TEMPLATE_NAME = "report.html.jinja2"
BUILD_DIR = os.path.join(REPO_ROOT, "build")
BUILD_INDEX_PATH = os.path.join(BUILD_DIR, "index.html")

# --- Discovery -----------------------------------------------------------

# Real, single-slug GitHub topics only. `topic:love` is deliberately excluded:
# it matches the literal English word "love" on unrelated (romance/dating) repos,
# not just the LOVE/LOEVE game framework, which is already covered by
# topic:love2d / topic:löve.
TOPIC_QUERIES = [
    "topic:love2d",
    "topic:löve",
    "topic:sdl",
    "topic:sdl2",
    "topic:sdl1",
    "topic:decompilation",
    "topic:reverse-engineering",
    "topic:game-engine",
    "topic:emulator",
    "topic:emulation",
    "topic:libretro",
    "topic:retroarch",
    "topic:game-port",
]

# Free-text phrase queries using GitHub's in:description,readme qualifier.
# These catch relevant repos that never tagged a matching topic. They are
# intentionally broader/noisier than the topic queries above -- the LLM
# classification pass (not string matching) is the real relevance filter.
KEYWORD_QUERIES = [
    '"sdl2 port" in:description,readme',
    '"sdl port" in:description,readme',
    '"game engine" reimplementation in:description,readme',
    '"decompiled" game in:description,readme',
    '"reverse engineered" game in:description,readme',
    "libretro core in:description,readme",
]

ALL_QUERIES = TOPIC_QUERIES + KEYWORD_QUERIES

# Common qualifiers appended to every query.
COMMON_QUALIFIERS = "fork:false archived:false"

# Lookback window for `created:>` on a weekly cron. Longer than the 7-day
# cadence on purpose: cheap safety margin against a missed/failed run, since
# dedup happens by numeric repo id against the state file (a repeat hit just
# gets skipped, not re-classified).
LOOKBACK_DAYS = 10

# Delay between search API calls (separate ~30 req/min bucket from the core
# API's 5000/hr).
SEARCH_QUERY_DELAY_SECONDS = 2.5

# GitHub search API result cap per query (used only to detect/warn when a
# query has become too broad).
SEARCH_RESULT_CAP = 1000

PER_PAGE = 100

# --- Rechecking tracked repos --------------------------------------------

# Once the watchlist is large, repos in these states are only rechecked this
# often instead of every week, to keep the recheck pass within API budget.
RECHECK_INACTIVE_STATUSES = {"archived", "deleted_or_private"}
RECHECK_INACTIVE_INTERVAL_DAYS = 28

# --- LLM classification (Gemini) -----------------------------------------

# Google retires/renames Gemini model ids periodically (gemini-2.5-flash-lite
# was cut off for new API keys on 2026-07-22, with no stable "-latest" alias
# to fall back on). If classification starts failing with a 404 mentioning
# the model name, check https://ai.google.dev/gemini-api/docs/models for the
# current GA flash-lite-tier model and update this constant.
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
CLASSIFY_BATCH_SIZE = 12
CLASSIFY_BATCH_DELAY_SECONDS = 3
README_EXCERPT_CHARS = 1500
CLASSIFIER_SCHEMA_VERSION = 1

# Display thresholds.
RELEVANT_CONFIDENCE_THRESHOLD = 0.5
BORDERLINE_CONFIDENCE_THRESHOLD = 0.3

CLASSIFIER_SYSTEM_PROMPT = """\
You are screening GitHub repositories as candidates for porting to \
PortMaster, a game-launcher/CFW for retro handheld devices.

Relevant = open source games, SDL1/SDL2 games or ports, game engine \
reimplementations, decompilation projects, reverse-engineering-of-games \
projects, emulators.

NOT relevant = student first-programming exercises, generic security/\
hacking tools unrelated to games, tutorials, unrelated web/app projects, \
trivial "yet another pong/snake clone" toy projects with no real \
engineering substance.

For each repo in the input array, return a verdict. Respond ONLY with a \
JSON array matching the required schema, one object per input repo, each \
explicitly keyed by "full_name" (do not rely on array order).
"""

CLASSIFIER_RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "full_name": {"type": "STRING"},
            "relevant": {"type": "BOOLEAN"},
            "confidence": {"type": "NUMBER"},
            "category": {
                "type": "STRING",
                "enum": [
                    "sdl_port",
                    "love2d_game",
                    "game_engine_reimplementation",
                    "decompilation",
                    "reverse_engineering",
                    "emulator",
                    "other_game",
                    "noise",
                ],
            },
            "reason": {"type": "STRING"},
        },
        "required": ["full_name", "relevant", "confidence", "category", "reason"],
    },
}

# --- Rising/promotion thresholds -----------------------------------------

# A repo is promoted to "Rising" once its stars have grown past its last
# surfaced baseline by both an absolute floor AND (a relative jump OR a big
# absolute jump). The baseline resets to the current star count every time a
# repo is surfaced (as New or as Rising), which is what stops a slow steady
# linear grower from re-qualifying every single week.
RISING_ABS_MIN_DELTA = 10
RISING_GROWTH_RATIO_THRESHOLD = 1.5
RISING_ABS_HIGH_DELTA = 50

# --- Retry/backoff ---------------------------------------------------------

MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 2

# Separate buffers per GitHub rate-limit bucket -- core (5000/hr) and search
# (30/min) are tracked independently since conflating them (treating a
# near-exhausted search-bucket reading as if it were the core budget, or
# vice versa) causes spurious multi-second sleeps on the wrong endpoint.
RATE_LIMIT_REMAINING_BUFFER = 50
SEARCH_RATE_LIMIT_REMAINING_BUFFER = 2
