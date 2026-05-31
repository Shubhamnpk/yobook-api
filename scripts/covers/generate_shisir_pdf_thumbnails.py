"""
Generate first-page thumbnails for Shisir PDF records.

This script does not edit the scraper or the source JSON data. It reads the
Shisir JSON files, downloads each PDF, renders page 1 as a JPG, and writes a
manifest so progress is saved after every record.

Usage:
  python scripts/covers/generate_shisir_pdf_thumbnails.py --limit 20
  python scripts/covers/generate_shisir_pdf_thumbnails.py --workers 8
  python scripts/covers/generate_shisir_pdf_thumbnails.py --force
"""

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import threading
import time
from io import BytesIO
from pathlib import Path

import fitz
import requests
from PIL import Image
from requests.utils import requote_uri

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "shisir_pdf_thumbnails"
MANIFEST_PATH = DATA_DIR / "shisir_pdf_thumbnails.json"
DEFAULT_JSON_PATHS = [
    DATA_DIR / "Acts" / "shisir_government.json",
    DATA_DIR / "Course Materials" / "shisir_library_materials.json",
    DATA_DIR / "Course Materials" / "shisir_question_papers.json",
    DATA_DIR / "Other Educational Materials" / "shisir_forms_and_formats.json",
]


manifest_lock = threading.Lock()
print_lock = threading.Lock()


def configure_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def slugify(value, fallback):
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return text[:90] or fallback


def record_key(record):
    raw = record.get("id") or record.get("downloadUrl") or record.get("pdfUrl") or record.get("title") or ""
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def output_path_for(record):
    key = record_key(record)
    title_slug = slugify(record.get("title"), "shisir-pdf")
    return OUTPUT_DIR / f"{title_slug}-{key}.jpg"


def collect_records(json_paths):
    records = []
    seen = set()
    for json_path in json_paths:
        if not json_path.exists():
            continue
        data = load_json(json_path)
        if not isinstance(data, list):
            continue
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            pdf_url = item.get("downloadUrl") or item.get("pdfUrl") or item.get("readUrl")
            if not isinstance(pdf_url, str) or not pdf_url.strip():
                continue
            key = item.get("id") or pdf_url
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "sourceJson": str(json_path.relative_to(ROOT)),
                    "sourceIndex": index,
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "downloadUrl": pdf_url.strip(),
                    "existingCoverUrl": item.get("coverUrl"),
                }
            )
    return records


def download_pdf(url, timeout):
    response = requests.get(
        requote_uri(url),
        headers={"User-Agent": "book-api-thumbnail-generator/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    content = response.content
    if not content.startswith(b"%PDF") and "pdf" not in content_type.lower():
        raise ValueError(f"response does not look like a PDF: {content_type or 'unknown content-type'}")
    return content


def render_first_page(pdf_bytes, output_path, width, quality):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count < 1:
        raise ValueError("PDF has no pages")

    page = doc.load_page(0)
    zoom = max(1.0, width / page.rect.width)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.open(BytesIO(pix.tobytes("png")))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=quality, optimize=True)
    doc.close()
    return image.size


def process_record(record, args):
    output_path = output_path_for(record)
    rel_output = str(output_path.relative_to(ROOT))
    if output_path.exists() and not args.force:
        return {
            **record,
            "status": "skipped",
            "thumbnailPath": rel_output,
            "reason": "thumbnail already exists",
            "processedAt": int(time.time()),
        }

    pdf_bytes = download_pdf(record["downloadUrl"], args.timeout)
    width, height = render_first_page(pdf_bytes, output_path, args.width, args.quality)
    return {
        **record,
        "status": "ok",
        "thumbnailPath": rel_output,
        "thumbnailWidth": width,
        "thumbnailHeight": height,
        "thumbnailSize": output_path.stat().st_size,
        "pdfBytesDownloaded": len(pdf_bytes),
        "processedAt": int(time.time()),
    }


def main():
    global OUTPUT_DIR
    configure_stdout()
    parser = argparse.ArgumentParser(description="Generate first-page thumbnails for Shisir PDFs")
    parser.add_argument("--json", action="append", type=Path, help="Specific Shisir JSON file; can be repeated")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, help="Process only the first N pending records")
    parser.add_argument("--width", type=int, default=700, help="Rendered thumbnail width in pixels")
    parser.add_argument("--quality", type=int, default=86, help="JPEG quality")
    parser.add_argument("--timeout", type=int, default=45, help="Request timeout in seconds")
    parser.add_argument("--force", action="store_true", help="Regenerate existing thumbnails")
    parser.add_argument("--dry-run", action="store_true", help="Show records without downloading PDFs")
    args = parser.parse_args()

    OUTPUT_DIR = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir

    json_paths = [p if p.is_absolute() else ROOT / p for p in args.json] if args.json else DEFAULT_JSON_PATHS
    records = collect_records(json_paths)
    if args.limit:
        records = records[: args.limit]

    print(f"Shisir PDF records found: {len(records)}")
    print(f"Output folder: {OUTPUT_DIR.relative_to(ROOT)}")
    print(f"Manifest: {(args.manifest if args.manifest.is_absolute() else ROOT / args.manifest).relative_to(ROOT)}")

    if args.dry_run:
        for record in records[:20]:
            print(f"  {record.get('id') or record['downloadUrl']} | {record.get('title')}")
        if len(records) > 20:
            print(f"  ... {len(records) - 20} more")
        return

    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    manifest = {}
    if manifest_path.exists():
        manifest = load_json(manifest_path)

    total = len(records)
    ok = skipped = failed = 0

    def handle_done(future, record_number):
        nonlocal ok, skipped, failed, manifest
        key = record_key(future.record)
        try:
            result = future.result()
            if result["status"] == "ok":
                ok += 1
            else:
                skipped += 1
        except Exception as exc:
            failed += 1
            result = {
                **future.record,
                "status": "error",
                "error": str(exc),
                "processedAt": int(time.time()),
            }

        with manifest_lock:
            manifest[key] = result
            save_json(manifest_path, manifest)

        with print_lock:
            label = result.get("title") or result.get("id") or result.get("downloadUrl")
            print(f"[{record_number}/{total}] {result['status']}: {label}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = []
        for number, record in enumerate(records, start=1):
            future = executor.submit(process_record, record, args)
            future.record = record
            future.number = number
            futures.append(future)

        for future in concurrent.futures.as_completed(futures):
            handle_done(future, future.number)

    print(f"Done. ok={ok}, skipped={skipped}, failed={failed}")
    print(f"Thumbnails: {OUTPUT_DIR.relative_to(ROOT)}")
    print(f"Manifest: {manifest_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
