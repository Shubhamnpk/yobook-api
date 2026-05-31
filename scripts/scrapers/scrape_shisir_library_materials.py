"""
Scrape Shisir Adhikari eLibrary materials into YoBook book format.

The /library page renders its dataset from embedded JavaScript arrays:
  - libraryCategories on /library and category pages
  - libraryMaterials on leaf category pages

This scraper walks those internal categories, extracts material PDF paths, visits
detail pages for cover images and detailed metadata concurrently, and writes
Course Materials records with real-time progress and incremental saving.

Usage:
  python scripts/scrapers/scrape_shisir_library_materials.py --limit-categories 5
  python scripts/scrapers/scrape_shisir_library_materials.py
  python scripts/scrapers/scrape_shisir_library_materials.py --selected-categories
  python scripts/scrapers/scrape_shisir_library_materials.py --workers 16 --category-workers 8
  python scripts/scrapers/scrape_shisir_library_materials.py --letter A
  python scripts/scrapers/scrape_shisir_library_materials.py --merge
"""

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
COURSE_DIR = DATA_DIR / "Course Materials"
OUTPUT_FILE = COURSE_DIR / "shisir_library_materials.json"
BASE_URL = "https://shisiradhikari.com.np"
LIBRARY_URL = f"{BASE_URL}/library"

HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/2.0 (Educational Research; Shisir eLibrary)",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}

DEFAULT_IMAGE_MARKERS = (
    "/images/default-post.png",
    "/images/logo.png",
    "/images/favicon.ico",
    "/favicon",
    "/logo",
    "default-post",
    "default-image",
    "no-image",
    "placeholder",
)

DEFAULT_CONNECT_TIMEOUT = 4.0
DEFAULT_READ_TIMEOUT = 12.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY = 0.35
DEFAULT_DETAIL_WORKERS = 12
DEFAULT_CATEGORY_WORKERS = 8
DEFAULT_REQUEST_INTERVAL = 0.5
SAVE_EVERY = 1

SELECTED_CATEGORY_KEYWORDS = (
    "academic",
    "act",
    "administration",
    "annual report",
    "b.ed",
    "book",
    "budget",
    "bulletin",
    "calendar",
    "census",
    "charter",
    "circular",
    "code of ethics",
    "constitution",
    "council",
    "court",
    "ctevt",
    "department",
    "dictionary",
    "directive",
    "education",
    "election",
    "federalism",
    "form",
    "guideline",
    "health assistant",
    "health education",
    "human resource",
    "job description",
    "journal",
    "lecture",
    "license",
    "m.ed",
    "medical education commission",
    "ministry",
    "nepal parichaya",
    "nursing",
    "parliament",
    "policy",
    "public health officer",
    "public holidays",
    "public procurement",
    "question bank",
    "research",
    "salary",
    "scholarship",
    "school",
    "standard operating procedure",
    "standards",
    "statistics",
    "strategic plan",
    "strategies",
    "survey",
    "teacher",
    "training",
    "tu",
)

# Shared threading locks
save_lock = threading.Lock()
print_lock = threading.Lock()
request_lock = threading.Lock()
last_request_at = 0.0
thread_local = threading.local()


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def detect_language(text):
    return "ne" if re.search(r"[\u0900-\u097F]", text or "") else "en"


def slugify(value):
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "material"


def stable_id(category_id, material_id, title):
    digest = hashlib.sha1(f"{category_id}|{material_id}".encode("utf-8")).hexdigest()[:10]
    return f"SL-{slugify(title)[:70]}-{digest}"


