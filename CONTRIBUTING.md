# Contributing

Thanks for helping improve YoBook API.

This project is meant to stay simple, useful, and easy to deploy. Prefer clear data, working links, and small improvements over complicated infrastructure.

## Ways to Contribute

- Fix incorrect book metadata
- Add or improve source scrapers
- Improve CEHRD coverage
- Improve PDF cover generation
- Add tests for API filters
- Improve deployment documentation
- Report broken links
- Suggest better source attribution

## Local Setup

```bash
pip install -r requirements.txt
python api.py
```

Open:

```text
http://127.0.0.1:5000/
```

## Data Workflow

Primary source:

```bash
python scripts/scraper.py --source cehrd
python scripts/generate_pdf_covers.py --source cehrd-learning
```

Merge all source files:

```bash
python -c "import sys; sys.path.insert(0, 'scripts'); import scraper; scraper.merge_all()"
```

Validate local data before committing:

```bash
python scripts/validate_catalog.py
```

## Pull Request Checklist

Before opening a pull request:

- Run `python -m py_compile api.py scripts/scraper.py scripts/generate_pdf_covers.py scripts/sync_pustakalaya_covers.py scripts/validate_catalog.py`
- Run `python scripts/validate_catalog.py`
- Check that `/api/books` still returns data
- Check that `/api/sources` lists CEHRD first
- Do not remove attribution, license, or source notices
- Do not claim ownership of third-party textbook content

## Source and Copyright Care

Only add public source links and metadata that can be reasonably indexed. Do not upload private, paid, or restricted books into this project.

Generated covers are made from the first page of linked PDFs for catalog display. They should be treated as source-derived content, not as original project artwork.

## Code Style

- Keep scripts plain Python where possible
- Avoid adding a database unless there is a strong reason
- Prefer readable code over clever abstractions
- Keep generated data deterministic when possible
- Keep CEHRD as the primary/default source

