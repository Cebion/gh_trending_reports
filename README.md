# gh_trending_reports

Weekly crawler that scouts GitHub for new PortMaster porting candidates
(open source games, SDL1/SDL2 games or ports, game engine reimplementations,
decompilation projects, reverse-engineering-of-games projects, emulators)
and publishes a report to GitHub Pages.

## How it works

- `run.py` orchestrates: **discover** new candidates via the GitHub Search
  API -> **recheck** previously tracked repos' star counts/activity ->
  **classify** every new candidate with an LLM (Gemini) to separate real
  candidates from noise (tutorials, unrelated tools, trivial clones) ->
  **promote** any tracked repo whose stars grew enough since it was last
  shown ("Rising") -> **render** the report -> save state.
- `data/watchlist.json` is the persistent record of every repo ever seen,
  its star history, and its classification. It's committed to `main` every
  run so good-but-obscure repos can resurface later if they gain traction,
  instead of only having a ~10-day window after creation to ever be seen.
- `build/index.html` is the generated report, published to `gh-pages`.

## Required secrets

- `GH_TOKEN` — GitHub token with repo read access (for the Search/Contents
  APIs) and push access to this repo (to commit the updated watchlist).
- `GEMINI_API_KEY` — Google AI Studio API key (free tier), used for
  candidate classification.

## Running locally

```
pip install -r requirements.txt
GH_TOKEN=... GEMINI_API_KEY=... python run.py
```

Then open `build/index.html`.
