"""
Pustakalaya Literature & Arts Scraper
=====================================
Scrapes all 9 Literature & Arts collections from pustakalaya.org.

Usage:
  python scripts/scrape_pustakalaya_literature.py                # Full scrape
  python scripts/scrape_pustakalaya_literature.py --limit 5      # Test: 5 items per collection, no merge
  python scripts/scrape_pustakalaya_literature.py --skip-details  # List only, no detail pages
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin, quote, unquote

import requests
from bs4 import BeautifulSoup

# ── Paths ────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
MERGED_FILE = os.path.join(DATA_DIR, "all_books.json")

HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/2.0 (Educational Research; Nepal Digital Library)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}
RATE_LIMIT = 1.2  # seconds between requests
BASE = "https://pustakalaya.org"

# ── Collections ──────────────────────────────────────────────────
# Using the exact encoded URLs the user provided — decoded into
# (label, collection_filter_string) pairs.
COLLECTIONS = [
    (
        "Nepali Literature",
        "Nepali Literature [[\u0928\u0947\u092a\u093e\u0932\u0940 \u0938\u093e\u0939\u093f\u0924\u094d\u092f]]",
        700,
    ),
    (
        "Nepali Children\u2019s Literature",
        "Nepali Children\u2019s Literature [[\u0928\u0947\u092a\u093e\u0932\u0940 \u092c\u093e\u0932 \u0938\u093e\u0939\u093f\u0924\u094d\u092f]]",
        754,
    ),
    (
        "Literature in Other Nepali Languages",
        "Literature in Other Nepali Languages [[\u0928\u0947\u092a\u093e\u0932\u0915\u093e \u0905\u0928\u094d\u092f \u092d\u093e\u0937\u093e\u0915\u093e \u0938\u093e\u0939\u093f\u0924\u094d\u092f]]",
        194,
    ),
    (
        "English Literature",
        "English Literature [[\u0905\u0919\u094d\u200d\u0917\u094d\u0930\u0947\u091c\u0940 \u0938\u093e\u0939\u093f\u0924\u094d\u092f]]",
        1599,
    ),
    (
        "Inspirational Materials",
        "Inspirational Materials [[\u092a\u094d\u0930\u0947\u0930\u0915 \u0938\u093e\u092e\u0917\u094d\u0930\u0940]]",
        14,
    ),
    (
        "Traditional Art",
        "Traditional Art [[\u092a\u0930\u092e\u094d\u092a\u0930\u093e\u0917\u0924 \u0915\u0932\u093e\u0915\u0943\u0924\u093f]]",
        33,
    ),
    (
        "Do It Yourself",
        "Do It Yourself [[\u0906\u092b\u0948\u0901 \u0917\u0930\u094d\u0928\u0941\u0939\u094b\u0938\u094d]]",
        39,
    ),
    (
        "English Children\u2019s Literature",
        "English Children\u2019s Literature [[\u0905\u0919\u094d\u200d\u0917\u094d\u0930\u0947\u091c\u0940 \u092c\u093e\u0932 \u0938\u093e\u0939\u093f\u0924\u094d\u092f]]",
        1122,
    )
]


# ── Helpers ──────────────────────────────────────────────────────
def detect_language(text):
    if re.search(r"[\u0900-\u097F]", text):
        return "ne"
    return "en"


def slugify(value):
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-") or "collection"


def collection_filename(label):
    return f"pustakalaya_literature_{slugify(label)}.json"


def collection_path(label):
    return os.path.join(DATA_DIR, collection_filename(label))


def collection_files():
    return [collection_filename(label) for label, _, _ in COLLECTIONS]


def build_search_url(collection_filter, page=1):
    """Build the exact search URL for a collection page."""
    filter_obj = {
        "type": [],
        "languages": [],
        "education_levels": [],
        "communities": [],
        "collections": [collection_filter],
        "keywords": [],
        "license_type": [],
    }
    return f"{BASE}/en/search/?q=&form-filter={quote(json.dumps(filter_obj))}&searchIn=all&page={page}"


def load_existing(label):
    """Load existing scraped data for a collection."""
    path = collection_path(label)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {b["id"]: b for b in data}
    return {}


def save_books(label, books_dict):
    """Save current collection state to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    books = list(books_dict.values())
    with open(collection_path(label), "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)
    return len(books)


def extract_result_count(soup):
    """Try to extract '754 results' from the page text."""
    text = soup.get_text()
    match = re.search(r"(\d+)\s*results", text, re.I)
    if match:
        return int(match.group(1))
    return None


# ── Search Page Scraper ──────────────────────────────────────────
def scrape_search_page(url):
    """
    Scrape one search results page.
    Returns list of (uuid, title) tuples found on this page.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    results = []
    seen_on_page = set()

    for link in soup.find_all("a", href=re.compile(r"/documents/detail/[a-f0-9-]+")):
        title = link.get_text(strip=True)
        href = link.get("href", "")
        uuid_match = re.search(r"detail/([a-f0-9-]+)", href)

        if not uuid_match or not title or len(title) < 3:
            continue
        if title.lower() in ("read", "document", ""):
            continue

        uuid = uuid_match.group(1)
        if uuid in seen_on_page:
            continue
        seen_on_page.add(uuid)

        # Try to grab thumbnail from the same row/card
        cover_url = None
        parent = link.find_parent("div", class_="col-md-2") or \
                 link.find_parent("div", class_="grid-book-cont") or \
                 link.find_parent("div", class_="row")
        if parent:
            img = parent.find("img")
            if img and img.get("src"):
                src = img["src"]
                cover_url = src if src.startswith("http") else f"{BASE}{src}"

        results.append((uuid, title, cover_url))

    total = extract_result_count(soup)
    return results, total


# ── Detail Page Scraper ──────────────────────────────────────────
def scrape_detail_page(uuid):
    """
    Fetch a single book's detail page and extract:
    - pdfUrl/readUrl (from the JS variable)
    - cover image (from det-img-cont)
    - metadata table (author, illustrator, editor, publisher, pages, language, keywords)
    - description
    """
    url = f"{BASE}/documents/detail/{uuid}/"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    detail = {}

    # ── PDF URL from JS ──
    pdf_match = re.search(r"pdfUrl\s*=\s*['\"](.+?)['\"]", resp.text)
    if pdf_match:
        pdf_url = urljoin(BASE, pdf_match.group(1))
        detail["pdfUrl"] = pdf_url
        detail["readUrl"] = pdf_url

    # ── Cover from detail image container ──
    img_div = soup.find("div", class_="det-img-cont")
    if img_div:
        img = img_div.find("img")
        if img and img.get("src"):
            detail["coverUrl"] = urljoin(BASE, img["src"])

    # ── File size ──
    size_p = soup.find("p", class_="f16")
    if size_p:
        size_text = size_p.get_text(strip=True)
        if "MB" in size_text or "KB" in size_text:
            detail["fileSize"] = size_text.replace("File size:", "").strip()

    # ── Metadata table ──
    table = soup.find("table", class_="acc_table") or soup.find("table")
    if table:
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            key = th.get_text(strip=True).rstrip(":").lower()
            val = td.get_text(" ", strip=True)

            if "author" in key:
                authors = [a.get_text(strip=True) for a in td.find_all("a")]
                detail["author"] = ", ".join(authors) if authors else val
            elif "illustrator" in key:
                detail["illustrator"] = val
            elif "editor" in key:
                detail["editor"] = val
            elif "publisher" in key:
                detail["publisher"] = val
            elif "total pages" in key or "pages" in key:
                detail["pageCount"] = val
            elif "language" in key:
                if "\u0928\u0947\u092a\u093e\u0932\u0940" in val:
                    detail["language"] = "ne"
                elif "english" in val.lower():
                    detail["language"] = "en"
                else:
                    detail["languageRaw"] = val
            elif "education" in key:
                detail["educationLevel"] = val
            elif "keyword" in key:
                kws = [a.get_text(strip=True) for a in td.find_all("a")]
                if kws:
                    detail["keywords"] = kws

    # ── Description ──
    desc_p = soup.find("p", class_="acc_paragraph")
    if desc_p:
        text = desc_p.get_text(strip=True)
        if text:
            detail["description"] = text

    return detail


# ── Main Scraper ─────────────────────────────────────────────────
def run(limit=None, skip_details=False):
    books_dict = load_existing()
    total_new = 0
    total_detail_fetches = 0
    scraped_at = datetime.utcnow().isoformat() + "Z"

    print("=" * 65)
    print("  Pustakalaya Literature & Arts Scraper")
    print(f"  Existing dataset: {len(books_dict)} books")
    if limit:
        print(f"  Item limit per collection: {limit}")
    if skip_details:
        print("  Mode: listing only (no detail pages)")
    print("=" * 65)

    for label, col_filter, expected_count in COLLECTIONS:
        print(f"\n{'─' * 60}")
        print(f"📚 {label} (~{expected_count} items)")
        print(f"{'─' * 60}")

        page = 1
        col_new = 0
        col_skipped = 0
        col_details = 0
        col_seen = 0

        while True:
            url = build_search_url(col_filter, page)
            try:
                results, total = scrape_search_page(url)
            except Exception as e:
                print(f"  ❌ Page {page} error: {e}")
                break

            if not results:
                if page == 1:
                    print(f"  ⚠️  No results found! Check collection filter.")
                break

            if page == 1 and total:
                print(f"  Server reports {total} results")

            for uuid, title, search_cover in results:
                if limit is not None and col_seen >= limit:
                    break

                col_seen += 1
                book_id = f"pustakalaya-{uuid}"

                # Already have this book with PDF? Just tag it.
                if book_id in books_dict and books_dict[book_id].get("pdfUrl"):
                    books_dict[book_id]["readUrl"] = books_dict[book_id]["pdfUrl"]
                    existing_kws = books_dict[book_id].get("keywords", [])
                    if label not in existing_kws:
                        existing_kws.append(label)
                        books_dict[book_id]["keywords"] = existing_kws
                    col_skipped += 1
                    continue

                # Build base record
                book = books_dict.get(book_id, {
                    "id": book_id,
                    "title": title,
                    "author": "Unknown",
                    "language": detect_language(title),
                    "country": "np",
                    "source": "pustakalaya-stories",
                    "sourceUrl": f"{BASE}/documents/detail/{uuid}/",
                    "readUrl": f"{BASE}/documents/detail/{uuid}/",
                    "coverUrl": search_cover,
                    "category": "Story",
                    "keywords": [label],
                    "scrapedAt": scraped_at,
                })

                # Add collection to keywords if not there
                if label not in book.get("keywords", []):
                    book.setdefault("keywords", []).append(label)

                # Fetch detail page for PDF URL + rich metadata
                if not skip_details and not book.get("pdfUrl"):
                    total_detail_fetches += 1
                    col_details += 1
                    try:
                        detail = scrape_detail_page(uuid)
                        book.update({k: v for k, v in detail.items() if v})

                        # Merge keywords from detail with collection label
                        if "keywords" in detail:
                            merged_kw = list(set(book.get("keywords", []) + detail["keywords"]))
                            book["keywords"] = merged_kw

                        status = "✅ PDF" if detail.get("pdfUrl") else "⚠️  no PDF"
                        sys.stdout.write(f"\r    [{total_detail_fetches}] {title[:45]:45s} {status}")
                        sys.stdout.flush()
                    except Exception as e:
                        sys.stdout.write(f"\r    [{total_detail_fetches}] {title[:45]:45s} ❌ {e}")
                        sys.stdout.flush()

                    time.sleep(RATE_LIMIT)

                books_dict[book_id] = book
                col_new += 1
                total_new += 1

            # Print page summary
            print(f"\n  Page {page}: {len(results)} items found, {col_seen} processed")
            if limit is not None and col_seen >= limit:
                print(f"  Reached item limit ({limit}) for {label}")
                break

            page += 1
            time.sleep(RATE_LIMIT)

        # Save progress after each collection
        saved = save_books(books_dict)
        print(f"  ── {label}: +{col_new} new, {col_skipped} existing, {col_details} details fetched")
        print(f"  ── Dataset size: {saved} total books (saved)")

    # Final summary
    total_books = save_books(books_dict)
    with_pdf = sum(1 for b in books_dict.values() if b.get("pdfUrl"))
    print(f"\n{'=' * 65}")
    print(f"  🎉 DONE!")
    print(f"  Total books in dataset: {total_books}")
    print(f"  Books with PDF links:   {with_pdf}")
    print(f"  New books this run:     {total_new}")
    print(f"  Detail pages fetched:   {total_detail_fetches}")
    print(f"  Saved to: {OUTPUT_FILE}")
    print(f"{'=' * 65}")

    return books_dict


# ── Merge into all_books.json ────────────────────────────────────
def merge_all():
    """Merge all active source JSONs into one master catalog."""
    source_files = [
        "cehrd_learning.json",
        "cehrd_stories.json",
        "pustakalaya_stories.json",
        "cehrd_nfe.json",
        "cehrd_audio.json",
    ]
    all_books = []
    seen_ids = set()

    for filename in source_files:
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for book in data:
                    bid = book.get("id")
                    if bid and bid not in seen_ids:
                        seen_ids.add(bid)
                        all_books.append(book)
        except Exception:
            pass

    # Also pick up any other .json files in data/ that aren't already handled
    for filename in sorted(os.listdir(DATA_DIR)):
        if not filename.endswith(".json") or filename == "all_books.json" or filename in source_files:
            continue
        filepath = os.path.join(DATA_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for book in data:
                    bid = book.get("id")
                    if bid and bid not in seen_ids:
                        seen_ids.add(bid)
                        all_books.append(book)
        except Exception:
            pass

    with open(MERGED_FILE, "w", encoding="utf-8") as f:
        json.dump(all_books, f, ensure_ascii=False, indent=2)

    print(f"\n🔄 Merged {len(all_books)} books → {MERGED_FILE}")
    return all_books


# ── CLI ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Scrape Pustakalaya Literature & Arts collections"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max number of search result items to process per collection (for testing)"
    )
    parser.add_argument(
        "--skip-details", action="store_true",
        help="Only scrape search result listings, skip detail pages"
    )
    parser.add_argument(
        "--no-merge", action="store_true",
        help="Skip merging into all_books.json"
    )
    parser.add_argument(
        "--merge-test", action="store_true",
        help="Allow merging into all_books.json even when --limit is used"
    )
    args = parser.parse_args()

    run(limit=args.limit, skip_details=args.skip_details)

    is_test_run = args.limit is not None
    should_merge = not args.no_merge and (not is_test_run or args.merge_test)
    if should_merge:
        merge_all()
    elif is_test_run:
        print("\nTest run detected (--limit): skipped merge into all_books.json")


if __name__ == "__main__":
    main()
