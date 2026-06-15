"""
Upload generated Shisir PDF thumbnails to ImgBB and update coverUrl values.

This script uses data/shisir_pdf_thumbnails.json as the source manifest. It
uploads thumbnails from data/shisir_pdf_thumbnails, saves upload progress after
each image, then replaces coverUrl in the matching Shisir JSON records.

Usage:
  $env:IMGBB_API_KEY = "your-key"
  python scripts/uploads/upload_shisir_thumbnails_to_imgbb.py --dry-run
  python scripts/uploads/upload_shisir_thumbnails_to_imgbb.py --workers 6
"""

import argparse
import concurrent.futures
import json
import os
import sys
import threading
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
METADATA_DIR = ROOT / "metadata"
SOURCE_MANIFEST_PATH = DATA_DIR / "shisir_pdf_thumbnails.json"
UPLOAD_MANIFEST_PATH = METADATA_DIR / "shisir_imgbb_uploads.json"
UPLOAD_URL = "https://api.imgbb.com/1/upload"


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


def collect_upload_items(source_manifest):
    items = []
    for key, item in source_manifest.items():
        if item.get("status") not in {"ok", "skipped"}:
            continue
        thumbnail_path = item.get("thumbnailPath")
        record_id = item.get("id")
        if not thumbnail_path or not record_id:
            continue
        image_path = ROOT / thumbnail_path
        if not image_path.exists():
            continue
        items.append(
            {
                "manifestKey": key,
                "id": record_id,
                "title": item.get("title"),
                "sourceJson": item.get("sourceJson"),
                "sourceIndex": item.get("sourceIndex"),
                "thumbnailPath": str(image_path.relative_to(ROOT)),
                "existingCoverUrl": item.get("existingCoverUrl"),
            }
        )
    return items


def upload_image(api_key, image_path, name, expiration, timeout):
    params = {"key": api_key}
    data = {"name": name}
    if expiration:
        data["expiration"] = str(expiration)

    with image_path.open("rb") as image_file:
        response = requests.post(
            UPLOAD_URL,
            params=params,
            data=data,
            files={"image": image_file},
            timeout=timeout,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code} {response.text[:500]}")
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload)
    return payload["data"]


def upload_item(item, args):
    image_path = ROOT / item["thumbnailPath"]
    uploaded = upload_image(
        args.api_key,
        image_path,
        image_path.stem,
        args.expiration,
        args.timeout,
    )
    return {
        **item,
        "status": "ok",
        "url": uploaded.get("url"),
        "displayUrl": uploaded.get("display_url"),
        "viewerUrl": uploaded.get("url_viewer"),
        "deleteUrl": uploaded.get("delete_url"),
        "width": uploaded.get("width"),
        "height": uploaded.get("height"),
        "size": uploaded.get("size"),
        "uploadedAt": int(time.time()),
    }


def update_json_records(upload_manifest):
    by_id = {
        item["id"]: item["url"]
        for item in upload_manifest.values()
        if item.get("status") == "ok" and item.get("id") and item.get("url")
    }
    changed_files = {}
    for json_path in sorted(DATA_DIR.glob("**/shisir*.json")):
        if json_path.name in {"shisir_pdf_thumbnails.json", "shisir_imgbb_uploads.json", "shisir_non_pdf_thumbnail_failures.json"}:
            continue
        data = load_json(json_path)
        if not isinstance(data, list):
            continue
        changed = 0
        for record in data:
            if not isinstance(record, dict):
                continue
            hosted_url = by_id.get(record.get("id"))
            if hosted_url and record.get("coverUrl") != hosted_url:
                record["coverUrl"] = hosted_url
                changed += 1
        if changed:
            save_json(json_path, data)
            changed_files[str(json_path.relative_to(ROOT))] = changed
    return changed_files


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="Upload Shisir PDF thumbnails to ImgBB")
    parser.add_argument("--api-key", default=os.environ.get("IMGBB_API_KEY"), help="ImgBB API key; defaults to IMGBB_API_KEY")
    parser.add_argument("--source-manifest", type=Path, default=SOURCE_MANIFEST_PATH)
    parser.add_argument("--upload-manifest", type=Path, default=UPLOAD_MANIFEST_PATH)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--expiration", type=int, help="Optional auto-delete time in seconds; omit for permanent upload")
    parser.add_argument("--limit", type=int, help="Upload only first N pending thumbnails")
    parser.add_argument("--force", action="store_true", help="Re-upload even if already present in upload manifest")
    parser.add_argument("--update-only", action="store_true", help="Only update JSON coverUrl values from the upload manifest")
    parser.add_argument("--dry-run", action="store_true", help="Show upload/update counts without changing anything")
    args = parser.parse_args()

    source_manifest_path = args.source_manifest if args.source_manifest.is_absolute() else ROOT / args.source_manifest
    upload_manifest_path = args.upload_manifest if args.upload_manifest.is_absolute() else ROOT / args.upload_manifest

    if not source_manifest_path.exists():
        message = f"Source manifest not found: {source_manifest_path.relative_to(ROOT)}"
        if args.dry_run or args.update_only:
            print(message)
            print("Generate thumbnails first, or pass --source-manifest.")
            return
        raise SystemExit(message)

    source_manifest = load_json(source_manifest_path)
    items = collect_upload_items(source_manifest)
    upload_manifest = load_json(upload_manifest_path) if upload_manifest_path.exists() else {}

    pending = []
    for item in items:
        existing = upload_manifest.get(item["id"])
        if existing and existing.get("url") and not args.force:
            continue
        pending.append(item)

    if args.limit:
        pending = pending[: args.limit]

    print(f"Generated thumbnail records found: {len(items)}")
    print(f"Already uploaded/reusable: {len(items) - len(pending)}")
    print(f"Pending uploads: {len(pending)}")
    print(f"Upload manifest: {upload_manifest_path.relative_to(ROOT)}")

    if args.update_only:
        changed_files = update_json_records(upload_manifest)
        print("Updated JSON files:")
        for rel_path, count in changed_files.items():
            print(f"  {rel_path}: {count} coverUrl values")
        if not changed_files:
            print("  none")
        return

    if args.dry_run:
        print("Dry run only. No uploads or JSON updates performed.")
        return

    if pending and not args.api_key:
        raise SystemExit("Missing API key. Set IMGBB_API_KEY or pass --api-key.")

    ok = failed = 0
    total = len(pending)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = []
        for index, item in enumerate(pending, start=1):
            future = executor.submit(upload_item, item, args)
            future.item = item
            future.index = index
            futures.append(future)

        for future in concurrent.futures.as_completed(futures):
            item = future.item
            try:
                result = future.result()
                ok += 1
            except Exception as exc:
                failed += 1
                result = {
                    **item,
                    "status": "error",
                    "error": str(exc),
                    "uploadedAt": int(time.time()),
                }

            with manifest_lock:
                upload_manifest[item["id"]] = result
                save_json(upload_manifest_path, upload_manifest)

            with print_lock:
                label = result.get("title") or result.get("id")
                print(f"[{future.index}/{total}] {result['status']}: {label}")

    changed_files = update_json_records(upload_manifest)
    print(f"Done. uploaded={ok}, failed={failed}, reusable={len(items) - len(pending)}")
    print("Updated JSON files:")
    for rel_path, count in changed_files.items():
        print(f"  {rel_path}: {count} coverUrl values")
    if not changed_files:
        print("  none")
    print(f"Upload manifest written: {upload_manifest_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