def load_json(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def make_session(pool_size=DEFAULT_DETAIL_WORKERS * 2):
    session = requests.Session()
    session.headers.update(HEADERS)
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_thread_session():
    session = getattr(thread_local, "session", None)
    if session is None:
        session = make_session()
        thread_local.session = session
    return session


def request_timeout(connect_timeout=DEFAULT_CONNECT_TIMEOUT, read_timeout=DEFAULT_READ_TIMEOUT):
    return (connect_timeout, read_timeout)


def configure_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def wait_for_request_slot(interval):
    global last_request_at

    interval = max(0.0, interval)
    if interval == 0:
        return

    with request_lock:
        now = time.monotonic()
        wait_time = interval - (now - last_request_at)
        if wait_time > 0:
            time.sleep(wait_time)
        last_request_at = time.monotonic()


def extract_js_array(html, variable_name):
    pattern = rf"const\s+{re.escape(variable_name)}\s*=\s*(\[.*?\]);"
    match = re.search(pattern, html, flags=re.DOTALL)
    if not match:
        return []
    return json.loads(match.group(1))


def absolute_pdf_url(fileurl):
    if not fileurl:
        return None
    if fileurl.startswith(("http://", "https://")):
        return fileurl

    path = fileurl.lstrip("/")
    if not path.startswith("storage/"):
        path = f"storage/{path}"
    quoted_path = quote(path, safe="/:")
    return urljoin(BASE_URL, quoted_path)


def normalize_cover_url(value):
    if not value:
        return None

    cover_url = urljoin(BASE_URL, clean_text(value))
    cover_url_lower = cover_url.lower()
    if any(marker.lower() in cover_url_lower for marker in DEFAULT_IMAGE_MARKERS):
        return None
    return cover_url


def selected_category(category, all_categories=False, letter=None):
    name = clean_text(category.get("name")).lower()
    slug = clean_text(category.get("slug")).lower()

    if letter:
        if not name.startswith(letter.lower()):
            return False
        return True

    if all_categories:
        return True

    haystack = f"{name} {slug}"
    return any(keyword in haystack for keyword in SELECTED_CATEGORY_KEYWORDS)


def fetch_with_retry(
    session,
    url,
    retries=DEFAULT_RETRIES,
    delay=DEFAULT_RETRY_DELAY,
    timeout=None,
    request_interval=DEFAULT_REQUEST_INTERVAL,
):
    if timeout is None:
        timeout = request_timeout()

    retries = max(1, retries)
    for i in range(retries):
        try:
            wait_for_request_slot(request_interval)
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.content.decode("utf-8", errors="replace")
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(delay * (i + 1))


def parse_page(html):
    return {
        "categories": extract_js_array(html, "libraryCategories"),
        "materials": extract_js_array(html, "libraryMaterials"),
    }


def fetch_category_page(category, timeout, retries, request_interval):
    category_id = int(category["id"])
    url = f"{LIBRARY_URL}/{category_id}"
    html = fetch_with_retry(
        get_thread_session(),
        url,
        timeout=timeout,
        retries=retries,
        request_interval=request_interval,
    )
    return category, url, parse_page(html)


def crawl_categories(
    session,
    all_categories=True,
    letter=None,
    limit_categories=None,
    category_workers=DEFAULT_CATEGORY_WORKERS,
    timeout=None,
    retries=DEFAULT_RETRIES,
    request_interval=DEFAULT_REQUEST_INTERVAL,
):
    print("Crawling library categories...")
    root = parse_page(
        fetch_with_retry(
            session,
            LIBRARY_URL,
            timeout=timeout,
            retries=retries,
            request_interval=request_interval,
        )
    )
    queue = deque(
        {
            "id": category["id"],
            "name": category.get("name") or "",
            "slug": category.get("slug") or "",
            "parentPath": [],
            "active_materials": category.get("active_materials"),
        }
        for category in root["categories"]
        if selected_category(category, all_categories, letter)
    )

    seen_categories = set()
    category_pages = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, category_workers)) as executor:
        while queue:
            if limit_categories and len(category_pages) >= limit_categories:
                break

            batch = []
            remaining = None if not limit_categories else limit_categories - len(category_pages)
            while queue and (remaining is None or len(batch) < remaining):
                category = queue.popleft()
                category_id = int(category["id"])
                if category_id in seen_categories:
                    continue
                seen_categories.add(category_id)
                batch.append(category)

            if not batch:
                continue

            future_to_category = {
                executor.submit(
                    fetch_category_page,
                    category,
                    timeout,
                    retries,
                    request_interval,
                ): category
                for category in batch
            }

            for future in concurrent.futures.as_completed(future_to_category):
                category = future_to_category[future]
                category_id = int(category["id"])
                try:
                    category, url, page = future.result()
                except Exception as exc:
                    with print_lock:
                        print(f"  [Error] Failed category {category_id} ({category['name']}): {exc}")
                    continue

                path = [*category.get("parentPath", []), category["name"]]
                category_pages.append({
                    "id": category_id,
                    "name": category["name"],
                    "slug": category.get("slug") or "",
                    "path": path,
                    "url": url,
                    "materials": page["materials"],
                })
                selected_children = [
                    child
                    for child in page["categories"]
                    if selected_category(child, all_categories, letter)
                ]
                category_total = f"/{limit_categories}" if limit_categories else ""
                with print_lock:
                    print(
                        f"Category progress: [{len(category_pages)}{category_total}] "
                        f"{category['name']} | materials: {len(page['materials'])} | "
                        f"queued children: {len(queue) + len(selected_children)}"
                    )

                for child in selected_children:
                    queue.append({
                        "id": child["id"],
                        "name": child.get("name") or "",
                        "slug": child.get("slug") or "",
                        "parentPath": path,
                        "active_materials": child.get("active_materials"),
                    })

    return category_pages


