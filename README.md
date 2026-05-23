# YoBook API

An open-source Nepal school textbook catalog and API.

YoBook API collects public educational-book metadata from official and public sources, keeps CEHRD as the primary source, generates real cover images from PDF first pages, and serves everything through a simple Flask API and browser UI.

## Open Source License

This project is free to use, copy, modify, distribute, and build on.

Please give credit when you use it by preserving the `LICENSE` and `NOTICE` files, and by mentioning:

> Powered by YoBook API

The project code is released under the MIT License. Source textbook PDFs, book covers generated from those PDFs, trademarks, and third-party metadata remain owned by their original publishers and providers.

## Why CEHRD First?

CEHRD Learning Portal is the primary source because it currently gives the cleanest official structure:

- Grade-wise courses from class 1 to 12
- Subject-wise textbook resources
- Working Moodle resource links
- Direct PDF redirects
- Reliable enough data to generate real book covers from PDF first pages

Lower-quality secondary sources are kept in `data/archive_data/` for reference, but they are not part of the active merged catalog.

## Sources

| Source | Role | What It Provides |
|---|---|---|
| CEHRD Learning Portal | Primary | Official grade/subject textbook PDFs from `learning.cehrd.gov.np` |
| E-Pustakalaya | Archived | Public digital-library records for Nepal education |
| CDC Nepal | Archived | Official CDC publication links and curated textbook records |
| Internet Archive | Archived | Digitized Nepal-related books and documents |
| Open Library | Archived | Additional public catalog metadata |

## Features

- Flask API with JSON responses
- Browser UI for searching and filtering books
- CEHRD-first default catalog
- Grade, subject, source, language, and keyword filters
- Real generated book covers from PDF first pages
- Local static cover serving through `/covers/<file>`
- Swagger UI at `/docs`
- No database required

## Quick Start

```bash
pip install -r requirements.txt
python api.py
```

Open:

```text
http://127.0.0.1:5000/
```

## Scraping

Scrape the primary CEHRD source:

```bash
python scripts/scraper.py --source cehrd
```

Scrape one grade:

```bash
python scripts/scraper.py --source cehrd --grade 5
```

Scrape everything:

```bash
python scripts/scraper.py
```

Generate real covers from PDF first pages:

```bash
python scripts/generate_pdf_covers.py --source cehrd-learning
```

The generated covers are saved in:

```text
data/covers/
```

## API

### List Books

```http
GET /api/books
```

Useful filters:

| Query | Example |
|---|---|
| `source` | `/api/books?source=cehrd-learning` |
| `grade` | `/api/books?grade=10` |
| `subject` | `/api/books?subject=Science` |
| `q` | `/api/books?q=mathematics` |
| `limit` | `/api/books?limit=20` |
| `page` | `/api/books?page=2` |

### Other Endpoints

```http
GET /api/books/<id>
GET /api/sources
GET /api/stats
GET /docs
```

## Data Shape

```json
{
  "id": "cehrd-learning-g1-mathematics-40",
  "title": "Mathematics - Grade 1",
  "author": "Centre for Education and Human Resource Development",
  "grade": 1,
  "subject": "Mathematics",
  "language": "en",
  "country": "np",
  "curriculum": "CDC Nepal",
  "source": "cehrd-learning",
  "sourceUrl": "https://learning.cehrd.gov.np/mod/resource/view.php?id=40",
  "readUrl": "https://learning.cehrd.gov.np/mod/resource/view.php?id=40",
  "pdfUrl": "https://learning.cehrd.gov.np/pluginfile.php/...",
  "coverUrl": "/covers/cehrd-learning-g1-mathematics-40.jpg",
  "category": "Textbook",
  "keywords": ["CEHRD", "CDC", "textbook", "Nepal", "class 1", "Mathematics"]
}
```

## Project Structure

```text
book-api/
  api.py                    Flask API and UI server
  scripts/
    scraper.py              Source scrapers
    generate_pdf_covers.py  Generates covers from PDF first pages
    sync_pustakalaya_covers.py
                            Enriches CEHRD covers from archived Pustakalaya data
  requirements.txt          Python dependencies
  Procfile                  Production start command
  openapi.json              API schema
  data/
    all_books.json          Active merged catalog
    cehrd_learning.json     Primary CEHRD data
    archive_data/           Archived lower-quality source data
      pustakalaya.json      E-Pustakalaya data
      cdc_nepal.json        CDC data
      archive_org.json      Internet Archive data
      open_library.json     Open Library data
    covers/                 Generated local book covers
```

## Deployment

Recommended free deployment: Vercel.

Vercel is ready through `vercel.json` and `api/index.py`:

```bash
npm i -g vercel
vercel login
vercel
vercel --prod
```

After deploy, the public API endpoints are:

```text
/api/books
/api/books?grade=1
/api/books/<id>
/api/sources
/api/stats
/docs
```

The Flask app is still useful for local development and powers the Vercel Python function.

Recommended start command:

```bash
gunicorn api:app
```

Good hosting options:

- Render: easiest for a Flask web service from GitHub
- Railway: good if you later want persistent volumes or scheduled jobs
- Fly.io: good for Docker-style deployment and more control

For a simple public deployment, commit the JSON data and generated covers so the app works immediately after deploy.

## Attribution

If you use this project in an app, website, API, dataset, research project, or redistributed package, please include visible or documented credit:

```text
Powered by YoBook API
```

Also keep the original `LICENSE` and `NOTICE` files with the code or distribution.

## Content Notice

YoBook API does not claim ownership of CEHRD, CDC, E-Pustakalaya, Internet Archive, Open Library, or other third-party source content.

The scraper and API code, catalog structure, normalization logic, and documentation are open source. Textbook PDFs and generated PDF-cover images may be subject to the original publishers' terms.

## Contributing

Contributions are welcome. Good first improvements include:

- Fixing metadata for a grade or subject
- Adding better language detection
- Improving cover generation quality
- Adding tests for API filters
- Adding a scheduled refresh workflow
- Improving deployment examples

Please read `CONTRIBUTING.md` before opening a pull request.

