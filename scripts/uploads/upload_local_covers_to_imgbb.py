"""
Upload local cover images to ImgBB and replace local coverUrl values in JSON.

The ImgBB API accepts multipart uploads at:
  https://api.imgbb.com/1/upload

Usage:
  $env:IMGBB_API_KEY = "your-key"
  python scripts/uploads/upload_local_covers_to_imgbb.py --dry-run
  python scripts/uploads/upload_local_covers_to_imgbb.py

By default this scans data/**/*.json for coverUrl values like /covers/name.jpg,
uploads each unique local image once, writes upload metadata to
data/imgbb_uploads.json, and replaces matching coverUrl values with the hosted
ImgBB image URL.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
MANIFEST_PATH = DATA_DIR / "imgbb_uploads.json"
UPLOAD_URL = "https://api.imgbb.com/1/upload"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


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


def is_remote_url(value):
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def local_cover_path(cover_url):
    if not isinstance(cover_url, str) or is_remote_url(cover_url):
        return None

    clean = cover_url.split("?", 1)[0].strip()
    if not clean:
        return None

    relative = clean.lstrip("/").replace("/", os.sep)
    path = DATA_DIR / relative
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    return path


def find_local_cover_refs(json_paths):
    refs = {}
    for json_path in json_paths:
        try:
            data = load_json(json_path)
        except Exception as exc:
            print(f"[skip] Could not read {json_path}: {exc}")
            continue

        if not isinstance(data, list):
            continue

        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            cover_url = item.get("coverUrl")
            path = local_cover_path(cover_url)
            if not path:
                continue
            refs.setdefault(str(path.relative_to(ROOT)), []).append(
                {"json": str(json_path.relative_to(ROOT)), "index": index, "coverUrl": cover_url}
            )
    return refs


def upload_image(api_key, image_path, name=None, expiration=None, timeout=60):
    params = {"key": api_key}
    data = {}
    if name:
        data["name"] = name
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
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload)
    return payload["data"]


def update_json_cover_urls(json_paths, url_map, dry_run=False):
    changed_files = {}
    for json_path in json_paths:
        data = load_json(json_path)
        if not isinstance(data, list):
            continue

        changed = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            old_cover = item.get("coverUrl")
            path = local_cover_path(old_cover)
            if not path:
                continue
            hosted_url = url_map.get(str(path.relative_to(ROOT)))
            if hosted_url and old_cover != hosted_url:
                item["coverUrl"] = hosted_url
                changed += 1

        if changed:
            changed_files[str(json_path.relative_to(ROOT))] = changed
            if not dry_run:
                save_json(json_path, data)
    return changed_files


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="Upload local cover images to ImgBB")
    parser.add_argument("--api-key", default=os.environ.get("IMGBB_API_KEY"), help="ImgBB API key; defaults to IMGBB_API_KEY")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="Directory containing JSON data")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH, help="Upload manifest path")
    parser.add_argument("--expiration", type=int, help="Optional auto-delete time in seconds; omit for permanent upload")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between uploads")
    parser.add_argument("--dry-run", action="store_true", help="Show what would upload/update without changing files")
    parser.add_argument("--force", action="store_true", help="Upload even if the manifest already has a hosted URL")
    args = parser.parse_args()

    json_paths = sorted(args.data_dir.glob("**/*.json"))
    refs = find_local_cover_refs(json_paths)
    print(f"Local cover images referenced: {len(refs)}")
    for rel_path, locations in refs.items():
        exists = (ROOT / rel_path).exists()
        print(f"  {rel_path} | refs={len(locations)} | exists={exists}")

    if not refs:
        print("No local coverUrl values found.")
        return

    if args.dry_run:
        print("Dry run only. No uploads or JSON updates performed.")
        return

    if not args.api_key:
        raise SystemExit("Missing API key. Set IMGBB_API_KEY or pass --api-key.")

    manifest = {}
    if args.manifest.exists():
        manifest = load_json(args.manifest)

    url_map = {}
    for rel_path in refs:
        image_path = ROOT / rel_path
        if not image_path.exists():
            print(f"[missing] {rel_path}")
            continue

        existing = manifest.get(rel_path)
        if existing and existing.get("url") and not args.force:
            url_map[rel_path] = existing["url"]
            print(f"[reuse] {rel_path} -> {existing['url']}")
            continue

        print(f"[upload] {rel_path}")
        uploaded = upload_image(
            args.api_key,
            image_path,
            name=image_path.stem,
            expiration=args.expiration,
        )
        manifest[rel_path] = {
            "url": uploaded.get("url"),
            "displayUrl": uploaded.get("display_url"),
            "viewerUrl": uploaded.get("url_viewer"),
            "deleteUrl": uploaded.get("delete_url"),
            "width": uploaded.get("width"),
            "height": uploaded.get("height"),
            "size": uploaded.get("size"),
            "uploadedAt": int(time.time()),
        }
        url_map[rel_path] = uploaded.get("url")
        save_json(args.manifest, manifest)
        time.sleep(max(0, args.delay))

    changed_files = update_json_cover_urls(json_paths, url_map, dry_run=False)
    print("Updated JSON files:")
    for rel_json, count in changed_files.items():
        print(f"  {rel_json}: {count} coverUrl values")
    manifest_path = args.manifest.resolve()
    try:
        manifest_display = manifest_path.relative_to(ROOT)
    except ValueError:
        manifest_display = manifest_path
    print(f"Manifest written: {manifest_display}")


if __name__ == "__main__":
    main()
