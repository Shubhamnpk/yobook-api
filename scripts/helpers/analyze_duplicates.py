"""
Refined duplicate analysis: URL-based and smart title-based.
"""
import json, os, re, sys
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CATALOG_HELPER = {"gradewise_audio_links.json", "tucl_thesis_dissertations.json", "tu_reports.json"}


def _str(v):
    if v is None: return ""
    if isinstance(v, list): return " ".join(str(x) for x in v)
    return str(v)


def norm(t):
    t = _str(t).lower()
    t = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", t)
    return t.strip()

def norm_en(t):
    """English-only normalization (strips Devanagari) — use with caution."""
    t = _str(t).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def load_books():
    books = []; seen = set()
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
    books = load_books()
    excl_path = os.path.join(DATA_DIR, "pustakalaya_duplicates.json")
    excluded = set(json.load(open(excl_path, "r", encoding="utf-8"))) if os.path.exists(excl_path) else set()
    books = [b for b in books if b.get("id") not in excluded]
    print(f"Total books (after exclusions): {len(books)}")

    # --- URL-based duplicates ---
    url_map = defaultdict(list)
    for b in books:
        for f in ("downloadUrl", "readUrl"):
            v = b.get(f)
            if isinstance(v, str) and v:
                url_map[v].append(b)
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str) and x:
                        url_map[x].append(b)

    print("\n=== URL-based duplicates (same file, different catalog entries) ===")
    total_url_dupes = 0
    for url, recs in sorted(url_map.items(), key=lambda x: -len({r.get("id") for r in x[1]})):
        ids = {r.get("id") for r in recs}
        if len(ids) > 1:
            total_url_dupes += 1
            if total_url_dupes <= 25:
                print(f"  URL: {url[:85]}")
                for r in recs:
                    title = str(r.get("title", ""))[:55]
                    print(f'    id={r.get("id")[:25]}  src={r.get("source")[:25]}  grade={r.get("grade")}  title={title}')
                print()

    print(f"\nTotal URL-based duplicates: {total_url_dupes}")

    # --- Same normalized title+grade+source (exact match including Devanagari) ---
    print("\n=== Same title+grade+source (likely true duplicates) ===")
    seen_pairs = {}
    same_source_dupes = 0
    for b in books:
        title = norm(b.get("title"))
        grade = _str(b.get("grade")).strip()
        src = b.get("source")
        if not title or not grade:
            continue
        key = (title, grade, src)
        if key in seen_pairs:
            same_source_dupes += 1
            if same_source_dupes <= 20:
                prev = seen_pairs[key]
                print(f'  NEW: {b.get("id")}  title="{str(b.get("title"))[:60]}"  g={grade}  src={src}')
                print(f'  OLD: {prev.get("id")}  title="{str(prev.get("title"))[:60]}"  g={grade}  src={src}')
                print()
        else:
            seen_pairs[key] = b

    print(f"\nSame-source title+grade duplicates: {same_source_dupes}")


if __name__ == "__main__":
    main()
