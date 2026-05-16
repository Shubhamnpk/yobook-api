# Deployment Guide

YoBook API is a Flask app with local JSON data and generated cover files. The simplest production setup is:

```bash
gunicorn api:app
```

## What to Commit

For a ready-to-run public deployment, commit:

- `api.py`
- `scraper.py`
- `generate_pdf_covers.py`
- `templates/`
- `data/*.json`
- `data/covers/`
- `requirements.txt`
- `Procfile`

The JSON and generated covers are intentionally part of the deployable app.

## Render

Recommended for the easiest public hosting.

Settings:

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn api:app`

## Railway

Good if you later want persistent volumes, scheduled jobs, or background refresh tasks.

Settings:

- Build: automatic Python build from `requirements.txt`
- Start command: `gunicorn api:app`

## Fly.io

Good when you want more control or Docker-based deployment.

Use `gunicorn api:app` as the web process inside the container.

## Refreshing Data

To refresh CEHRD data:

```bash
python scraper.py --source cehrd
python generate_pdf_covers.py --source cehrd-learning
python -c "import scraper; scraper.merge_all()"
```

Then redeploy the updated repository.