def parse_detail_html(html, fallback_title, fallback_author):
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = fallback_title
    title_tag = soup.find("h3", class_="dchl-title")
    if title_tag:
        title = clean_text(title_tag.text)

    # Detailed metadata divs at the bottom
    published_year = None
    author = fallback_author
    page_count = None

    metadata_div = soup.find(lambda tag: tag.name == "div" and tag.find("strong") and ("Published On:" in tag.text or "Author(s)/Publisher(s):" in tag.text))
    if metadata_div:
        for row in metadata_div.find_all("div"):
            row_text = clean_text(row.text)
            if "Published On:" in row_text:
                published_year = clean_text(row_text.replace("Published On:", ""))
            elif "Author(s)/Publisher(s):" in row_text:
                author_text = clean_text(row_text.replace("Author(s)/Publisher(s):", "")).replace("©", "").strip()
                if author_text:
                    author = author_text
            elif "No of Pages:" in row_text:
                page_count = clean_text(row_text.replace("No of Pages:", ""))

    # Spans with icons (overrides or fallbacks)
    view_count = None
    download_count = None

    spans = soup.find_all("span", class_="text-nowrap")
    for span in spans:
        icon = span.find("i")
        if icon:
            icon_classes = icon.get("class", [])
            icon_class_str = " ".join(icon_classes)
            text_val = clean_text(span.text)
            if "fa-calendar" in icon_class_str and "fa-calendar-alt" not in icon_class_str:
                if not published_year and text_val:
                    published_year = text_val
            elif "fa-users" in icon_class_str:
                if not author or author == "Unknown":
                    author = text_val
            elif "fa-file" in icon_class_str:
                if not page_count:
                    page_count = text_val
            elif "fa-eye" in icon_class_str:
                view_count = text_val
            elif "fa-download" in icon_class_str:
                dl_span = span.find("span", class_="text-danger")
                if dl_span:
                    download_count = clean_text(dl_span.text)
                else:
                    # Clean up number from text
                    nums = re.findall(r"\d+", text_val)
                    if nums:
                        download_count = nums[0]

    # Description
    description = ""
    desc_div = soup.find("div", class_="text-justify")
    if desc_div:
        description = clean_text(desc_div.text)

    # File size and PDF URL
    pdf_url = None
    file_size = None

    download_a = None
    for a in soup.find_all("a", href=True):
        if "Download" in a.text:
            download_a = a
            break

    if download_a:
        pdf_url = absolute_pdf_url(download_a["href"])
        a_text = clean_text(download_a.text)
        size_match = re.search(r"\((.*?)\)", a_text)
        if size_match:
            file_size = size_match.group(1)

    viewer_div = soup.find("div", class_="_df_book")
    if viewer_div and viewer_div.get("source"):
        if not pdf_url:
            pdf_url = absolute_pdf_url(viewer_div["source"])

    # Cover image
    cover_url = None
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        cover_url = normalize_cover_url(og_image.get("content"))

    if not cover_url:
        for img in soup.find_all("img"):
            cover_url = normalize_cover_url(img.get("src") or img.get("data-src"))
            if cover_url:
                break

    return {
        "title": title,
        "author": author,
        "publishedYear": published_year,
        "pageCount": page_count,
        "description": description,
        "downloadUrl": pdf_url,
        "fileSize": file_size,
        "coverUrl": cover_url,
        "viewCount": view_count,
        "downloadCount": download_count,
    }


