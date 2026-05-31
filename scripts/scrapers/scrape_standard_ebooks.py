"""
Scrape Standard Ebooks public catalog into YoBook literature format.

The full OPDS catalog requires credentials, so this scraper uses the public
paginated /ebooks pages and each public ebook detail page. It extracts only
public metadata and public download URLs.

Usage:
  python scripts/scrapers/scrape_standard_ebooks.py --limit 12 --dry-run
  python scripts/scrapers/scrape_standard_ebooks.py
  python scripts/scrapers/scrape_standard_ebooks.py --skip-existing
  python scripts/scrapers/scrape_standard_ebooks.py --workers 6 --request-interval 0.2
"""

import argparse
import concurrent.futures
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILE = ROOT / "data" / "Literature and Arts" / "standard_ebooks.json"

BASE_URL = "https://standardebooks.org"
CATALOG_URL = f"{BASE_URL}/ebooks"

DEFAULT_TIMEOUT = (5, 20)
DEFAULT_RETRIES = 2
DEFAULT_WORKERS = 8
DEFAULT_REQUEST_INTERVAL = 0.12

HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/1.0 (Educational Research; Standard Ebooks)",
    "Accept": "application/xhtml+xml,text/html;q=0.9,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    adapter = HTTPAdapter(pool_connections=24, pool_maxsize=24, max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_text(session, url):
    last_exc = None
    for attempt in range(DEFAULT_RETRIES + 1):
        try:
            response = session.get(url, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_exc = exc
            if attempt < DEFAULT_RETRIES:
                time.sleep(0.5 * (attempt + 1))
    raise last_exc


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def ebook_slug(source_url):
    return source_url.replace(f"{BASE_URL}/ebooks/", "").strip("/")


def absolute_url(url):
    return urljoin(BASE_URL, url) if url else ""


def catalog_page_url(page):
    return CATALOG_URL if page == 1 else f"{CATALOG_URL}?page={page}"


def parse_soup(html):
    return BeautifulSoup(html, "lxml-xml")


def find_last_page(soup):
    pages = [1]
    for link in soup.select('nav[aria-label="Pagination"] a[href]'):
        text = clean_text(link.get_text())
        if text.isdigit():
            pages.append(int(text))
    return max(pages)


def parse_catalog_page(html):
    soup = parse_soup(html)
    items = []
    for item in soup.select("main ol > li"):
        title_link = item.select_one("p:nth-of-type(1) a[href]")
        author_link = item.select_one("p:nth-of-type(2) a[href]")
        if not title_link:
            continue
        items.append(
            {
                "title": clean_text(title_link.get_text()),
                "author": clean_text(author_link.get_text()) if author_link else "",
                "sourceUrl": absolute_url(title_link.get("href")),
            }
        )
    return items


def collect_catalog_items(session, limit=None):
    first_html = get_text(session, CATALOG_URL)
    first_soup = parse_soup(first_html)
    last_page = find_last_page(first_soup)

    items = parse_catalog_page(first_html)
    for page in range(2, last_page + 1):
        if limit and len(items) >= limit:
            break
        html = get_text(session, catalog_page_url(page))
        items.extend(parse_catalog_page(html))
        print(f"Indexed page {page}/{last_page}: {len(items)} items")

    if limit:
        items = items[:limit]

    deduped = {item["sourceUrl"]: item for item in items}
    return list(deduped.values())


def link_by_text(soup, text):
    expected = text.lower()
    for link in soup.find_all("a", href=True):
        if clean_text(link.get_text()).lower() == expected:
            return absolute_url(link.get("href"))
    return ""


def download_links(soup):
    links = []
    for link in soup.find_all("a", href=True):
        text = clean_text(link.get_text()).lower()
        href = absolute_url(link.get("href"))
        if "/downloads/" not in href:
            continue
        if text == "compatible epub":
            links.append(href)
        elif text == "advanced epub":
            links.append(href)
        elif text == "azw3":
            links.append(href)
        elif text == "kepub":
            links.append(href)
    return links


def extract_subjects(soup):
    subjects = []
    for link in soup.select('a[href^="/subjects/"]'):
        subject = clean_text(link.get_text())
        if subject and subject not in subjects:
            subjects.append(subject)
    return subjects


def extract_description(soup):
    description = soup.select_one('meta[name="description"]')
    if description and description.get("content"):
        text = clean_text(description.get("content"))
        text = re.sub(
            r"^Free epub ebook download of the Standard Ebooks edition of\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text
    return ""


def normalize_detail(index_item, html, scraped_at):
    soup = parse_soup(html)
    source_url = index_item["sourceUrl"]
    path_slug = ebook_slug(source_url)
    title = clean_text(soup.select_one("h1").get_text()) if soup.select_one("h1") else index_item["title"]
    author_node = soup.select_one("main h1 + p")
    author = index_item["author"] or (clean_text(author_node.get_text()) if author_node else "Anonymous")
    subjects = extract_subjects(soup)
    downloads = download_links(soup)
    read_url = link_by_text(soup, "Read on one page") or f"{source_url}/text/single-page"
    cover = soup.select_one('meta[property="og:image"]')
    cover_url = cover.get("content") if cover else f"{source_url}/downloads/cover.jpg"

    return {
        "id": f"se-{slugify(path_slug)}",
        "title": title,
        "author": author or "Standard Ebooks",
        "language": "en",
        "country": "us",
        "source": "standard-ebooks",
        "sourceUrl": source_url,
        "readUrl": read_url,
        "downloadUrl": downloads,
        "coverUrl": cover_url,
        "category": "Literature and Arts",
        "subject": subjects[0] if subjects else "Literature",
        "subjects": subjects,
        "publisher": "Standard Ebooks",
        "description": extract_description(soup),
        "scrapedAt": scraped_at,
    }


def fetch_detail(index_item):
    session = make_session()
    html = get_text(session, index_item["sourceUrl"])
    return index_item, html


def scrape(
    limit=None,
    workers=DEFAULT_WORKERS,
    request_interval=DEFAULT_REQUEST_INTERVAL,
    existing_source_urls=None,
):
    session = make_session()
    items = collect_catalog_items(session, limit=limit)
    if existing_source_urls:
        before = len(items)
        items = [item for item in items if item["sourceUrl"] not in existing_source_urls]
        print(f"Skipping existing detail pages: {before - len(items)}")
    scraped_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    books = []
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_detail, item): item for item in items}
        total = len(future_map)
        for done, future in enumerate(concurrent.futures.as_completed(future_map), 1):
            item = future_map[future]
            try:
                index_item, html = future.result()
                record = normalize_detail(index_item, html, scraped_at)
                if record["downloadUrl"]:
                    books.append(record)
                else:
                    failed.append((item["sourceUrl"], "missing compatible epub"))
            except Exception as exc:
                failed.append((item["sourceUrl"], str(exc)))

            if done % 50 == 0 or done == total:
                print(f"Fetched details {done}/{total}: records={len(books)} failed={len(failed)}")
            time.sleep(request_interval)

    deduped = {book["id"]: book for book in books}
    books = sorted(deduped.values(), key=lambda book: (book["author"].lower(), book["title"].lower()))
    return books, failed


