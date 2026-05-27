"""
Add official NCERT textbook cover image URLs to the NCERT catalog.

NCERT's textbook viewer loads cover images from:
  https://ncert.nic.in/textbook/pdf/<book-code>cc.jpg

The <book-code> is the same prefix used by the ZIP URL:
  https://ncert.nic.in/textbook/pdf/leph1dd.zip -> leph1

Usage:
  python scripts/scrape_ncert_cover_images.py
  python scripts/scrape_ncert_cover_images.py --limit 10
  python scripts/scrape_ncert_cover_images.py --skip-validate
"""

import argparse
import json
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
NCERT_JSON = ROOT / "data" / "Course Materials" / "ncert_textbooks.json"
NCERT_PDF_BASE = "https://ncert.nic.in/textbook/pdf"
HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/1.0 (Educational Research; NCERT Cover Images)",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


def load_books(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_books(path, books):
    with path.open("w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)


def book_code_from_zip_url(zip_url):
    if not zip_url:
        return None

    filename = zip_url.rsplit("/", 1)[-1]
    if not filename.endswith("dd.zip"):
        return None

    return filename[: -len("dd.zip")]


def official_cover_url(book_code):
    return f"{NCERT_PDF_BASE}/{book_code}cc.jpg"


def is_image_url(session, url):
    response = session.head(url, allow_redirects=True, timeout=20)
    if response.status_code != 200:
        return False

    return response.headers.get("content-type", "").lower().startswith("image/")


def main():
    parser = argparse.ArgumentParser(description="Scrape official NCERT cover image URLs")
    parser.add_argument("--input", type=Path, default=NCERT_JSON, help="NCERT JSON file to update")
    parser.add_argument("--limit", type=int, help="Maximum records to process")
    parser.add_argument("--skip-validate", action="store_true", help="Do not HEAD-check cover URLs")
    args = parser.parse_args()

    books = load_books(args.input)
    session = requests.Session()
    session.headers.update(HEADERS)

    updated = 0
    skipped = 0
    failed = 0

    for book in books:
        if args.limit and updated >= args.limit:
            break

        book_code = book_code_from_zip_url(book.get("zipUrl"))
        if not book_code:
            skipped += 1
            continue

        cover_url = official_cover_url(book_code)

        if not args.skip_validate:
            try:
                if not is_image_url(session, cover_url):
                    print(f"Missing cover: {book.get('id')} -> {cover_url}")
                    failed += 1
                    continue
            except Exception as exc:
                print(f"Cover check failed: {book.get('id')} -> {exc}")
                failed += 1
                continue

        if book.get("coverUrl") == cover_url and book.get("coverSource") == "ncert-official":
            skipped += 1
            continue

        book["coverUrl"] = cover_url
        book["coverSource"] = "ncert-official"
        book["coverSourceUrl"] = book.get("sourceUrl") or "https://ncert.nic.in/textbook.php"
        updated += 1

    save_books(args.input, books)
    print(f"Done. updated={updated}, skipped={skipped}, failed={failed}")


if __name__ == "__main__":
    main()
