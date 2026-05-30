"""
Scrape OpenStax textbooks into YoBook textbook format.

This scraper uses OpenStax's public CMS API instead of rendered HTML:
  1. Fetch the books index for ids/slugs.
  2. Fetch each book detail concurrently.
  3. Normalize live English books that have a downloadable PDF.

Usage:
  python scripts/scrapers/scrape_openstax_textbooks.py --limit 5 --dry-run
  python scripts/scrapers/scrape_openstax_textbooks.py
  python scripts/scrapers/scrape_openstax_textbooks.py --workers 16 --validate-pdfs
"""

import argparse
import concurrent.futures
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILE = ROOT / "data" / "Course Materials" / "openstax_textbooks.json"

BASE_URL = "https://openstax.org"
BOOK_INDEX_URL = f"{BASE_URL}/apps/cms/api/v2/pages/"
BOOK_DETAIL_URL = f"{BASE_URL}/apps/cms/api/v2/pages/{{page_id}}/"

DEFAULT_WORKERS = 12
DEFAULT_TIMEOUT = (5, 20)
DEFAULT_RETRIES = 2
REQUEST_INTERVAL = 0.05

EXCLUDED_SLUGS = {
    "biology-2e",
    "calculus-volume-1",
    "calculus-volume-2",
    "calculus-volume-3",
    "concepts-biology",
    "microbiology",
    "precalculus-2e",
    "principles-economics-3e",
    "principles-macroeconomics-3e",
    "principles-microeconomics-3e",
    "university-physics-volume-1",
    "university-physics-volume-2",
    "university-physics-volume-3",
}

HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/1.0 (Educational Research; OpenStax Textbooks)",
    "Accept": "application/json,text/html;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_json(session, url, params=None):
    last_exc = None
    for attempt in range(DEFAULT_RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_exc = exc
            if attempt < DEFAULT_RETRIES:
                time.sleep(0.4 * (attempt + 1))
    raise last_exc


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def strip_html(value):
    if not value:
        return ""
    return clean_text(BeautifulSoup(value, "lxml").get_text(" "))


def slug_from_url(url):
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def normalize_slug(slug):
    return re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")


def first_pdf_url(book):
    return book.get("high_resolution_pdf_url") or book.get("low_resolution_pdf_url") or ""


def author_names(book, max_authors=3):
    names = []
    authors = book.get("authors") or []

    def author_sort_key(item):
        value = item.get("value") or {}
        return (
            not bool(value.get("senior_author")),
            not bool(value.get("display_at_top")),
            clean_text(value.get("name")).lower(),
        )

    for item in sorted(authors, key=author_sort_key):
        value = item.get("value") or {}
        name = clean_text(value.get("name"))
        if name and name not in names:
            names.append(name)
        if len(names) >= max_authors:
            break

    return ", ".join(names) or "OpenStax"


def subject_name(book):
    for category in book.get("book_categories") or []:
        name = clean_text(category.get("subject_category"))
        if name:
            return name

    for subject in book.get("book_subjects") or []:
        name = clean_text(subject.get("subject_name"))
        if name:
            return name

    return "OpenStax"


def normalize_book(book, scraped_at):
    meta = book.get("meta") or {}
    slug = normalize_slug(meta.get("slug") or slug_from_url(meta.get("html_url", "")))
    pdf_url = first_pdf_url(book)

    if not slug or not pdf_url:
        return None
    if slug in EXCLUDED_SLUGS:
        return None
    if book.get("book_state") != "live":
        return None
    if meta.get("locale") and meta.get("locale") != "en":
        return None

    source_url = meta.get("html_url") or f"{BASE_URL}/details/books/{slug}"

    return {
        "id": f"ops-{slug}",
        "title": clean_text(book.get("title")),
        "author": author_names(book),
        "language": "en",
        "country": "us",
        "source": "openstax",
        "sourceUrl": source_url,
        "readUrl": book.get("webview_rex_link") or book.get("webview_link") or source_url,
        "pdfUrl": pdf_url,
        "coverUrl": book.get("cover_url") or book.get("title_image_url") or "",
        "category": "Textbook",
        "subject": subject_name(book),
        "publisher": "OpenStax",
        "educationLevel": "Higher Education",
        "scrapedAt": scraped_at,
    }


def fetch_book_index(session):
    params = {
        "type": "books.Book",
        "fields": "title,id,book_state",
        "limit": 250,
    }
    data = get_json(session, BOOK_INDEX_URL, params=params)
    return data.get("items", [])


def fetch_book_detail(page_id):
    session = make_session()
    return get_json(session, BOOK_DETAIL_URL.format(page_id=page_id), params={"format": "json"})


def is_valid_pdf(session, url):
    response = session.head(url, allow_redirects=True, timeout=DEFAULT_TIMEOUT)
    if response.status_code >= 400:
        return False
    content_type = response.headers.get("content-type", "").lower()
    return "pdf" in content_type or urlparse(response.url).path.lower().endswith(".pdf")


def scrape_books(limit=None, workers=DEFAULT_WORKERS, validate_pdfs=False):
    session = make_session()
    index_items = fetch_book_index(session)
    if limit:
        index_items = index_items[:limit]

    scraped_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    books = []
    failed = []
    skipped = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(fetch_book_detail, item["id"]): item
            for item in index_items
            if item.get("id")
        }

        for future in concurrent.futures.as_completed(future_map):
            item = future_map[future]
            try:
                detail = future.result()
                record = normalize_book(detail, scraped_at)
                if not record:
                    skipped += 1
                    continue
                if validate_pdfs and not is_valid_pdf(session, record["pdfUrl"]):
                    failed.append((record["id"], "PDF validation failed"))
                    continue
                books.append(record)
            except Exception as exc:
                failed.append((item.get("id"), str(exc)))
            time.sleep(REQUEST_INTERVAL)

    deduped = {book["id"]: book for book in books}
    return sorted(deduped.values(), key=lambda book: (book["subject"].lower(), book["title"].lower())), skipped, failed


def save_books(path, books):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Scrape OpenStax textbooks")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE, help="Output JSON file")
    parser.add_argument("--limit", type=int, help="Maximum books from the index to process")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent detail fetches")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing JSON")
    parser.add_argument("--validate-pdfs", action="store_true", help="HEAD-check each PDF URL")
    args = parser.parse_args()

    books, skipped, failed = scrape_books(
        limit=args.limit,
        workers=max(1, args.workers),
        validate_pdfs=args.validate_pdfs,
    )

    print(f"OpenStax records ready: {len(books)}")
    print(f"Skipped non-live/non-English/no-PDF records: {skipped}")
    print(f"Failed detail/PDF checks: {len(failed)}")

    if failed:
        for book_id, reason in failed[:20]:
            print(f"  - {book_id}: {reason}")
        if len(failed) > 20:
            print(f"  ... {len(failed) - 20} more")

    if args.dry_run:
        print(json.dumps(books[:3], ensure_ascii=False, indent=2))
        return 0 if books else 1

    save_books(args.output, books)
    print(f"Wrote {args.output.relative_to(ROOT)}")
    return 0 if books else 1


if __name__ == "__main__":
    sys.exit(main())