def process_material_details(
    session,
    category_page,
    material,
    scraped_at,
    cache_record=None,
    timeout=None,
    retries=DEFAULT_RETRIES,
    request_interval=DEFAULT_REQUEST_INTERVAL,
    fetch_details=True,
):
    category_id = category_page["id"]
    material_id = material.get("id")
    source_url = f"{LIBRARY_URL}/{category_id}/{material_id}"

    title = clean_text(material.get("name"))
    author = clean_text(material.get("author")) or "Unknown"
    pdf_url = absolute_pdf_url(material.get("fileurl"))
    cover_url = None
    published_year = clean_text(material.get("published_year")) if material.get("published_year") else None
    file_size = f"{material.get('size')} MB" if material.get("size") is not None else None
    description = clean_text(material.get("description")) if material.get("description") else ""

    # Load detail page if not cached
    if not cache_record and fetch_details:
        try:
            detail_session = session or get_thread_session()
            detail_html = fetch_with_retry(
                detail_session,
                source_url,
                timeout=timeout,
                retries=retries,
                request_interval=request_interval,
            )
            details = parse_detail_html(detail_html, title, author)
            if details["title"]:
                title = details["title"]
            if details["author"]:
                author = details["author"]
            if details["publishedYear"]:
                published_year = details["publishedYear"]
            if details["description"]:
                description = details["description"]
            if details["downloadUrl"]:
                pdf_url = details["downloadUrl"]
            if details["fileSize"]:
                file_size = details["fileSize"]
            if details["coverUrl"]:
                cover_url = normalize_cover_url(details["coverUrl"])
        except Exception as exc:
            with print_lock:
                print(f"  [Warning] Detail fetch failed for {title} ({source_url}): {exc}")
    elif cache_record:
        # Use cache
        title = cache_record.get("title") or title
        author = cache_record.get("author") or author
        published_year = cache_record.get("publishedYear") or published_year
        description = cache_record.get("description") or description
        pdf_url = cache_record.get("downloadUrl") or cache_record.get("pdfUrl") or pdf_url
        file_size = cache_record.get("fileSize") or file_size
        cover_url = normalize_cover_url(cache_record.get("coverUrl")) or cover_url

    category_name = category_page["name"]
    path = category_page["path"]
    keywords = [
         
        "E. Health Network",
        "Educational Resource",
        "Government Resource",
        category_name,
        *path,
    ]

    record = {
        "id": stable_id(category_id, material_id, title),
        "title": title,
        "author": author,
        "language": detect_language(title),
        "country": "np",
        "source": "SL",
        "sourceUrl": source_url,
        "coverUrl": cover_url,
        "category": "Course Materials",
        "libraryCategory": category_name,
        "keywords": list(dict.fromkeys(filter(None, keywords))),
        "scrapedAt": scraped_at if not cache_record else cache_record.get("scrapedAt", scraped_at),
        "downloadUrl": pdf_url,
        "readUrl": pdf_url,
        "publisher": "E. Health Network",
    }

    if published_year:
        record["publishedYear"] = published_year
    if file_size:
        record["fileSize"] = file_size
    if description:
        record["description"] = description

    return record


