"""
Deep-check the 11 title-matched cross-source candidates.
"""
import json, os, re

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CATALOG_HELPER = {"gradewise_audio_links.json", "tucl_thesis_dissertations.json", "tu_reports.json"}
EXCLUDED_FILE = os.path.join(DATA_DIR, "pustakalaya_duplicates.json")


def _str(v):
    if v is None: return ""
    if isinstance(v, list): return " ".join(str(x) for x in v)
    return str(v)


def norm(t):
    t = _str(t).lower()
    t = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", t)
    return t.strip()


def load_books():
    books = []; seen = set()
    fps = []
    merged = os.path.join(DATA_DIR, "all_books.json")
    if os.path.exists(merged): fps.append(merged)
    for r, _, fs in os.walk(DATA_DIR):
        for f in sorted(fs):
            if not f.endswith(".json") or f == "all_books.json" or f in CATALOG_HELPER: continue
            fps.append(os.path.join(r, f))
    for fp in fps:
        try:
            d = json.load(open(fp, "r", encoding="utf-8"))
            if isinstance(d, list):
                for b in d:
                    if not isinstance(b, dict): continue
                    bid = b.get("id")
                    if bid and bid not in seen:
                        seen.add(bid); books.append(b)
        except: pass
    return books


def main():
    books = load_books()
    excluded = set(json.load(open(EXCLUDED_FILE, "r", encoding="utf-8"))) if os.path.exists(EXCLUDED_FILE) else set()
    active = [b for b in books if b.get("id") not in excluded]

    target_sources = {"cehrd-learning", "cehrd-stories", "cehrd-nfe", "cehrd-audio", "cdc-library"}
    cehrd_titles = {}
    for b in active:
        if b.get("source") in target_sources:
            t = norm(b.get("title"))
            if t: cehrd_titles[t] = b

    print("Checking 11 cross-source name matches: are they really the same book?\n")

    for b in active:
        src = b.get("source", "")
        if not src.startswith("pustakalaya-"):
            continue
        t = norm(b.get("title"))
        if t and t in cehrd_titles:
            c = cehrd_titles[t]
            print(f"Title: {b.get('title')}")
            print(f"  Pustakalaya: id={b.get('id')}")
            print(f"  CEHRD/CDC:   id={c.get('id')}")
            print(f"  downloadUrl P: {b.get('downloadUrl', '-')[:90]}")
            print(f"  downloadUrl C: {c.get('downloadUrl', '-')[:90]}")
            print(f"  readUrl P:     {b.get('readUrl', '-')[:90]}")
            print(f"  readUrl C:     {c.get('readUrl', '-')[:90]}")
            print(f"  coverUrl P:    {b.get('coverUrl', '-')[:90]}")
            print(f"  coverUrl C:    {c.get('coverUrl', '-')[:90]}")
            print()


if __name__ == "__main__":
    main()
