"""
Validate the local YoBook catalog files.

This is a lightweight maintainer check for pull requests and data refreshes.
It does not make network calls.
"""

import json
import os
import sys
from collections import Counter


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
REQUIRED_FIELDS = ("id", "title", "source", "category")


def iter_catalog_files():
    for root, _, files in os.walk(DATA_DIR):
        for filename in sorted(files):
            if filename.endswith(".json") and filename != "all_books.json":
                yield os.path.join(root, filename)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    errors = []
    warnings = []
    seen_ids = {}
    source_counts = Counter()
    item_count = 0

    if not os.path.isdir(DATA_DIR):
        print(f"Missing data directory: {DATA_DIR}")
        return 1

    for path in iter_catalog_files():
        relpath = os.path.relpath(path, ROOT)
        try:
            data = load_json(path)
        except Exception as exc:
            errors.append(f"{relpath}: could not read JSON: {exc}")
            continue

        if not isinstance(data, list):
            errors.append(f"{relpath}: expected a list")
            continue

        for index, book in enumerate(data):
            item_count += 1
            if not isinstance(book, dict):
                errors.append(f"{relpath}[{index}]: expected an object")
                continue

            missing = [field for field in REQUIRED_FIELDS if not book.get(field)]
            if missing:
                errors.append(f"{relpath}[{index}]: missing {', '.join(missing)}")

            book_id = book.get("id")
            if book_id:
                if book_id in seen_ids:
                    warnings.append(
                        f"{relpath}[{index}]: duplicate id {book_id} also in {seen_ids[book_id]}"
                    )
                else:
                    seen_ids[book_id] = relpath

            if book.get("pdfUrl") and book.get("source", "").startswith("pustakalaya-"):
                errors.append(f"{relpath}[{index}]: Pustakalaya records should use readUrl, not pdfUrl")

            if not (book.get("readUrl") or book.get("pdfUrl") or book.get("audioUrl")):
                warnings.append(f"{relpath}[{index}]: missing readUrl/pdfUrl/audioUrl")

            source_counts[book.get("source") or "unknown"] += 1

    print(f"Catalog files checked: {sum(1 for _ in iter_catalog_files())}")
    print(f"Catalog records checked: {item_count}")
    for source, count in sorted(source_counts.items()):
        print(f"  {source}: {count}")

    if warnings:
        print("\nWarnings:")
        for warning in warnings[:50]:
            print(f"  - {warning}")
        if len(warnings) > 50:
            print(f"  ... {len(warnings) - 50} more")

    if errors:
        print("\nValidation failed:")
        for error in errors[:100]:
            print(f"  - {error}")
        if len(errors) > 100:
            print(f"  ... {len(errors) - 100} more")
        return 1

    print("\nValidation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