def scrape(
    all_categories=True,
    letter=None,
    limit_categories=None,
    limit_materials=None,
    skip_details=False,
    workers=DEFAULT_DETAIL_WORKERS,
    category_workers=DEFAULT_CATEGORY_WORKERS,
    no_cache=False,
    connect_timeout=DEFAULT_CONNECT_TIMEOUT,
    read_timeout=DEFAULT_READ_TIMEOUT,
    retries=DEFAULT_RETRIES,
    request_interval=DEFAULT_REQUEST_INTERVAL,
    save_every=SAVE_EVERY,
):
    configure_stdout()
    workers = max(1, workers)
    category_workers = max(1, category_workers)
    retries = max(1, retries)
    timeout = request_timeout(connect_timeout, read_timeout)
    pool_size = max(workers, category_workers, 1) * 2
    session = make_session(pool_size=pool_size)
    scraped_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # Load cache if possible
    cache = {}
    if not no_cache and OUTPUT_FILE.exists():
        print(f"Loading existing cache from {OUTPUT_FILE}...")
        try:
            existing = load_json(OUTPUT_FILE)
            for item in existing:
                url_parts = item.get("sourceUrl", "").rstrip("/").split("/")
                if len(url_parts) >= 2:
                    try:
                        cid = int(url_parts[-2])
                        mid = int(url_parts[-1])
                        # We only count it cached if it has a valid coverUrl or we fetched detail
                        cache[(cid, mid)] = item
                    except ValueError:
                        pass
            print(f"  Loaded {len(cache)} cached items.")
        except Exception as e:
            print(f"  Warning: Cache load failed: {e}")

    # Crawl category listings
    category_pages = crawl_categories(
        session,
        all_categories=all_categories,
        letter=letter,
        limit_categories=limit_categories,
        category_workers=category_workers,
        timeout=timeout,
        retries=retries,
        request_interval=request_interval,
    )

    print(f"Total categories fetched: {len(category_pages)}")

    # Collate materials to process
    jobs = []
    seen = set()
    for cat_page in category_pages:
        for material in cat_page["materials"]:
            if limit_materials and len(jobs) >= limit_materials:
                break
            mid = material.get("id")
            if not mid or not material.get("fileurl"):
                continue
            key = (cat_page["id"], mid)
            if key in seen:
                continue
            seen.add(key)
            jobs.append((cat_page, material))
        if limit_materials and len(jobs) >= limit_materials:
            break

    total_jobs = len(jobs)
    print(f"Total unique materials to process: {total_jobs}")

    records = []
    to_scrape = []

    # Separate cached vs uncached
    for cat_page, material in jobs:
        key = (cat_page["id"], material["id"])
        cache_item = cache.get(key)
        if cache_item and not skip_details:
            # Re-build record using cached detail fields
            records.append(
                process_material_details(
                    session,
                    cat_page,
                    material,
                    scraped_at,
                    cache_record=cache_item,
                    timeout=timeout,
                    retries=retries,
                    request_interval=request_interval,
                    fetch_details=False,
                )
            )
        else:
            to_scrape.append((cat_page, material))

    print(f"  Using cache for: {len(records)} materials")
    detail_action = "Need to build without detail requests" if skip_details else "Need to fetch detail pages for"
    print(f"  {detail_action}: {len(to_scrape)} materials")

    # Initial save of cache-matched records, if any. Avoid replacing output with []
    # when a limited test run finds no materials.
    if records:
        save_output_threadsafe(records)

    if not to_scrape:
        print("All materials loaded from cache. Done!")
        return records

    # Fetch uncached detail pages concurrently, or build records from listing data when skipped.
    work_label = "record build" if skip_details else "detail fetch"
    print(
        f"Starting {work_label} with {workers} workers "
        f"(timeout {connect_timeout:g}s connect/{read_timeout:g}s read, "
        f"{retries} attempts, {request_interval:g}s request interval)..."
    )
    completed_count = len(records)
    unsaved_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_mat = {
            executor.submit(
                process_material_details,
                None,
                cat_page,
                mat,
                scraped_at,
                None,
                timeout,
                retries,
                request_interval,
                not skip_details,
            ): (cat_page, mat)
            for cat_page, mat in to_scrape
        }

        for future in concurrent.futures.as_completed(future_to_mat):
            cat_page, mat = future_to_mat[future]
            try:
                record = future.result()
                if record:
                    records.append(record)
                    completed_count += 1
                    unsaved_count += 1
                    saved = False
                    if save_every <= 1 or unsaved_count >= save_every or completed_count == total_jobs:
                        save_output_threadsafe(records)
                        unsaved_count = 0
                        saved = True
                    percent = (completed_count / total_jobs) * 100
                    with print_lock:
                        saved_text = " | Saved!" if saved else ""
                        print(f"Progress: [{completed_count}/{total_jobs}] ({percent:.1f}%) | "
                              f"Scraped: {record['title'][:40]}... | "
                              f"Category: {record['libraryCategory']} | "
                              f"Size: {record.get('fileSize', 'Unknown')}{saved_text}")
            except Exception as exc:
                completed_count += 1
                percent = (completed_count / total_jobs) * 100
                with print_lock:
                    print(f"Progress: [{completed_count}/{total_jobs}] ({percent:.1f}%) | "
                          f"Failed: {mat.get('name', 'Unknown')[:40]}... | Error: {exc}")

    save_output_threadsafe(records)
    print(f"Finished scraping. Total records saved: {len(records)}")
    return records


