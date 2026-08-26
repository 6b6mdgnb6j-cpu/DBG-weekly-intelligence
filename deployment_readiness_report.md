# Deployment Readiness Report

## Baseline

- Baseline tag: `baseline-58-sources`
- Baseline commit: `de8a925`
- Registered sources: 185
- Enabled sources: 58
- Scope: deployment preparation only; crawler, source, relevance, highlight, and UI design logic are frozen.

## Python Compatibility

- Target runtime: Python 3.12 on Streamlit Community Cloud.
- No Python 3.14-only syntax was introduced in the deployment changes.
- The Streamlit viewer imports only local loader/style helpers and standard JSON/path handling.

## Requirements Audit

- `requirements.txt` is limited to the package required for Streamlit app startup:
  - `streamlit`
- `requirements-crawler.txt` preserves the accepted crawler/generator dependency set from the 58-source baseline, excluding the viewer-only Streamlit dependency:
  - `pandas`
  - `requests`
  - `beautifulsoup4`
  - `feedparser`
- The deployment viewer does not import crawler network dependencies during page load.

## Published Data Architecture

- The deployed app reads Git-tracked published report data:
  - `published/latest.json`
  - `published/archive/weekly_20260817.json`
  - `published/archive/weekly_20260727.json`
- `output/`, `raw/`, and `logs/` remain ignored and are not required for deployment.
- `publish_weekly.py` copies an already-generated weekly report into the published data directory and updates `published/latest.json`.

## App Startup Behavior

- `app.py` does not call `run_weekly.py`.
- `app.py` does not crawl websites.
- `app.py` does not require `output/`, `raw/`, `logs/`, or local absolute paths.
- If no published data exists, the app shows a graceful message instead of raising a missing-file traceback.

## Secrets Audit

- No `.env` or `.streamlit/secrets.toml` file is tracked.
- No API keys, passwords, authorization headers, cookies, or credentials were found in tracked deployment files.
- Search hits for `cookie`/`token` are ordinary parser variable names in crawler code, not secret values.

## Absolute Path Audit

- Deployment code uses relative project paths derived from local module locations.
- No local user-directory dependency is used by the deployed viewer.
- README examples mention `output/weekly_data_*.json` only as local publishing input, not as a Streamlit runtime dependency.

## Local Streamlit Test

- Compile check passed:
  - `python3 -m compileall app.py publish_weekly.py crawler utils`
- Local Streamlit startup passed:
  - app served HTTP 200 on local test port
- Latest report loaded:
  - 2026-08-17 to 2026-08-23
  - 15 final items
  - 5 highlights
- Archive data available:
  - 2026-08-17 to 2026-08-23
  - 2026-07-27 to 2026-08-02
- No new crawl log was created during Streamlit startup.

## Files Added Or Modified

- Added: `publish_weekly.py`
- Added: `published/latest.json`
- Added: `published/archive/weekly_20260817.json`
- Added: `published/archive/weekly_20260727.json`
- Added: `README.md`
- Added: `deployment_readiness_report.md`
- Modified: `app.py`
- Modified: `utils/loader.py`
- Modified: `requirements.txt`
- Modified: `.gitignore`

## Known Limitations

- No scheduled weekly crawling is configured.
- No GitHub Actions automation is configured.
- No translation API is configured.
- The Streamlit app displays already-published reports only.
- Hard-source issues such as SimCorp, Clearstream, blocked sources, JS-heavy sites, and China regulator network access remain outside this deployment phase.

## Recommendation

A. Ready to create private GitHub repo and deploy.
