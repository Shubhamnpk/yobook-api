"""
TUCL Reports scraper
====================

Scrapes report/project metadata from:
https://elibrary.tucl.edu.np/communities/4fd8ecce-5c92-4d7a-8c90-22ad63a41b1d

Output records intentionally use a compact research-report shape:
id, title, author, language, source, coverUrl, category, subcategory, keywords,
publishedYear, academicLevel, institutes, publisher, readUrl, downloadUrl.

Usage:
  python scripts/scrapers/scrape_tucl_reports.py --limit 10
  python scripts/scrapers/scrape_tucl_reports.py --workers 8 --discovery-workers 8
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

import requests


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "Reference Materials", "tu_reports.json")

BASE = "https://elibrary.tucl.edu.np"
REST_BASE = f"{BASE}/JQ99OgQIizUxyjI9nB0on9OyLkqsGIf4"
COMMUNITY_UUID = "4fd8ecce-5c92-4d7a-8c90-22ad63a41b1d"
COMMUNITY_NAME = "Report"

HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/1.0 (Educational Research; Nepal Digital Library)",
    "Accept": "application/json",
}
PAGE_SIZE = 100
DEFAULT_WORKERS = 8
DEFAULT_DISCOVERY_WORKERS = 8
DEFAULT_SAVE_EVERY = 100
MAX_RETRIES = 4
DISCOVERY_MAX_BACKOFF = 180
REQUEST_TIMEOUT = (6, 18)
DISCOVERY_RETRIES = 2
KEYWORD_LIMIT = 28
TITLE_KEYWORD_LIMIT = 8

STOPWORDS = {
    "about",
    "after",
    "analysis",
    "based",
    "building",
    "case",
    "commercial",
    "comparative",
    "design",
    "development",
    "effect",
    "from",
    "into",
    "nepal",
    "project",
    "report",
    "study",
    "structural",
    "system",
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


def clean_keyword(value):
    value = re.sub(r"\s+", " ", clean_text(value))
    return value.strip(" ,;:")


def extract_year(value):
    match = re.search(r"\b(19|20)\d{2}\b", value or "")
    return match.group(0) if match else clean_text(value)


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
            value = clean_keyword(value)
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


def fallback_title(item):
    item_id = item.get("uuid") or item.get("id") or "unknown"
    return f"Untitled TU report {item_id}"


def source_url_for_item(item):
    handle = item.get("handle") or ""
    if handle:
        return f"{BASE}/handle/{handle}"
    return f"{BASE}/items/{item.get('uuid') or item.get('id')}"


def clean_category_name(name):
    return clean_text(name)


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
            f"with {max(1, discovery_workers)} workers..."
        )
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, discovery_workers)) as executor:
        futures = {
            executor.submit(fetch_discovery_page, page_number): page_number
            for page_number in remaining_pages
        }
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            page_number, items, _ = future.result()
            pages[page_number] = items
            completed += 1
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
    original = next(
        (bundle for bundle in embedded(bundles_data, "bundles") if bundle.get("name") == "ORIGINAL"),
        None,
    )
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
        name = clean_category_name(current.get("name"))
        if uuid == COMMUNITY_UUID:
            break
        if name:
            path.append(name)

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
        return []

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
    return path


def thumbnail_url(item):
    return item.get("_links", {}).get("thumbnail", {}).get("href") or None


def join_institutes(*values):
    parts = []
    seen = set()
    for value in values:
        value = clean_text(value)
        key = value.lower()
        if value and key not in seen:
            parts.append(value)
            seen.add(key)
    return ", ".join(parts)


def map_item_to_report(session, item, scraped_at):
    bitstream = first_pdf_bitstream(session, item)
    collection_path = item_collection_path(session, item)
    pdf_url = bitstream.get("_links", {}).get("content", {}).get("href", "") if bitstream else ""

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
    publisher = clean_text(metadata_first(item, "dc.publisher"))
    issued = clean_text(metadata_first(item, "dc.date.issued"))
    published_year = extract_year(issued)
    language = normalize_language(metadata_first(item, "dc.language.iso"))
    institutes = join_institutes(institute, affiliated_institute, other_institute)

    keywords = compact_keywords(
        "TU",
        "Tribhuvan University",
        "TU Report",
        "Report",
        academic_level,
        published_year,
        issued,
        collection_path,
        institutes,
        publisher,
        authors,
        subjects,
        title_keywords(title),
    )

    return {
        "id": f"tu-report-{item.get('uuid') or item.get('id')}",
        "title": title,
        "author": author,
        "language": language,
        "source": "tu",
        "coverUrl": thumbnail_url(item),
        "category": COMMUNITY_NAME,
        "subcategory": ", ".join(collection_path),
        "keywords": keywords,
        "publishedYear": published_year,
        "academicLevel": academic_level,
        "institutes": institutes,
        "publisher": publisher,
        "readUrl": pdf_url,
        "downloadUrl": pdf_url,
    }


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
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            report_id = item.get("id")
            if report_id:
                records[report_id] = item
    return records


def append_progress(path, report):
    progress_file = progress_path(path)
    output_dir = os.path.dirname(progress_file) or "."
    os.makedirs(output_dir, exist_ok=True)
    with open(progress_file, "a", encoding="utf-8") as file:
        file.write(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


def format_reports_json(reports):
    placeholders = {}
    serializable = []
    for index, report in enumerate(reports):
        record = dict(report)
        if isinstance(record.get("keywords"), list):
            placeholder = f"__INLINE_KEYWORDS_{index}__"
            placeholders[placeholder] = json.dumps(record["keywords"], ensure_ascii=False)
            record["keywords"] = placeholder
        serializable.append(record)

    text = json.dumps(serializable, ensure_ascii=False, indent=2)
    for placeholder, inline_json in placeholders.items():
        text = text.replace(f'"{placeholder}"', inline_json)
    return text + "\n"


def save_reports(path, reports):
    output_dir = os.path.dirname(path) or "."
    os.makedirs(output_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=output_dir,
        text=True,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(format_reports_json(reports))
    os.replace(temp_path, path)


def sorted_reports(reports_by_id):
    return [reports_by_id[key] for key in sorted(reports_by_id)]


def should_fetch(item, existing, refresh=False):
    report_id = f"tu-report-{item.get('uuid') or item.get('id')}"
    if refresh:
        return True
    cached = existing.get(report_id)
    return not cached or not cached.get("readUrl") or cached.get("category") != COMMUNITY_NAME


def fetch_report(item, scraped_at):
    session = worker_session()
    return map_item_to_report(session, item, scraped_at)


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
    existing.update(load_progress(output_file))
    reports_by_id = dict(existing)

    print("TUCL Reports")
    print(f"REST base: {REST_BASE}")
    print(f"Output: {output_file}")
    print(f"Existing records: {len(existing)}")
    print(f"Progress checkpoint: {progress_path(output_file)}")
    print(f"Workers: {workers}")
    print(f"Discovery workers: {discovery_workers}")
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

    if not pending:
        save_reports(output_file, sorted_reports(reports_by_id))
        print(f"Saved {len(reports_by_id)} records. Nothing new to fetch.")
        return sorted_reports(reports_by_id)

    counters = {
        "processed": 0,
        "failed": 0,
        "with_pdf": 0,
        "dirty_since_save": 0,
        "started_at": time.monotonic(),
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(fetch_report, item, scraped_at): item
            for item in pending
        }
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            counters["processed"] += 1
            try:
                report = future.result()
            except Exception as exc:
                counters["failed"] += 1
                title = clean_text(
                    metadata_first(item, "dc.title", default=item.get("name")),
                    default=fallback_title(item),
                )
                print(f"  [{counters['processed']}/{len(pending)}] FAILED {title[:60]} - {exc}")
                continue

            reports_by_id[report["id"]] = report
            counters["dirty_since_save"] += 1
            append_progress(output_file, report)
            if report.get("readUrl"):
                counters["with_pdf"] += 1

            elapsed = max(0.001, time.monotonic() - counters["started_at"])
            rate = counters["processed"] / elapsed
            remaining = max(0, len(pending) - counters["processed"])
            eta_seconds = int(remaining / rate) if rate else 0
            status = "PDF" if report.get("readUrl") else "no PDF"
            print(
                f"  [{counters['processed']}/{len(pending)}] saved {status}: "
                f"{clean_text(report.get('title'), default='Untitled')[:62]} "
                f"({rate:.2f}/s, eta {eta_seconds // 60}m {eta_seconds % 60}s)"
            )

            if counters["dirty_since_save"] >= max(1, save_every):
                save_reports(output_file, sorted_reports(reports_by_id))
                counters["dirty_since_save"] = 0

    if counters["dirty_since_save"]:
        save_reports(output_file, sorted_reports(reports_by_id))

    reports = sorted_reports(reports_by_id)
    save_reports(output_file, reports)
    print(
        f"Saved {len(reports)} records "
        f"({counters['with_pdf']} PDFs fetched this run, {counters['failed']} failures)."
    )
    return reports


def main():
    parser = argparse.ArgumentParser(description="Scrape TUCL report metadata.")
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
    args = parser.parse_args()

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
