"""
Find URL-based duplicates across the catalog.
For each shared URL, keep the best record and mark the rest as excluded.
"""
import json, os, re, sys
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CATALOG_HELPER = {"gradewise_audio_links.json", "tucl_thesis_dissertations.json", "tu_reports.json"}
EXCLUDED_FILE = os.path.join(DATA_DIR, "pustakalaya_duplicates.json")

SOURCE_PRIORITY = {
    "cehrd-learning": 0,
    "cehrd-stories": 1,
    "cehrd-nfe": 2,
    "cehrd-audio": 3,
    "pustakalaya-stories": 4,
    "pustakalaya-reference": 5,
    "pustakalaya-course": 6,
    "pustakalaya-teaching": 7,
    "pustakalaya-other-educational": 8,
    "ncert-official": 9,
    "openstax": 10,
    "standard-ebooks": 11,
    "cdc-library": 12,
    "SL": 13,
    "shisir-library-grouped": 14,
    "questionbanknepal": 15,
}


def _str(v):
    if v is None: return ""
    if isinstance(v, list): return " ".join(str(x) for x in v)
    return str(v)


def _book_score(b):
    """Higher score = richer metadata, we prefer to keep this record."""
    score = 0
    score += 1 if b.get("title") else 0
    score += 1 if b.get("titleLocal") else 0
    score += 1 if b.get("author") else 0
    score += 1 if b.get("grade") else 0
    score += 1 if b.get("subject") else 0
    score += 1 if b.get("description") else 0
    score += 1 if b.get("publisher") else 0
    score += 1 if b.get("coverUrl") else 0
    score += 1 if b.get("category") else 0
    score += 1 if b.get("keywords") else 0
    score += 1 if b.get("language") == "en" else 0  # prefer English
    score += 2 if isinstance(b.get("downloadUrl"), str) and b.get("downloadUrl") else 0
    score += 2 if isinstance(b.get("readUrl"), str) and b.get("readUrl") else 0
    return score


def _source_rank(b):
    src = b.get("source", "")
    return SOURCE_PRIORITY.get(src, 99)


def load_books():
    books = []
    seen = set()
    merged = os.path.join(DATA_DIR, "all_books.json")
    fps = [merged] if os.path.exists(merged) else []
    for r, _, fs in os.walk(DATA_DIR):
        for f in sorted(fs):
            if not f.endswith(".json") or f == "all_books.json" or f in CATALOG_HELPER:
                continue
            fps.append(os.path.join(r, f))
    for fp in fps:
        try:
            d = json.load(open(fp, "r", encoding="utf-8"))
            if isinstance(d, list):
                for b in d:
                    bid = b.get("id")
                    if bid and bid not in seen:
                        seen.add(bid)
                        books.append(b)
        except Exception:
            pass
    return books


def main():
    print("Loading books...")
    books = load_books()
    print(f"  Total unique books: {len(books)}")

    # Load current excluded IDs
    already_excluded = set()
    if os.path.exists(EXCLUDED_FILE):
        already_excluded = set(json.load(open(EXCLUDED_FILE, "r", encoding="utf-8")))
        print(f"  Already excluded: {len(already_excluded)}")

    # Build URL -> books map (only for non-excluded books)
    url_map = defaultdict(list)
    for b in books:
        if b.get("id") in already_excluded:
            continue
        for f in ("downloadUrl", "readUrl"):
            v = b.get(f)
            if isinstance(v, str) and v.startswith("http"):
                url_map[v].append(b)
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str) and x.startswith("http"):
                        url_map[x].append(b)

    # Find duplicates: same URL, different IDs
    new_excluded = set()
    dup_groups = 0

    for url, recs in sorted(url_map.items(), key=lambda x: -len({r.get("id") for r in x[1]})):
        ids = {r.get("id") for r in recs}
        if len(ids) <= 1:
            continue

        dup_groups += 1

        # Score each record and pick the best one
        scored = sorted(recs, key=lambda r: (_source_rank(r), -_book_score(r)))
        # First by source rank (lower = better), then by metadata score (higher = better)
        keeper = scored[0]

        for r in recs:
            if r.get("id") != keeper.get("id"):
                new_excluded.add(r.get("id"))

        if dup_groups <= 5:
            print(f"\n  URL: {url[:80]}")
            print(f"    KEEP: id={keeper.get('id')[:25]} src={keeper.get('source')} title=\"{_str(keeper.get('title'))[:50]}\"")
            for r in recs:
                if r.get("id") != keeper.get("id"):
                    print(f"    EXCL: id={r.get('id')[:25]} src={r.get('source')} title=\"{_str(r.get('title'))[:50]}\"")

    print(f"\nFound {dup_groups} URL groups with duplicates")

    # Merge with existing excluded IDs
    all_excluded = sorted(already_excluded | new_excluded)
    print(f"New IDs to exclude: {len(new_excluded)}")
    print(f"Total excluded IDs: {len(all_excluded)}")

    # Write updated exclusion list
    with open(EXCLUDED_FILE, "w", encoding="utf-8") as f:
        json.dump(all_excluded, f, indent=2, ensure_ascii=False)
    print(f"Written to {EXCLUDED_FILE}")


if __name__ == "__main__":
    main()
