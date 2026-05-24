"""
Pustakalaya Course Materials Scraper
====================================
Scrapes Course Materials collections from pustakalaya.org.
Writes one JSON file per collection under data/Course Materials/.

Usage:
  python scripts/scrape_pustakalaya_course_materials.py                # Full scrape
  python scripts/scrape_pustakalaya_course_materials.py --limit 5      # Test: 5 items per collection, no merge
  python scripts/scrape_pustakalaya_course_materials.py --skip-details  # List only, no detail pages
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
COLLECTION_DATA_DIR = os.path.join(DATA_DIR, "Course Materials")
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
        "Social Studies",
        "Social Studies [[\u0938\u093e\u092e\u093e\u091c\u093f\u0915 \u0936\u093f\u0915\u094d\u0937\u093e]]",
        231,
    ),
    (
        "Sanskrit",
        "Sanskrit [[\u0938\u0902\u0938\u094d\u0915\u0943\u0924]]",
        36,
    ),
    (
        "Sociology and Anthropology",
        "Sociology and Anthropology [[\u0938\u092e\u093e\u091c\u0936\u093e\u0938\u094d\u0924\u094d\u0930 \u0930 \u092e\u093e\u0928\u0935\u0936\u093e\u0938\u094d\u0924\u094d\u0930]]",
        155,
    ),
    (
        "Music",
        "Music [[\u0938\u0902\u0917\u0940\u0924]]",
        10,
    ),
    (
        "Science",
        "Science [[\u0935\u093f\u091c\u094d\u091e\u093e\u0928]]",
        460,
    ),
    (
        "Environmental Studies",
        "Environmental Studies [[\u0935\u093e\u0924\u093e\u0935\u0930\u0923 \u0936\u093f\u0915\u094d\u0937\u093e]]",
        75,
    ),
    (
        "Political Science and Philosophy",
        "Political Science and Philosophy [[\u0930\u093e\u0928\u091c\u0940\u0924\u093f\u0936\u093e\u0938\u094d\u0924\u094d\u0930 \u0930 \u0926\u0930\u094d\u0936\u0928\u0936\u093e\u0938\u094d\u0924\u094d\u0930]]",
        295,
    ),
    (
        "Nepali",
        "Nepali [[\u0928\u0947\u092a\u093e\u0932\u0940]]",
        510,
    ),
    (
        "Mathematics",
        "Mathematics [[\u0917\u0923\u093f\u0924]]",
        511,
    ),
    (
        "History and Culture",
        "History and Culture [[\u0907\u0924\u093f\u0939\u093e\u0938 \u0930 \u0938\u0902\u0938\u094d\u0915\u0943\u0924\u093f]]",
        174,
    ),
    (
        "Economics",
        "Economics [[\u0905\u0930\u094d\u0925\u0936\u093e\u0938\u094d\u0924\u094d\u0930]]",
        86,
    ),
    (
        "English",
        "English [[\u0905\u0919\u094d\u200d\u0917\u094d\u0930\u0947\u091c\u0940]]",
        642,
    ),
    (
        "Health and Physical Education",
        "Health and Physical Education [[\u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f \u0924\u0925\u093e \u0936\u093e\u0930\u0940\u0930\u093f\u0915 \u0936\u093f\u0915\u094d\u0937\u093e]]",
        110,
    ),
    (
        "Textbooks",
        "Textbooks [[\u092a\u093e\u0920\u094d\u092f\u092a\u0941\u0938\u094d\u0924\u0915]]",
        178,
    ),
    (
        "Occupation, Business and Technology Education",
        "Occupation, Business and Technology Education [[\u092a\u0947\u0938\u093e, \u0935\u094d\u092f\u0935\u0938\u093e\u092f \u0930 \u092a\u094d\u0930\u0935\u093f\u0927\u093f \u0936\u093f\u0915\u094d\u0937\u093e]]",
        16,
    ),
    (
        "Moral Education",
        "Moral Education [[\u0928\u0948\u0924\u093f\u0915 \u0936\u093f\u0915\u094d\u0937\u093e]]",
        10,
    ),
    (
        "Old Textbooks",
        "Old Textbooks [[\u092a\u0941\u0930\u093e\u0928\u093e \u092a\u093e\u0920\u094d\u092f\u092a\u0941\u0938\u094d\u0924\u0915]]",
        182,
    ),
    (
        "Population",
        "Population [[\u091c\u0928\u0938\u0919\u094d\u0916\u094d\u092f\u093e \u0936\u093f\u0915\u094d\u0937\u093e]]",
        25,
    ),
    (
        "Education",
        "Education [[\u0936\u093f\u0915\u094d\u0937\u093e]]",
        3,
    ),
    (
        "Geography",
        "Geography [[\u092d\u0942\u0917\u094b\u0932]]",
        7,
    ),
    (
        "Civics",
        "Civics [[\u0928\u093e\u0917\u0930\u093f\u0915 \u0936\u093e\u0938\u094d\u0924\u094d\u0930]]",
        3,
    ),
    (
        "Accounting",
        "Accounting [[\u0932\u0947\u0916\u093e]]",
        5,
    ),
    (
        "Plant Science",
        "Plant Science [[\u0935\u0928\u0938\u094d\u092a\u0924\u093f \u0935\u093f\u091c\u094d\u091e\u093e\u0928]]",
        20,
    ),
    (
        "Animal Science",
        "Animal Science [[\u092a\u0936\u0941 \u0935\u093f\u091c\u094d\u091e\u093e\u0928]]",
        22,
    ),
    (
        "Civil Engineering",
        "Civil Engineering [[\u0938\u093f\u092d\u093f\u0932 \u0907\u0928\u094d\u091c\u093f\u0928\u093f\u092f\u0930\u093f\u0919]]",
        18,
    ),
    (
        "Electrical Engineering",
        "Electrical Engineering [[\u0907\u0932\u0947\u0915\u094d\u091f\u094d\u0930\u093f\u0915\u0932 \u0907\u0928\u094d\u091c\u093f\u0928\u093f\u092f\u0930\u093f\u0919]]",
        17,
    ),
    (
        "Computer Engineering",
        "Computer Engineering [[\u0915\u092e\u094d\u092a\u094d\u092f\u0941\u091f\u0930 \u0907\u0928\u094d\u091c\u093f\u0928\u093f\u092f\u0930\u093f\u0919]]",
        19,
    ),
    (
        "E-Paath",
        "E-Paath [[\u0908\u200d-\u092a\u093e\u0920]]",
        0,
    ),
    (
        "Technical And Vocational",
        "Technical And Vocational [[\u092a\u094d\u0930\u093e\u0935\u093f\u0927\u093f\u0915 \u0930 \u0935\u094d\u092f\u093e\u0935\u0938\u093e\u092f\u093f\u0915]]",
        21,
    ),
    (
        "Our Surroundings",
        "Our Surroundings [[\u0939\u093e\u092e\u094d\u0930\u094b \u0938\u0947\u0930\u094b\u092b\u0947\u0930\u094b]]",
        43,
    ),
    (
        "Rural Development",
        "Rural Development [[\u0917\u094d\u0930\u093e\u092e\u0940\u0923 \u0935\u093f\u0915\u093e\u0938]]",
        4,
    ),
    (
        "Textbook Chapters",
        "Textbook Chapters [[\u092a\u093e\u0920\u094d\u092f\u092a\u0941\u0938\u094d\u0924\u0915\u0915\u094b \u092a\u093e\u0920]]",
        733,
    ),
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
    return f"pus_{slugify(label)}.json"


def collection_path(label):
    return os.path.join(COLLECTION_DATA_DIR, collection_filename(label))


def collection_files():
    return [
        os.path.join("Course Materials", collection_filename(label))
        for label, _, _ in COLLECTIONS
    ]


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
    os.makedirs(COLLECTION_DATA_DIR, exist_ok=True)
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
    - readUrl (direct PDF URL from the JS variable)
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
    total_new = 0
    total_detail_fetches = 0
    scraped_at = datetime.utcnow().isoformat() + "Z"
    existing_total = sum(len(load_existing(label)) for label, _, _ in COLLECTIONS)

    print("=" * 65)
    print("  Pustakalaya Course Materials Scraper")
    print(f"  Existing collection files: {existing_total} books")
    if limit:
        print(f"  Item limit per collection: {limit}")
    if skip_details:
        print("  Mode: listing only (no detail pages)")
    print(f"  Output folder: {COLLECTION_DATA_DIR}")
    print("=" * 65)

    for label, col_filter, expected_count in COLLECTIONS:
        books_dict = load_existing(label)
        print(f"\n{'─' * 60}")
        print(f"📚 {label} (~{expected_count} items)")
        print(f"{'─' * 60}")

        page = 1
        col_new = 0
        col_skipped = 0
        col_details = 0
        col_seen = 0
        seen_uuids = set()
        reported_total = None

        while True:
            url = build_search_url(col_filter, page)
            page_changed = False
            try:
                results, total = scrape_search_page(url)
            except Exception as e:
                print(f"  ❌ Page {page} error: {e}")
                break

            if not results:
                if page == 1:
                    print(f"  ⚠️  No results found! Check collection filter.")
                break

            if total and reported_total is None:
                reported_total = total
                print(f"  Server reports {reported_total} results")

            page_unique = 0
            for uuid, title, search_cover in results:
                if limit is not None and col_seen >= limit:
                    break
                if reported_total is not None and col_seen >= reported_total:
                    break
                if uuid in seen_uuids:
                    continue
                seen_uuids.add(uuid)
                page_unique += 1

                col_seen += 1
                book_id = f"pus-{uuid}"

                # Already have this book with a direct PDF read URL? Just tag it.
                if book_id in books_dict and books_dict[book_id].get("readUrl"):
                    existing_kws = books_dict[book_id].get("keywords", [])
                    if label not in existing_kws:
                        existing_kws.append(label)
                        books_dict[book_id]["keywords"] = existing_kws
                        page_changed = True
                    col_skipped += 1
                    continue

                # Build base record
                book = books_dict.get(book_id, {
                    "id": book_id,
                    "title": title,
                    "author": "Unknown",
                    "language": detect_language(title),
                    "country": "np",
                    "source": "pustakalaya-course",
                    "sourceUrl": f"{BASE}/documents/detail/{uuid}/",
                    "coverUrl": search_cover,
                    "category": "Course Materials",
                    "keywords": [label],
                    "scrapedAt": scraped_at,
                })

                # Add collection to keywords if not there
                if label not in book.get("keywords", []):
                    book.setdefault("keywords", []).append(label)

                # Fetch detail page for direct PDF read URL + rich metadata
                if not skip_details and not book.get("readUrl"):
                    total_detail_fetches += 1
                    col_details += 1
                    try:
                        detail = scrape_detail_page(uuid)
                        book.update({k: v for k, v in detail.items() if v})

                        # Merge keywords from detail with collection label
                        if "keywords" in detail:
                            merged_kw = list(set(book.get("keywords", []) + detail["keywords"]))
                            book["keywords"] = merged_kw

                        status = "✅ PDF" if detail.get("readUrl") else "⚠️  no PDF"
                        print(f"    [{col_seen}] {title[:45]:45s} {status}")
                    except Exception as e:
                        print(f"    [{col_seen}] {title[:45]:45s} ❌ {e}")

                    time.sleep(RATE_LIMIT)

                book.pop("pdfUrl", None)
                if "/documents/detail/" in book.get("readUrl", ""):
                    book.pop("readUrl", None)

                books_dict[book_id] = book
                page_changed = True
                col_new += 1
                total_new += 1

            if page_changed:
                save_books(label, books_dict)

            # Print page summary
            print(f"\n  Page {page}: {len(results)} items found, {page_unique} new, {col_seen} processed")
            if page_unique == 0:
                print(f"  No new unique items on page {page}; stopping {label}")
                break
            if limit is not None and col_seen >= limit:
                print(f"  Reached item limit ({limit}) for {label}")
                break
            if reported_total is not None and col_seen >= reported_total:
                print(f"  Reached reported result count ({reported_total}) for {label}")
                break

            page += 1
            time.sleep(RATE_LIMIT)

        # Save progress after each collection
        saved = save_books(label, books_dict)
        print(f"  ── {label}: +{col_new} new, {col_skipped} existing, {col_details} details fetched")
        print(f"  ── Dataset size: {saved} total books (saved)")

    # Final summary
    total_books = 0
    with_pdf = 0
    for label, _, _ in COLLECTIONS:
        collection_books = load_existing(label)
        total_books += len(collection_books)
        with_pdf += sum(1 for b in collection_books.values() if b.get("readUrl"))
    print(f"\n{'=' * 65}")
    print(f"  🎉 DONE!")
    print(f"  Total books across collection files: {total_books}")
    print(f"  Books with PDF links:   {with_pdf}")
    print(f"  New books this run:     {total_new}")
    print(f"  Detail pages fetched:   {total_detail_fetches}")
    print(f"  Saved under: {COLLECTION_DATA_DIR}")
    print(f"{'=' * 65}")

    return total_books


# ── Merge into all_books.json ────────────────────────────────────
def merge_all():
    """Merge all active source JSONs into one master catalog."""
    source_files = [
        "cehrd_learning.json",
        "cehrd_stories.json",
        *collection_files(),
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

    # Also pick up any other .json files in data/ that aren't already handled.
    legacy_files = {"pustakalaya_stories.json"}
    for filename in sorted(os.listdir(DATA_DIR)):
        if (
            not filename.endswith(".json")
            or filename == "all_books.json"
            or filename in source_files
            or filename in legacy_files
        ):
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

    # Pick up nested resource folders such as Literature and Arts, Reference Materials, etc.
    for root, _, files in os.walk(DATA_DIR):
        if root == DATA_DIR:
            continue
        for filename in sorted(files):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(root, filename)
            relpath = os.path.relpath(filepath, DATA_DIR)
            if relpath in source_files:
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

    with open(MERGED_FILE, "w", encoding="utf-8") as f:
        json.dump(all_books, f, ensure_ascii=False, indent=2)

    print(f"\n🔄 Merged {len(all_books)} books → {MERGED_FILE}")
    return all_books


# ── CLI ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Scrape Pustakalaya Course Materials collections"
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