def save_output_threadsafe(records_list):
    with save_lock:
        sorted_records = sorted(records_list, key=lambda item: (item.get("libraryCategory", "").lower(), item.get("title", "").lower()))
        save_json(OUTPUT_FILE, sorted_records)


def merge_all():
    sys.path.insert(0, str(ROOT / "scripts"))
    import scraper
    scraper.merge_all()


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="Scrape Shisir eLibrary materials concurrently with caching")
    parser.add_argument(
        "--all-categories",
        action="store_true",
        default=True,
        help="Scrape every library category (default)",
    )
    parser.add_argument(
        "--selected-categories",
        action="store_false",
        dest="all_categories",
        help="Scrape only categories matched by the built-in keyword list",
    )
    parser.add_argument("--limit-categories", type=int, help="Limit categories fetched")
    parser.add_argument("--limit-materials", type=int, help="Limit material records written")
    parser.add_argument("--skip-details", action="store_true", help="Do not fetch material detail pages for covers/metadata")
    parser.add_argument("--merge", action="store_true", help="Merge all source files into data/all_books.json after scrape")
    parser.add_argument("--workers", type=int, default=DEFAULT_DETAIL_WORKERS, help="Number of concurrent workers for fetching detail pages")
    parser.add_argument("--category-workers", type=int, default=DEFAULT_CATEGORY_WORKERS, help="Number of concurrent workers for category pages")
    parser.add_argument("--no-cache", action="store_true", help="Do not use existing cache file, force fetch detail pages")
    parser.add_argument("--connect-timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT, help="Seconds to wait while opening a connection")
    parser.add_argument("--read-timeout", type=float, default=DEFAULT_READ_TIMEOUT, help="Seconds to wait for a response body")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="Total request attempts before giving up")
    parser.add_argument("--request-interval", type=float, default=DEFAULT_REQUEST_INTERVAL, help="Seconds to wait between HTTP requests")
    parser.add_argument("--save-every", type=int, default=SAVE_EVERY, help="Write output after this many completed materials; default saves every material")
    parser.add_argument("--letter", type=str, help="Letter to filter categories (e.g. A, B, C)")
    args = parser.parse_args()

    scrape(
        all_categories=args.all_categories,
        letter=args.letter,
        limit_categories=args.limit_categories,
        limit_materials=args.limit_materials,
        skip_details=args.skip_details,
        workers=args.workers,
        category_workers=args.category_workers,
        no_cache=args.no_cache,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        retries=args.retries,
        request_interval=args.request_interval,
        save_every=args.save_every,
    )
    if args.merge:
        merge_all()


if __name__ == "__main__":
    main()
