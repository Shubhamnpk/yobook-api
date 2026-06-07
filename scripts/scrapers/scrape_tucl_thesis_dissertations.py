r"""
TUCL Thesis & Dissertations scraper
===================================

Scrapes DSpace item metadata from:
https://elibrary.tucl.edu.np/communities/c2f76147-7820-4c16-9e0c-9f30613da768

The PDF is exposed as a DSpace bitstream content URL. This script records that
URL as both readUrl and downloadUrl for API compatibility, but does not
download the PDF file.

Usage:
  python scripts/scrapers/scrape_tucl_thesis_dissertations.py --limit 10
  python scripts/scrapers/scrape_tucl_thesis_dissertations.py --workers 12
  python scripts/scrapers/scrape_tucl_thesis_dissertations.py --save-every 250
  python scripts/scrapers/scrape_tucl_thesis_dissertations.py --structure-only
  python scripts\scrapers\scrape_tucl_thesis_dissertations.py --workers 8 --discovery-workers 3 --save-every 100
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_FILE = os.path.join(
    DATA_DIR, "Reference Materials", "tucl_thesis_dissertations.json"
)

BASE = "https://elibrary.tucl.edu.np"
REST_BASE = f"{BASE}/JQ99OgQIizUxyjI9nB0on9OyLkqsGIf4"
COMMUNITY_UUID = "c2f76147-7820-4c16-9e0c-9f30613da768"
COMMUNITY_URL = f"{BASE}/communities/{COMMUNITY_UUID}"

HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/1.0 (Educational Research; Nepal Digital Library)",
    "Accept": "application/json",
}
RATE_LIMIT = 0.1
PAGE_SIZE = 100
DEFAULT_WORKERS = 8
MAX_WORKERS = 10
DEFAULT_DISCOVERY_WORKERS = 2
MAX_DISCOVERY_WORKERS = 3
DEFAULT_SAVE_EVERY = 250
MAX_RETRIES = 4
DISCOVERY_MAX_BACKOFF = 60
REQUEST_TIMEOUT = (6, 18)
DISCOVERY_RETRIES = 2
KEYWORD_LIMIT = 32
TITLE_KEYWORD_LIMIT = 10

STOPWORDS = {
    "about",
    "after",
    "among",
    "analysis",
    "based",
    "between",
    "case",
    "comparative",
    "during",
    "effect",
    "effects",
    "from",
    "into",
    "municipality",
    "nepal",
    "nepalese",
    "practice",
    "practices",
    "relation",
    "role",
    "rural",
    "selected",
    "study",
    "through",
    "towards",
    "using",
    "with",
}

_thread_local = threading.local()
_cache_lock = threading.Lock()
_json_cache = {}


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except AttributeError:
    pass


def worker_session():
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        _thread_local.session = session
    return session


def request_json(session, url, params=None, max_retries=MAX_RETRIES, label=None):
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            wait_seconds = min(6, 0.75 * attempt)
            if label:
                print(
                    f"{label} request attempt {attempt}/{max_retries} failed; "
                    f"retrying in {wait_seconds:.1f}s. {exc}"
                )
            time.sleep(wait_seconds)
    raise RuntimeError(f"Failed after {max_retries} attempts: {url}") from last_error


def request_json_cached(session, url):
    with _cache_lock:
        cached = _json_cache.get(url)
    if cached is not None:
        return cached

    data = request_json(session, url)
    with _cache_lock:
        _json_cache[url] = data
    return data


def embedded(data, key):
    return data.get("_embedded", {}).get(key, [])


def page_info(data):
    return data.get("page", {}) or {}


def metadata_values(item, key):
    return [
        entry.get("value", "").strip()
        for entry in item.get("metadata", {}).get(key, [])
        if entry.get("value", "").strip()
    ]


def metadata_first(item, *keys, default=""):
    for key in keys:
        values = metadata_values(item, key)
        if values:
            return values[0]
    return default


def clean_text(value, default=""):
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def normalize_language(value):
    value = (value or "").lower()
    if value.startswith("en"):
        return "en"
    if value.startswith("ne"):
        return "ne"
    return "en"


def compact_keywords(*groups, max_items=KEYWORD_LIMIT):
    keywords = []
    seen = set()
    for group in groups:
        values = group if isinstance(group, (list, tuple)) else [group]
        for value in values:
            value = (value or "").strip()
            key = value.lower()
            if not value or key in seen:
                continue
            keywords.append(value)
            seen.add(key)
            if len(keywords) >= max_items:
                return keywords
    return keywords


def title_keywords(title, max_items=TITLE_KEYWORD_LIMIT):
    words = re.findall(r"[A-Za-z][A-Za-z0-9&'.-]*", title or "")
    keywords = []
    seen = set()
    for word in words:
        value = word.strip(" .,'\"()[]{}")
        key = value.lower()
        if len(key) < 4 or key in STOPWORDS or key in seen:
            continue
        keywords.append(value)
        seen.add(key)
        if len(keywords) >= max_items:
            break
    return keywords


def source_url_for_item(item):
    handle = item.get("handle") or ""
    if handle:
        return f"{BASE}/handle/{handle}"
    return urljoin(BASE, f"/items/{item.get('uuid') or item.get('id')}")


def fallback_title(item):
    item_id = item.get("uuid") or item.get("id") or "unknown"
    return f"Untitled TU thesis {item_id}"


def clean_category_name(name):
    name = (name or "").strip()
    if name.lower() == "management":
        return "Management"
    return name


def get_structure(session):
    community_url = f"{REST_BASE}/api/core/communities/{COMMUNITY_UUID}"
    community = request_json(session, community_url)

    subcommunities = []
    sub_data = request_json(
        session,
        f"{community_url}/subcommunities",
        params={"page": 0, "size": 100},
    )
    for sub in embedded(sub_data, "subcommunities"):
        subcommunities.append(
            {
                "uuid": sub.get("uuid") or sub.get("id"),
                "name": sub.get("name"),
                "archivedItemsCount": sub.get("archivedItemsCount", 0),
            }
        )

    collections = []
    col_data = request_json(
        session,
        f"{community_url}/collections",
        params={"page": 0, "size": 100},
    )
    for collection in embedded(col_data, "collections"):
        collections.append(
            {
                "uuid": collection.get("uuid") or collection.get("id"),
                "name": collection.get("name"),
                "archivedItemsCount": collection.get("archivedItemsCount", 0),
            }
        )

    facets = {}
    facets_data = request_json(
        session,
        f"{REST_BASE}/api/discover/facets",
        params={"scope": COMMUNITY_UUID},
    )
    for facet in embedded(facets_data, "facets"):
        facets[facet.get("name")] = {
            "facetType": facet.get("facetType"),
            "facetLimit": facet.get("facetLimit"),
        }

    return {
        "uuid": community.get("uuid") or community.get("id"),
        "name": community.get("name"),
        "archivedItemsCount": community.get("archivedItemsCount", 0),
        "url": COMMUNITY_URL,
        "restBase": REST_BASE,
        "subcommunities": subcommunities,
        "collections": collections,
        "facets": facets,
    }


def iter_discovery_items(session, limit=None):
    page = 0
    seen = 0
    total_elements = None
    discovery_failures = 0
    while True:
        try:
            data = request_json(
                session,
                f"{REST_BASE}/api/discover/search/objects",
                params={"scope": COMMUNITY_UUID, "page": page, "size": PAGE_SIZE},
            )
            discovery_failures = 0
        except RuntimeError as exc:
            discovery_failures += 1
            wait_seconds = min(DISCOVERY_MAX_BACKOFF, 15 * discovery_failures)
            print(
                f"Discovery page {page + 1} failed after retries; "
                f"waiting {wait_seconds}s before retrying same page. {exc}"
            )
            time.sleep(wait_seconds)
            continue

        result_data = data.get("_embedded", {}).get("searchResult", {})
        info = page_info(result_data)
        if total_elements is None:
            total_elements = info.get("totalElements")
            total_pages = info.get("totalPages")
            if total_elements is not None:
                print(f"Discovery: {total_elements} items across {total_pages} pages")

        objects = embedded(result_data, "objects")
        if not objects:
            break

        print(f"Discovery page {page + 1}: {len(objects)} objects")
        for result in objects:
            item = result.get("_embedded", {}).get("indexableObject")
            if not item or item.get("type") != "item":
                continue
            yield item
            seen += 1
            if limit is not None and seen >= limit:
                return

        total_pages = info.get("totalPages")
        page += 1
        if total_pages is not None and page >= total_pages:
            break
        time.sleep(RATE_LIMIT)


def fetch_discovery_page(page):
    session = worker_session()
    failures = 0
    while True:
        try:
            if page == 0 and failures == 0:
                print("Discovery page 1: requesting first page...")
            data = request_json(
                session,
                f"{REST_BASE}/api/discover/search/objects",
                params={"scope": COMMUNITY_UUID, "page": page, "size": PAGE_SIZE},
                max_retries=DISCOVERY_RETRIES,
                label=f"Discovery page {page + 1}",
            )
            result_data = data.get("_embedded", {}).get("searchResult", {})
            objects = []
            for result in embedded(result_data, "objects"):
                item = result.get("_embedded", {}).get("indexableObject")
                if item and item.get("type") == "item":
                    objects.append(item)
            return page, objects, page_info(result_data)
        except RuntimeError as exc:
            failures += 1
            wait_seconds = min(DISCOVERY_MAX_BACKOFF, 15 * failures)
            print(
                f"Discovery page {page + 1} failed after retries; "
                f"waiting {wait_seconds}s before retrying same page. {exc}"
            )
            time.sleep(wait_seconds)


def discover_all_items(limit=None, discovery_workers=DEFAULT_DISCOVERY_WORKERS):
    session = requests.Session()
    session.headers.update(HEADERS)
    requested_discovery_workers = max(1, discovery_workers)
    effective_discovery_workers = min(requested_discovery_workers, MAX_DISCOVERY_WORKERS)
    if effective_discovery_workers != requested_discovery_workers:
        print(
            f"Discovery workers capped at {effective_discovery_workers} "
            f"for TUCL stability (requested {requested_discovery_workers})."
        )
    page, first_items, first_info = fetch_discovery_page(0)
    total_elements = first_info.get("totalElements")
    total_pages = first_info.get("totalPages") or 1
    print(f"Discovery: {total_elements} items across {total_pages} pages")
    print(f"Discovery page 1: {len(first_items)} objects")

    if limit is not None and len(first_items) >= limit:
        return first_items[:limit]

    pages = {page: first_items}
    remaining_pages = list(range(1, total_pages))
    if limit is not None:
        pages_needed = (limit + PAGE_SIZE - 1) // PAGE_SIZE
        remaining_pages = remaining_pages[: max(0, pages_needed - 1)]

    if remaining_pages:
        print(
            f"Prefetching {len(remaining_pages)} discovery pages "
            f"with {effective_discovery_workers} workers..."
        )
    with concurrent.futures.ThreadPoolExecutor(max_workers=effective_discovery_workers) as executor:
        futures = {
            executor.submit(fetch_discovery_page, page_number): page_number
            for page_number in remaining_pages
        }
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            page_number, items, _ = future.result()
            pages[page_number] = items
            completed += 1
            if completed == 1 or completed % 10 == 0 or completed == len(futures):
                print(
                    f"Discovery prefetch: {completed}/{len(futures)} pages "
                    f"(latest page {page_number + 1}: {len(items)} objects)"
                )

    all_items = []
    for page_number in sorted(pages):
        all_items.extend(pages[page_number])
        if limit is not None and len(all_items) >= limit:
            return all_items[:limit]
    return all_items


def first_pdf_bitstream(session, item):
    bundles_url = item.get("_links", {}).get("bundles", {}).get("href")
    if not bundles_url:
        return None

    bundles_data = request_json(session, bundles_url)
    bundles = embedded(bundles_data, "bundles")
    original = next((bundle for bundle in bundles if bundle.get("name") == "ORIGINAL"), None)
    if not original:
        return None

    bitstreams_url = original.get("_links", {}).get("bitstreams", {}).get("href")
    if not bitstreams_url:
        return None

    bitstreams_data = request_json(session, bitstreams_url)
    candidates = embedded(bitstreams_data, "bitstreams")
    pdfs = [
        bitstream
        for bitstream in candidates
        if bitstream.get("name", "").lower().endswith(".pdf")
    ]
    return (pdfs or candidates or [None])[0]


def parent_community_path(session, community):
    path = []
    current = community
    while current:
        uuid = current.get("uuid") or current.get("id")
        name = current.get("name")
        if uuid == COMMUNITY_UUID:
            break
        if name:
            path.append(clean_category_name(name))

        parent_url = current.get("_links", {}).get("parentCommunity", {}).get("href")
        if not parent_url:
            break
        try:
            current = request_json_cached(session, parent_url)
        except RuntimeError:
            break

    return list(reversed(path))


def item_collection_path(session, item):
    owning_url = item.get("_links", {}).get("owningCollection", {}).get("href")
    if not owning_url:
        return [], {}

    collection = request_json_cached(session, owning_url)
    parent_url = collection.get("_links", {}).get("parentCommunity", {}).get("href")
    path = []
    if parent_url:
        try:
            parent = request_json_cached(session, parent_url)
            path.extend(parent_community_path(session, parent))
        except RuntimeError:
            pass

    collection_name = clean_category_name(collection.get("name"))
    if collection_name:
        path.append(collection_name)
    return path, collection


def thumbnail_url(item):
    link = item.get("_links", {}).get("thumbnail", {}).get("href")
    return link or None


def map_item_to_book(session, item, scraped_at):
    bitstream = first_pdf_bitstream(session, item)
    collection_path, _ = item_collection_path(session, item)
    pdf_url = ""
    if bitstream:
        pdf_url = bitstream.get("_links", {}).get("content", {}).get("href", "")

    title = clean_text(
        metadata_first(item, "dc.title", default=item.get("name")),
        default=fallback_title(item),
    )
    authors = metadata_values(item, "dc.contributor.author")
    author = ", ".join(authors) or "Unknown"
    subjects = metadata_values(item, "dc.subject")
    academic_level = clean_text(metadata_first(item, "local.academic.level"))
    institute = clean_text(metadata_first(item, "local.institute.title"))
    affiliated_institute = clean_text(metadata_first(item, "local.affiliatedinstitute.title"))
    other_institute = clean_text(metadata_first(item, "local.otherinstitute.title"))
    advisor = clean_text(metadata_first(item, "dc.contributor.advisor", "local.advisor"))
    issued = clean_text(metadata_first(item, "dc.date.issued"))
    publisher = clean_text(metadata_first(item, "dc.publisher"))
    language = normalize_language(metadata_first(item, "dc.language.iso"))

    subcategory = ", ".join(collection_path)
    keywords = compact_keywords(
        "TU",
        "Tribhuvan University",
        "TU Thesis",
        "Thesis",
        "Dissertation",
        academic_level,
        issued,
        collection_path,
        institute,
        affiliated_institute,
        other_institute,
        publisher,
        authors,
        subjects,
        title_keywords(title),
    )
    book = {
        "id": f"tucl-{item.get('uuid') or item.get('id')}",
        "title": title,
        "author": author,
        "language": language,
        "country": "np",
        "source": "tu",
        "sourceUrl": source_url_for_item(item),
        "coverUrl": thumbnail_url(item),
        "category": "Thesis",
        "subcategory": subcategory,
        "keywords": keywords,
        "scrapedAt": scraped_at,
    }

    optional_fields = {
        "readUrl": pdf_url,
        "downloadUrl": pdf_url,
        "description": metadata_first(item, "dc.description.abstract", "dc.description"),
        "publisher": publisher,
        "publishedYear": issued,
        "academicLevel": academic_level,
        "institute": institute,
        "affiliatedInstitute": affiliated_institute,
        "otherInstitute": other_institute,
        "advisor": advisor,
        "lastModified": item.get("lastModified"),
    }
    book.update({key: value for key, value in optional_fields.items() if value})
    return book


def load_existing(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        return {}
    return {item.get("id"): item for item in data if item.get("id")}


def progress_path(output_file):
    return f"{output_file}.progress.jsonl"


def load_progress(path):
    progress_file = progress_path(path)
    if not os.path.exists(progress_file):
        return {}

    records = {}
    with open(progress_file, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                print(f"Skipping invalid progress line {line_number}: {progress_file}")
                continue
            book_id = item.get("id")
            if book_id:
                records[book_id] = item
    return records


def append_progress(path, book):
    progress_file = progress_path(path)
    output_dir = os.path.dirname(progress_file) or "."
    os.makedirs(output_dir, exist_ok=True)
    with open(progress_file, "a", encoding="utf-8") as file:
        file.write(json.dumps(book, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


def save_books(path, books):
    output_dir = os.path.dirname(path) or "."
    os.makedirs(output_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=output_dir,
        text=True,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(format_books_json(books))
    os.replace(temp_path, path)


def format_books_json(books):
    chunks = ["[\n"]
    for index, book in enumerate(books):
        record = dict(book)
        placeholder = None
        if isinstance(record.get("keywords"), list):
            placeholder = f"__INLINE_KEYWORDS_{index}__"
            record["keywords"] = placeholder

        text = json.dumps(record, ensure_ascii=False, indent=2)
        if placeholder:
            inline_keywords = json.dumps(book["keywords"], ensure_ascii=False)
            text = text.replace(f'"{placeholder}"', inline_keywords)

        lines = text.splitlines()
        chunks.extend(f"  {line}\n" for line in lines)
        chunks.append(",\n" if index < len(books) - 1 else "\n")
    chunks.append("]\n")
    return "".join(chunks)


def sorted_books(books_by_id):
    return [books_by_id[key] for key in sorted(books_by_id)]


def rebuild_from_progress(output_file=OUTPUT_FILE):
    existing = load_existing(output_file)
    progress_records = load_progress(output_file)
    merged = dict(existing)
    merged.update(progress_records)
    books = sorted_books(merged)
    save_books(output_file, books)
    print(f"Rebuilt {output_file}")
    print(f"Existing records: {len(existing)}")
    print(f"Progress records: {len(progress_records)}")
    print(f"Merged records: {len(books)}")
    return books


def should_fetch(item, existing, refresh=False):
    book_id = f"tucl-{item.get('uuid') or item.get('id')}"
    if refresh:
        return True
    cached = existing.get(book_id)
    return (
        not cached
        or not cached.get("readUrl")
        or cached.get("category") != "Thesis"
        or not cached.get("subcategory")
        or "TU Thesis" not in cached.get("keywords", [])
    )


def fetch_book(item, scraped_at):
    session = worker_session()
    return map_item_to_book(session, item, scraped_at)


def drain_completed_futures(
    futures,
    books_by_id,
    output_file,
    save_every,
    counters,
    block=False,
):
    if not futures:
        return

    done_iter = (
        concurrent.futures.as_completed(futures)
        if block
        else (future for future in list(futures) if future.done())
    )
    for future in done_iter:
        item = futures.pop(future)
        counters["processed"] += 1
        try:
            book = future.result()
        except Exception as exc:
            counters["failed"] += 1
            title = clean_text(
                metadata_first(item, "dc.title", default=item.get("name")),
                default=fallback_title(item),
            )
            print(f"  [{counters['processed']}/{counters['queued']}] FAILED {title[:60]} - {exc}")
            continue

        books_by_id[book["id"]] = book
        counters["dirty_since_save"] += 1
        append_progress(output_file, book)
        if book.get("readUrl"):
            counters["with_pdf"] += 1

        elapsed = max(0.001, time.monotonic() - counters["started_at"])
        rate = counters["processed"] / elapsed
        remaining = max(0, counters["queued"] - counters["processed"])
        eta_seconds = int(remaining / rate) if rate else 0
        status = "PDF" if book.get("readUrl") else "no PDF"
        print(
            f"  [{counters['processed']}/{counters['queued']}] saved {status}: "
            f"{clean_text(book.get('title'), default='Untitled')[:62]} "
            f"({rate:.2f}/s, eta {eta_seconds // 60}m {eta_seconds % 60}s)"
        )

        if counters["dirty_since_save"] >= max(1, save_every):
            save_books(output_file, sorted_books(books_by_id))
            counters["dirty_since_save"] = 0


def run(
    limit=None,
    output_file=OUTPUT_FILE,
    workers=DEFAULT_WORKERS,
    discovery_workers=DEFAULT_DISCOVERY_WORKERS,
    refresh=False,
    save_every=DEFAULT_SAVE_EVERY,
):
    scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    existing = load_existing(output_file)
    progress_records = load_progress(output_file)
    existing.update(progress_records)
    session = requests.Session()
    session.headers.update(HEADERS)
    books_by_id = dict(existing)
    effective_workers = min(max(1, workers), MAX_WORKERS)
    effective_discovery_workers = min(max(1, discovery_workers), MAX_DISCOVERY_WORKERS)

    print("TUCL Thesis & Dissertations")
    print(f"REST base: {REST_BASE}")
    print(f"Output: {output_file}")
    print(f"Existing records: {len(existing)}")
    print(f"Progress checkpoint: {progress_path(output_file)}")
    print(
        f"Workers: {effective_workers}"
        + (f" (requested {workers})" if effective_workers != workers else "")
    )
    print(
        f"Discovery workers: {effective_discovery_workers}"
        + (f" (requested {discovery_workers})" if effective_discovery_workers != discovery_workers else "")
    )
    print(f"Full JSON save every: {save_every} records")
    if limit is not None:
        print(f"Limit: {limit} items")

    discovery_started = time.monotonic()
    items = discover_all_items(limit=limit, discovery_workers=discovery_workers)
    discovery_elapsed = max(0.001, time.monotonic() - discovery_started)
    pending = [item for item in items if should_fetch(item, existing, refresh=refresh)]
    skipped = len(items) - len(pending)
    print(
        f"Discovery finished: {len(items)} items in {discovery_elapsed:.1f}s; "
        f"{len(pending)} queued, {skipped} skipped existing."
    )

    counters = {
        "discovered": len(items),
        "queued": len(pending),
        "skipped": skipped,
        "processed": 0,
        "failed": 0,
        "with_pdf": 0,
        "dirty_since_save": 0,
        "started_at": time.monotonic(),
    }
    if not pending:
        save_books(output_file, sorted_books(books_by_id))
        print(f"Saved {len(books_by_id)} records. Nothing new to fetch.")
        return sorted_books(books_by_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = {
            executor.submit(fetch_book, item, scraped_at): item
            for item in pending
        }
        drain_completed_futures(
            futures,
            books_by_id,
            output_file,
            save_every,
            counters,
            block=True,
        )

    if counters["dirty_since_save"]:
        save_books(output_file, sorted_books(books_by_id))

    books = sorted_books(books_by_id)
    save_books(output_file, books)
    print(
        f"Saved {len(books)} records "
        f"({counters['with_pdf']} PDFs fetched this run, {counters['failed']} failures)."
    )
    return books


def main():
    parser = argparse.ArgumentParser(description="Scrape TUCL thesis/dissertation metadata.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum items to scrape.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output JSON path.")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent PDF metadata workers. Default: {DEFAULT_WORKERS}",
    )
    parser.add_argument(
        "--discovery-workers",
        type=int,
        default=DEFAULT_DISCOVERY_WORKERS,
        help=f"Concurrent discovery page workers. Default: {DEFAULT_DISCOVERY_WORKERS}",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch all discovered records again instead of skipping complete existing records.",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=DEFAULT_SAVE_EVERY,
        help=f"Rebuild full JSON after this many completed fetches. Default: {DEFAULT_SAVE_EVERY}. Each record is still checkpointed immediately.",
    )
    parser.add_argument(
        "--structure-only",
        action="store_true",
        help="Print the community structure and available facets, then exit.",
    )
    parser.add_argument(
        "--rebuild-from-progress",
        action="store_true",
        help="Merge the progress JSONL into the final JSON without contacting TUCL.",
    )
    args = parser.parse_args()

    session = requests.Session()
    if args.rebuild_from_progress:
        rebuild_from_progress(args.output)
        return

    if args.structure_only:
        structure = get_structure(session)
        print(json.dumps(structure, ensure_ascii=False, indent=2))
        return

    run(
        limit=args.limit,
        output_file=args.output,
        workers=args.workers,
        discovery_workers=args.discovery_workers,
        refresh=args.refresh,
        save_every=args.save_every,
    )


if __name__ == "__main__":
    main()
