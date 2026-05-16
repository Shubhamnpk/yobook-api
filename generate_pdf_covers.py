"""
Generate real book cover images from PDF first pages.

Usage:
  python generate_pdf_covers.py --source cehrd-learning
  python generate_pdf_covers.py --source cdc-nepal --limit 10
  python generate_pdf_covers.py --input data/all_books.json --limit 5
"""

import argparse
import json
import os
import tempfile
from pathlib import Path

import fitz
import requests


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
COVERS_DIR = DATA_DIR / "covers"
SOURCE_FILES = {
    "cehrd-learning": DATA_DIR / "cehrd_learning.json",
    "cdc-nepal": DATA_DIR / "cdc_nepal.json",
    "pustakalaya": DATA_DIR / "pustakalaya.json",
    "archive-org": DATA_DIR / "archive_org.json",
    "openlibrary": DATA_DIR / "open_library.json",
}
HEADERS = {
    "User-Agent": "YoBookAPI-CoverGenerator/1.0",
    "Accept": "application/pdf,*/*",
}


def load_books(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_books(path, books):
    with path.open("w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)


def render_pdf_cover(pdf_url, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with requests.get(pdf_url, headers=HEADERS, stream=True, timeout=45) as resp:
            resp.raise_for_status()
            with tmp_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)

        doc = fitz.open(tmp_path)
        try:
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
            pix.save(output_path)
        finally:
            doc.close()
    finally:
        tmp_path.unlink(missing_ok=True)


def update_merged_catalog(updated_books):
    merged_path = DATA_DIR / "all_books.json"
    if not merged_path.exists():
        return

    updated_by_id = {book.get("id"): book for book in updated_books if book.get("id")}
    merged = load_books(merged_path)
    changed = 0

    for book in merged:
        updated = updated_by_id.get(book.get("id"))
        if updated and book.get("coverUrl") != updated.get("coverUrl"):
            book["coverUrl"] = updated.get("coverUrl")
            changed += 1

    if changed:
        save_books(merged_path, merged)
        print(f"Updated {changed} covers in {merged_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate cover images from PDF first pages")
    parser.add_argument("--source", choices=sorted(SOURCE_FILES), help="Known source JSON to update")
    parser.add_argument("--input", type=Path, help="Custom JSON file to update")
    parser.add_argument("--limit", type=int, help="Maximum number of covers to generate")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate existing local covers")
    args = parser.parse_args()

    if not args.source and not args.input:
        parser.error("Provide --source or --input")

    json_path = SOURCE_FILES[args.source] if args.source else args.input
    books = load_books(json_path)
    generated = 0
    skipped = 0
    failed = 0

    for book in books:
        if args.limit and generated >= args.limit:
            break

        book_id = book.get("id")
        pdf_url = book.get("pdfUrl")
        if not book_id or not pdf_url:
            skipped += 1
            continue

        cover_path = COVERS_DIR / f"{book_id}.jpg"
        local_cover_url = f"/covers/{cover_path.name}"

        if cover_path.exists() and not args.overwrite:
            book["coverUrl"] = local_cover_url
            skipped += 1
            continue

        try:
            print(f"Generating {book_id}...")
            render_pdf_cover(pdf_url, cover_path)
            book["coverUrl"] = local_cover_url
            generated += 1
        except Exception as exc:
            print(f"  failed: {exc}")
            failed += 1

    save_books(json_path, books)
    update_merged_catalog(books)
    print(f"Done. generated={generated}, skipped={skipped}, failed={failed}")


if __name__ == "__main__":
    main()

