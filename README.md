# YoBook API

An open-source Nepal school textbook catalog and API.

YoBook API collects public educational-book metadata from official and public sources, keeps CEHRD first in API ordering, includes curated Pustakalaya learning collections, generates real cover images from PDF first pages, and serves everything through a simple Flask API and browser UI.

## Open Source License

This project is free to use, copy, modify, distribute, and build on.

Please give credit when you use it by preserving the `LICENSE` and `NOTICE` files, and by mentioning:

> Powered by YoBook API

The project code is released under the MIT License. Source textbook PDFs, book covers generated from those PDFs, trademarks, and third-party metadata remain owned by their original publishers and providers.

## Source Strategy

CEHRD Learning Portal is listed first because it currently gives the cleanest official school-textbook structure:

- Grade-wise courses from class 1 to 12
- Subject-wise textbook resources
- Working Moodle resource links
- Direct PDF redirects
- Reliable enough data to generate real book covers from PDF first pages

Pustakalaya collections are grouped by their site sections and stored in folder-per-section JSON files. Lower-quality secondary sources are kept in `data/archive_data/` for reference when present, but they are not part of the active merged catalog.

## Sources

| Source | Role | What It Provides |
|---|---|---|
| CEHRD Learning Portal | Primary | Official grade/subject textbook PDFs from `learning.cehrd.gov.np` |
| CEHRD Stories/NFE/Audio | Active | Public CEHRD stories, non-formal education materials, and audio resources |
| Pustakalaya Literature and Arts | Active | Public literature and children's literature records from `pustakalaya.org` |
| Pustakalaya Reference Materials | Active | Dictionary, atlas, and children's encyclopedia collections |
| Pustakalaya Course Materials | Active | Subject, textbook, and technical course-material collections |
| Pustakalaya Teaching Materials | Active | Teacher support, curriculum, guides, and training collections |
| Pustakalaya Other Educational Materials | Active | Health, civics, environment, agriculture, law, computer, and related collections |
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

Scrape Pustakalaya section collections:

```bash
python scripts/scrape_pustakalaya_literature.py --limit 5
python scripts/scrape_pustakalaya_literature_copy.py --limit 5
python scripts/scrape_pustakalaya_course_materials.py --limit 5
python scripts/scrape_pustakalaya_teaching_materials.py --limit 5
python scripts/scrape_pustakalaya_other_educational_materials.py --limit 5
```

`--limit` is a test mode: it processes that many items per collection and skips merging into `all_books.json` unless `--merge-test` is passed.

Merge all active source files and nested resource folders:

```bash
python -c "import sys; sys.path.insert(0, 'scripts'); import scraper; scraper.merge_all()"
```

Validate the local catalog:

```bash
python scripts/validate_catalog.py
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

List responses are compact by default so search and browsing stay fast. Each item includes an `id` and `detailUrl`; call `/api/books/<id>` when you need the full record with PDF/read URLs, long metadata, and source details.

Useful filters:

| Query | Example |
|---|---|
| `source` | `/api/books?source=cehrd-learning` |
| `source` | `/api/books?source=pustakalaya-course` |
| `grade` | `/api/books?grade=10` |
| `subject` | `/api/books?subject=Science` |
| `q` | `/api/books?q=mathematics` |
| `limit` | `/api/books?limit=20` |
| `page` | `/api/books?page=2` |
| `full` | `/api/books?full=true` |

Compact list item:

```json
{
  "id": "cehrd-learning-g1-mathematics-40",
  "title": "Mathematics - Grade 1",
  "grade": 1,
  "subject": "Mathematics",
  "language": "en",
  "source": "cehrd-learning",
  "coverUrl": "/covers/cehrd-learning-g1-mathematics-40.jpg",
  "detailUrl": "/api/books/cehrd-learning-g1-mathematics-40"
}
```

### Other Endpoints

```http
GET /api/books/<id>
GET /api/gradewise-audio
GET /api/gradewise-audio?grade=4&subject=English
GET /api/pdf?url=<catalog-pdf-url>
GET /api/audio?url=<catalog-audio-url>
GET /api/sources
GET /api/stats
GET /docs
```

`/api/pdf` only streams PDF/read URLs that already exist in the catalog. The browser reader uses it to load CEHRD PDFs through the same origin for the flip-book UI.
`/api/gradewise-audio` returns Pustakalaya grade-wise audio grouped by grade, subject, and chapter. `/api/audio` streams catalog audio URLs and grade-wise audio URLs.

### Public API behavior and compatibility

- Public endpoints are cache-friendly and include `ETag` + `Last-Modified` headers.
- API requests are rate-limited per IP address to protect service availability.
- For v1, backward-compatible changes are preferred. If an endpoint or field is deprecated, removal is planned with advance notice in repository docs.

### Public endpoint exposure policy

Public consumers should use the stable `/api/*` contract. Recommended public endpoints are:

- `GET /api/books`
- `GET /api/books/<id>`
- `GET /api/gradewise-audio`
- `GET /api/sources`
- `GET /api/stats`
- `GET /api/health`
- `GET /openapi.json`
- `GET /docs`

Proxy endpoints are intentionally restricted and rate-limited:

- `GET /api/pdf?url=<catalog-pdf-url>`
- `GET /api/audio?url=<catalog-audio-url>`

Both proxy routes only allow URLs that are already in the catalog and must pass host allowlisting, timeout, and payload-size limits.

### What fields are exposed

List responses are compact and optimized for browsing:

- `id`, `title`, `titleLocal`
- `author`, `grade`, `subject`, `language`
- `source`, `category`, `level`
- `coverUrl`, `audioUrl`, `detailUrl`

Detail responses (`/api/books/<id>`) return the full record for that book.

### Internal dataset contract (`data/all_books.json`)

`data/all_books.json` is the internal canonical merged dataset used to power API responses. It is not intended to be treated as a long-term external API contract.

Best practice for API clients:

- Consume `/api/*` endpoints, not raw data files.
- Assume API schemas are stable and versioned through OpenAPI.
- Use `ETag`/`Last-Modified` for cache-aware clients.

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
  "audioUrl": null,
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
    Course Materials/       Pustakalaya course-material collection files
    Literature and Arts/    Pustakalaya literature collection files
    Other Educational Materials/
                            Pustakalaya other-educational collection files
    Reference Materials/    Pustakalaya reference collection files
    Teaching Materials/     Pustakalaya teaching-material collection files
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