def save_books(path, books):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_existing_books(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def main():
    parser = argparse.ArgumentParser(description="Scrape Standard Ebooks literature catalog")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE, help="Output JSON file")
    parser.add_argument("--limit", type=int, help="Maximum ebooks to process")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent detail fetches")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL,
        help="Small delay after each completed detail request",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Keep records already in the output file and only fetch missing source URLs",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing JSON")
    args = parser.parse_args()

    existing = load_existing_books(args.output) if args.skip_existing else []
    existing_by_url = {book.get("sourceUrl"): book for book in existing if book.get("sourceUrl")}

    books, failed = scrape(
        limit=args.limit,
        workers=max(1, args.workers),
        request_interval=max(0, args.request_interval),
        existing_source_urls=set(existing_by_url),
    )
    if args.skip_existing:
        merged = {book["id"]: book for book in existing}
        merged.update({book["id"]: book for book in books})
        books = sorted(merged.values(), key=lambda book: (book["author"].lower(), book["title"].lower()))

    print(f"Standard Ebooks records ready: {len(books)}")
    if args.skip_existing:
        print(f"Existing records kept: {len(existing)}")
        print(f"New records fetched: {len(books) - len(existing)}")
    print(f"Failed records: {len(failed)}")
    for url, reason in failed[:20]:
        print(f"  - {url}: {reason}")
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
