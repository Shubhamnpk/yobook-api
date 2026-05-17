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

## Cloudflare Pages

Recommended free deployment for YoBook API.

This repository includes a Cloudflare Pages setup:

- `index.html` for the public browser UI
- `functions/api/*.js` for edge API endpoints
- `data/*.json` as the source catalog
- `data/covers/` for generated book-cover images
- `_redirects` so `/covers/...` works on Cloudflare
- `_headers` for cache and CORS headers
- `wrangler.toml` for Cloudflare project defaults

Cloudflare Pages settings:

- Framework preset: None
- Build command: leave empty
- Build output directory: `.`
- Root directory: repository root

After deployment, these routes work without a sleeping server:

```text
/
/api/books
/api/books?source=cehrd-learning&grade=1
/api/books/<id>
/api/sources
/api/stats
/data/all_books.json
/data/covers/<file>.jpg
```

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

