"""
Fuzzy title matching to find duplicates with variant naming.
E.g. "Math 12" vs "Mathematics Grade 12" vs "Math Twelve"
"""
import json, os, re
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CATALOG_HELPER = {"gradewise_audio_links.json", "tucl_thesis_dissertations.json", "tu_reports.json"}
EXCLUDED_FILE = os.path.join(DATA_DIR, "pustakalaya_duplicates.json")


def _str(v):
    if v is None: return ""
    if isinstance(v, list): return " ".join(str(x) for x in v)
    return str(v)


def load_books():
    books = []; seen = set()
    merged = os.path.join(DATA_DIR, "all_books.json")
    fps = [merged] if os.path.exists(merged) else []
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


def normalize_core(title):
    """Extract the core subject/meaning from a title."""
    t = _str(title).lower().strip()
    # Remove common prefixes/suffixes
    t = re.sub(r'^(ncert|cdc|cehrd|pustakalaya)\s*[-:.]*\s*', '', t)
    t = re.sub(r'\s*[-:.]*\s*(pdf|book|textbook|guide|teacher.s guide|teacher guide)$', '', t)
    t = re.sub(r'\s*[-:.]*\s*(grade|class|कक्षा|ग्रेड)\s*\d{1,2}', ' <GRADE>', t)
    t = re.sub(r'\b\d{1,2}\b', ' <NUM>', t)
    t = re.sub(r'\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b', ' <NUM>', t)
    # Normalize whitespace
    t = re.sub(r'[^a-z0-9\u0900-\u097f<>]+', ' ', t)
    t = ' '.join(t.split())
    return t


def extract_grade(title):
    """Extract grade number from title."""
    t = _str(title)
    m = re.search(r'\b(?:grade|class|कक्षा|ग्रेड)\s*[-:]?\s*(\d{1,2})\b', t, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'\b(\d{1,2})\b', t)
    if m: return m.group(1)
    return None


def extract_subject(title):
    """Try to identify the subject from title."""
    t = _str(title).lower()
    subjects = [
        'mathematics', 'math', 'maths', 'ganit', 'गणित',
        'science', 'विज्ञान',
        'nepali', 'नेपाली',
        'english',
        'social studies', 'social', 'samajik', 'सामाजिक',
        'health', 'स्वास्थ्य',
        'physics', 'भौतिक',
        'chemistry', 'रसायन',
        'biology', 'जीवविज्ञान',
        'accountancy', 'accounting', 'लेखाशास्त्र',
        'economics', 'अर्थशास्त्र',
        'geography', 'भूगोल',
        'history', 'इतिहास',
        'political', 'राजनीति',
    ]
    for s in subjects:
        if s in t:
            return s
    return None


def main():
    books = load_books()
    excl = set(json.load(open(EXCLUDED_FILE, "r", encoding="utf-8"))) if os.path.exists(EXCLUDED_FILE) else set()
    active = [b for b in books if b.get("id") not in excl]
    print(f"Total books: {len(active)}")

    # Group by: (core_normalized_title, grade)
    # The core normalized title replaces grade/class + number with <GRADE>
    # This catches "Math Grade 12" == "Mathematics Class 12" == "Math 12"
    groups = defaultdict(list)
    for b in active:
        core = normalize_core(b.get("title", ""))
        if not core: continue
        grade = extract_grade(b.get("title", "")) or _str(b.get("grade") or "")
        groups[(core, grade)].append(b)

    print("\n=== Duplicates by core title (ignoring 'grade/class X' format differences) ===")
    found = 0
    seen_groups = set()
    for (core, grade), recs in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(recs) <= 1: continue
        ids = {r.get("id") for r in recs}
        if len(ids) <= 1: continue

        found += 1
        if found > 30: continue
        print(f"\n  Core: \"{core}\"  Grade: {grade}  ({len(recs)} records)")
        for r in recs:
            src = r.get("source", "?")
            title = _str(r.get("title"))[:65]
            print(f"    id={r.get('id')[:28]}  src={src[:20]}  title=\"{title}\"")

    print(f"\nTotal core-title groups with duplicates: {found}")

    # Also check: same subject + grade across different sources
    print("\n=== Same (subject + grade) across different sources ===")
    subj_grade = defaultdict(list)
    for b in active:
        subject = extract_subject(b.get("title", "")) or _str(b.get("subject", "")).lower().strip()
        grade = extract_grade(b.get("title", "")) or _str(b.get("grade") or "")
        if not subject or not grade: continue
        subj_grade[(subject, grade)].append(b)

    sg_found = 0
    for (subj, grade), recs in sorted(subj_grade.items(), key=lambda x: -len(x[1])):
        if len(recs) <= 1: continue
        sources = {r.get("source") for r in recs}
        if len(sources) <= 1: continue
        sg_found += 1
        if sg_found > 25: continue
        print(f"\n  Subject: {subj}  Grade: {grade}  ({len(recs)} records across {len(sources)} sources)")
        for r in recs:
            print(f"    id={r.get('id')[:28]}  src={r.get('source')[:20]}  title=\"{_str(r.get('title'))[:55]}\"")

    print(f"\nTotal subject+grade groups across sources: {sg_found}")


if __name__ == "__main__":
    main()
