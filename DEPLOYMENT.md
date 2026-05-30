# Deployment Guide

YoBook API is a Flask app with local JSON data and generated cover files. The simplest production setup is:

```bash
gunicorn api:app
```

## What to Commit

For a ready-to-run public deployment, commit:

- `api.py`
- `scripts/`
- `data/*.json`
- `data/covers/`
- `requirements.txt`
- `Procfile`

The JSON and generated covers are intentionally part of the deployable app.

## Vercel

Recommended deployment for YoBook API. `vercel.json` routes the static UI as static files and sends Flask API traffic through the Python function wrapper at `api/index.py`.

Public routes after deploy:

```text
/
/playground.html
/api
/api/books
/api/books?grade=1
/api/books/<id>
/api/sources
/api/stats
/docs
/openapi.json
/data/all_books.json
/data/covers/<file>.jpg
```

Deploy from the project root:

```bash
npm i -g vercel
vercel login
vercel
vercel --prod
```

Vercel installs `requirements.txt` for the Python API function. The archived source files under `data/archive_data/` are excluded from Vercel deployments by `.vercelignore`; only the active merged catalog is public.

## Cloudflare Workers

Cloudflare Workers cannot run the Flask app directly. The repository includes `wrangler.jsonc` and `cloudflare-worker.js` as a Workers/static-assets compatibility layer so this deploy command has a valid entry point:

```bash
npx wrangler versions upload
```

The Worker serves static files and implements the main catalog endpoints from `data/all_books.json`, including `/api/books`, `/api/search`, `/api/books/<id>`, `/api/sources`, `/api/stats`, and `/api/health`. Use Vercel, Render, Railway, or Fly.io when you need the full Flask runtime behavior, especially proxy endpoints such as `/api/pdf` and `/api/audio`.

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
python scripts/scrapers/scraper.py --source cehrd
python scripts/covers/generate_pdf_covers.py --source cehrd-learning
python -c "import sys; sys.path.insert(0, 'scripts/scrapers'); import scraper; scraper.merge_all()"
```

Then redeploy the updated repository.

