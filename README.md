# DBG Weekly Intelligence

Streamlit viewer for the Deutsche Börse Group weekly intelligence report.

The deployed app is a viewer only. It reads already-published report data from `published/latest.json` and does not crawl websites during page load.

## Local Viewer

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Crawler / Generator Environment

For crawler and weekly-generation work, install the crawler dependency set:

```bash
pip install -r requirements-crawler.txt
```

For a clean full-project environment, install both files:

```bash
pip install -r requirements.txt
pip install -r requirements-crawler.txt
```

## Publish A Generated Report

After a weekly report has already been generated locally, publish its final JSON payload:

```bash
python3 publish_weekly.py <weekly_json>
```

Example:

```bash
python3 publish_weekly.py output/weekly_data_20260817.json
```

This writes:

- `published/archive/weekly_YYYYMMDD.json`
- `published/latest.json`

## Deployment Target

The intended deployment target is Streamlit Community Cloud using a private GitHub repository.

Generated crawl data, logs, QA diagnostics, and temporary outputs remain local and are not part of the deployed viewer payload.
