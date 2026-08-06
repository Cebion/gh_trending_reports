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

# Bump this whenever CLASSIFIER_SYSTEM_PROMPT or CLASSIFIER_RESPONSE_SCHEMA
# changes meaningfully (new categories, tightened relevance rules, etc).
# state.pending_records() treats any stored classification whose
# classifier_schema_version is older than this as needing a fresh verdict,
# so a prompt refinement automatically re-judges the whole watchlist against
# the new rules on the next run -- no separate manual "reclassify" step to
# remember to run.
CLASSIFIER_SCHEMA_VERSION = 2

# Display thresholds.
RELEVANT_CONFIDENCE_THRESHOLD = 0.5
BORDERLINE_CONFIDENCE_THRESHOLD = 0.3

# Categories excluded from "relevant" regardless of what the classifier
# returned for `relevant` -- belt-and-suspenders against a model that
# ignores the system prompt's instruction, and lets already-classified
# repos in the watchlist get re-filtered on the next render without needing
# a fresh (costly) Gemini call. Each of these came from a real
# false-positive pattern found by reviewing early report output (fan
# translations, AI bots, decompilation *tools* vs. actual decompiled games,
# mods, web/WASM builds).
EXCLUDED_CATEGORIES = {"emulator", "mod", "tool", "web_port", "translation", "ai_bot"}

CLASSIFIER_SYSTEM_PROMPT = """\
You are screening GitHub repositories as candidates for porting to \
PortMaster, a game-launcher/CFW for retro handheld devices. A PortMaster \
port is a complete, playable game that runs natively on the handheld \
(SDL1/SDL2, native Linux binary) -- not a developer tool, not a web build, \
not an add-on for something else.

Relevant = a complete, playable game that is one of:
- An SDL1/SDL2 game, or a port of an existing game to SDL1/SDL2
- A LOVE2D game -- a finished, playable game built with LOVE, not a \
generic engine/framework/tech-demo that merely uses LOVE
- A reimplementation of a SPECIFIC existing/known game's engine (e.g. a \
from-scratch engine that runs a named classic/commercial game's original \
assets), producing something playable -- NOT a generic new engine meant \
for arbitrary future games
- A decompilation of a specific existing game that produces a playable, \
runnable build of that game
- The playable, runnable output of reverse-engineering a specific \
existing game

NOT relevant, even when otherwise well-engineered or game-adjacent -- \
still classify these (do not just guess "noise"), so they can be audited \
separately rather than silently conflated:
- Emulators/emulation cores -> category "emulator" (out of scope by \
explicit user preference)
- Mods, content packs, multiplayer patches, or cosmetic add-ons for an \
existing game or for another reimplementation project -- even an \
excellent mod for an otherwise-relevant base project is not itself a port \
candidate -> category "mod"
- Developer tools/toolkits/utilities: decompilers, asset/code extractors, \
file inspectors or patchers, installers/packagers, format converters -- \
anything that helps someone else produce, analyze, or install a game, \
rather than being the playable game itself -> category "tool"
- Web/browser builds: Emscripten/WASM/JS-targeted ports -- PortMaster runs \
native Linux/SDL2 binaries on handheld hardware, not a browser runtime \
-> category "web_port"
- Fan translations or localization-only patches of an existing game, with \
no other engineering substance -> category "translation"
- AI bots, solvers, or algorithm demos that play a game (e.g. a \
Tetris-playing AI) rather than being a playable game themselves \
-> category "ai_bot"
- Generic/custom game engines, frameworks, raycasters, procedural \
generators, voxel engines, or other reusable tech that is not itself a \
complete, specific, playable game -> category "noise"
- Student first-programming exercises, generic security/hacking tools \
unrelated to games, tutorials, unrelated web/app projects, trivial \
"yet another pong/snake clone" toy projects with no real engineering \
substance -> category "noise"

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
                    "other_game",
                    # Not relevant, but broken out from generic "noise" so the
                    # excluded-repos audit table shows *why* at a glance --
                    # each of these came from a real false-positive pattern
                    # found by reviewing early report output.
                    "emulator",
                    "mod",
                    "tool",
                    "web_port",
                    "translation",
                    "ai_bot",
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
