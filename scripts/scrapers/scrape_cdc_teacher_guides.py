"""
CDC Teacher Guides Scraper
==========================
Scrapes teacher guides from the CDC OPAC page and writes book records in the
YoBook catalog JSON format.

The OPAC page links each record to CDC E-Library/ResourceSpace. For each
resource, this scraper looks for the "View directly in browser" URL and uses it
as both readUrl and downloadUrl. If the resource page is unavailable for older
records, it falls back to the same ResourceSpace browser-view URL pattern.

Usage:
  python scripts/scrapers/scrape_cdc_teacher_guides.py
  python scripts/scrapers/scrape_cdc_teacher_guides.py --limit 5
  python scripts/scrapers/scrape_cdc_teacher_guides.py --output "data/Teaching Materials/cdc_teacher-guides.json"
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "Teaching Materials", "cdc_teacher-guides.json")

OPAC_URL = (
    "http://202.45.146.138/catalog/opac_css/index.php"
    "?lvl=cmspage&pageid=6&id_rubrique=111"
)
OPAC_BASE = "http://lib.moecdc.gov.np/catalog/opac_css/"
ELIBRARY_BASE = "https://lib.moecdc.gov.np/elibrary/"

HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/2.0 (Educational Research; Nepal Digital Library)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}
RATE_LIMIT = 0.7


def detect_language(text):
    if re.search(r"[\u0900-\u097F]", text or ""):
        return "ne"
    return "en"


def extract_grade(text):
    if not text:
        return None

    lower = text.lower()
    word_map = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }
    roman_map = {
        "i": 1,
        "ii": 2,
        "iii": 3,
        "iv": 4,
        "v": 5,
        "vi": 6,
        "vii": 7,
        "viii": 8,
        "ix": 9,
        "x": 10,
    }

    digit_match = re.search(r"(?:grade|class|कक्षा)\s*[-:]?\s*(\d{1,2})", lower, re.I)
    if digit_match:
        return int(digit_match.group(1))

    for word, grade in word_map.items():
        if re.search(rf"\b(?:grade|class)\s+{word}\b", lower):
            return grade

    roman_match = re.search(r"\b(?:grade|class)\s+([ivx]{1,5})\b", lower)
    if roman_match and roman_match.group(1) in roman_map:
        return roman_map[roman_match.group(1)]

    nepali_digits = str.maketrans("०१२३४५६७८९", "0123456789")
    converted = text.translate(nepali_digits)
    nepali_match = re.search(r"कक्षा\s*[-:]?\s*(\d{1,2})", converted)
    if nepali_match:
        return int(nepali_match.group(1))

    return None


def education_level_for_grade(grade):
    if grade is None:
        return None
    if grade <= 5:
        return "Primary"
    if grade <= 8:
        return "Middle"
    if grade <= 10:
        return "Secondary"
    return "Higher Secondary"


def normalize_page_count(value):
    if not value:
        return None
    match = re.search(r"\d+", value)
    return match.group(0) if match else value.strip()


def normalize_author(value):
    if not value:
        return "Curriculum Development Centre (CDC)"
    value = re.sub(r"\s*,\s*Author\b", "", value).strip()
    value = re.sub(r"\s*;\s*", "; ", value)
    return value or "Curriculum Development Centre (CDC)"


def normalize_publisher(value):
    if not value:
        return "Curriculum Development Centre"
    if ":" in value:
        value = value.split(":", 1)[1]
    return value.strip() or "Curriculum Development Centre"


def extract_elibrary_ref(url):
    if not url:
        return None
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if params.get("r"):
        return params["r"][0]
    if params.get("ref"):
        return params["ref"][0]
    match = re.search(r"[?&](?:r|ref)=(\d+)", url)
    return match.group(1) if match else None


def browser_pdf_url(ref):
    return (
        f"{ELIBRARY_BASE}pages/download.php"
        f"?direct=1&noattach=true&ref={ref}&ext=pdf&k="
    )


def fetch_soup(session, url):
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml"), response.url


def extract_cover_url(child):
    if not child:
        return None

    img = child.select_one("img.vignetteimg, img.vignetteNot, img")
    if not img:
        return None

    for attr in ("vigurl", "src"):
        value = img.get(attr)
        if not value:
            continue
        match = re.search(r"vigurl=([^&]+)", value)
        if match:
            return unquote(match.group(1))
        if value.startswith("http"):
            return value
        return urljoin(OPAC_BASE, value)

    return None


def extract_public_metadata(child, notice_id):
    metadata = {}
    if not child:
        return metadata

    scope = child.select_one(f"#div_public{notice_id}") or child
    for row in scope.select("tr"):
        label = row.select_one(".etiq_champ")
        value = row.select_one(".public_line_value")
        if not label or not value:
            continue
        key = label.get_text(" ", strip=True).strip(":").strip()
        metadata[key] = value.get_text(" ", strip=True)

    return metadata


def extract_keywords(metadata):
    raw = metadata.get("Keywords") or ""
    keywords = []
    for item in re.split(r"\s{2,}|;|\|", raw):
        item = item.strip(" \u00a0")
        if item and item not in keywords:
            keywords.append(item)

    for item in ("Teacher's Guide", "Teaching Manual", "CDC Library"):
        if item not in keywords:
            keywords.append(item)

    return keywords


def extract_browser_view_url(session, elibrary_url, ref):
    """Return the ResourceSpace 'View directly in browser' URL when available."""
    if not ref:
        return None

    fallback = browser_pdf_url(ref)

    try:
        soup, _ = fetch_soup(session, elibrary_url)
    except requests.RequestException:
        return fallback

    text = soup.get_text(" ", strip=True).lower()
    if "resource not found" in text:
        return fallback

    for link in soup.find_all("a", href=True):
        href = link["href"]
        label = link.get_text(" ", strip=True).lower()
        if "download.php" not in href:
            continue
        if "direct=1" in href and "noattach=true" in href:
            return urljoin(ELIBRARY_BASE, href)
        if "view in browser" in label:
            return urljoin(ELIBRARY_BASE, href)

    heading = soup.find(["h1", "h2", "h3"], string=re.compile("View directly in browser", re.I))
    if heading:
        next_link = heading.find_next("a", href=True)
        if next_link:
            return urljoin(ELIBRARY_BASE, next_link["href"])

    return fallback


def parse_opac_records(session):
    soup, _ = fetch_soup(session, OPAC_URL)
    records = []
    seen = set()

    for parent in soup.select("div.notice-parent"):
        notice_id = re.sub(r"\D", "", parent.get("id", ""))
        if not notice_id:
            continue

        title_el = parent.select_one(".header_title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        link_el = parent.select_one('a[type="external_url_notice"], span.notice_link a[href]')
        elibrary_url = link_el.get("href") if link_el else ""
        ref = extract_elibrary_ref(elibrary_url)
        if not title or not ref:
            continue

        dedupe_key = (ref, re.sub(r"\s+", " ", title).strip().lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        child = soup.select_one(f"#el{notice_id}Child")
        metadata = extract_public_metadata(child, notice_id)
        cover_url = extract_cover_url(child)

        records.append(
            {
                "noticeId": notice_id,
                "resourceRef": ref,
                "title": title,
                "elibraryUrl": elibrary_url,
                "metadata": metadata,
                "coverUrl": cover_url,
            }
        )

    return records


def build_book(record, scraped_at, session):
    title = record["title"]
    metadata = record["metadata"]
    ref = record["resourceRef"]
    grade = extract_grade(" ".join([title, metadata.get("Keywords", "")]))
    pdf_url = extract_browser_view_url(session, record["elibraryUrl"], ref)

    book = {
        "id": f"cdc-library-teachers-guide-r{ref}",
        "title": title,
        "author": normalize_author(metadata.get("Authors")),
        "language": detect_language(" ".join([title, metadata.get("Languages", "")])),
        "country": "np",
        "source": "cdc-library",
        "sourceUrl": f"{OPAC_BASE}index.php?lvl=notice_display&id={record['noticeId']}",
        "coverUrl": record.get("coverUrl") or "",
        "category": "Teaching Materials",
        "keywords": extract_keywords(metadata),
        "scrapedAt": scraped_at,
        "readUrl": pdf_url,
        "publisher": normalize_publisher(metadata.get("Publisher")),
    }

    page_count = normalize_page_count(metadata.get("Pagination"))
    if page_count:
        book["pageCount"] = page_count

    if grade is not None:
        book["grade"] = str(grade)
        book["educationLevel"] = education_level_for_grade(grade)

    description = metadata.get("General note")
    if description:
        book["description"] = description
    else:
        book["description"] = f"Teacher's guide from CDC Library resource {ref}."

    # The user-facing browser URL is also the best download URL for these items.
    book["downloadUrl"] = pdf_url

    return book


def save_books(books, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(books)} teacher guides -> {output_path}")


def safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"))


def main():
    parser = argparse.ArgumentParser(description="Scrape CDC OPAC teacher guides.")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Output JSON file path")
    parser.add_argument("--limit", type=int, help="Only scrape the first N OPAC records")
    parser.add_argument("--rate-limit", type=float, default=RATE_LIMIT, help="Delay between e-library requests")
    args = parser.parse_args()

    session = requests.Session()
    scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    records = parse_opac_records(session)
    if args.limit:
        records = records[: args.limit]

    books = []
    for index, record in enumerate(records, start=1):
        safe_print(f"[{index}/{len(records)}] {record['resourceRef']} {record['title']}")
        books.append(build_book(record, scraped_at, session))
        time.sleep(args.rate_limit)

    save_books(books, os.path.abspath(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
