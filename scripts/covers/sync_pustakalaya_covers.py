"""
Use archived Pustakalaya records to enrich CEHRD book cover URLs.

The archived Pustakalaya search data can contain stale or repeated thumbnail
URLs. This script visits each matching Pustakalaya detail page, extracts the
detail-page cover image, and applies it to CEHRD only when the grade/subject
match is strong enough.
"""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CEHRD_PATH = DATA_DIR / "cehrd_learning.json"
MERGED_PATH = DATA_DIR / "all_books.json"
PUSTAKALAYA_PATH = DATA_DIR / "archive_data" / "pustakalaya.json"

HEADERS = {
    "User-Agent": "YoBookAPI-CoverSync/1.0",
    "Accept": "text/html,application/xhtml+xml",
}

SUBJECT_ALIASES = {
    "english": ["english", "my english"],
    "hamro serofero": ["hamro serofero", "mero serofero", "serofero", "हाम्रो सेरोफेरो"],
    "health": ["health", "स्वास्थ्य"],
    "mathematics": ["mathematics", "math", "गणित"],
    "nepali": ["nepali", "मेरो नेपाली", "नेपाली"],
    "science": ["science", "science and technology", "विज्ञान"],
    "social studies": ["social studies", "social", "सामाजिक अध्ययन"],
}

SUPPLEMENTAL_TERMS = [
    "teacher",
    "teachers'",
    "guide",
    "integrated grade teaching",
    "model question",
    "question",
    "curriculum",
    "optional",
    "opt ",
    "supporting material",
    "unit one",
    "स्वाध्ययन",
    "नमूना",
    "प्रश्न",
    "पाठ्यक्रम",
    "शिक्षक",
    "निर्देशिका",
    "ऐच्छिक",
]


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def normalize(value):
    text = as_text(value).lower()
    text = re.sub(r"grade\s*[-]?\s*(i{1,3}|iv|v|vi{0,3}|ix|x|xi|xii)\b", "grade ", text)
    text = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_supplemental(book):
    title = normalize(book.get("title"))
    return any(term in title for term in SUPPLEMENTAL_TERMS)


def subject_matches(book, subject):
    wanted = normalize(subject)
    candidate_subject = normalize(book.get("subject"))
    title = normalize(book.get("title"))
    aliases = SUBJECT_ALIASES.get(wanted, [wanted])

    if candidate_subject == wanted:
        return True
    return any(normalize(alias) in title for alias in aliases)


def score_match(cehrd_book, pusta_book):
    if cehrd_book.get("grade") != pusta_book.get("grade"):
        return 0
    if not subject_matches(pusta_book, cehrd_book.get("subject")):
        return 0
    if not pusta_book.get("coverUrl"):
        return 0

    wanted_subject = normalize(cehrd_book.get("subject"))
    title = normalize(pusta_book.get("title"))
    if wanted_subject == "science" and ("computer science" in title or "कम्प्युटर" in title):
        return 0

    score = 60
    if normalize(pusta_book.get("subject")) == normalize(cehrd_book.get("subject")):
        score += 25

    for alias in SUBJECT_ALIASES.get(wanted_subject, [wanted_subject]):
        if normalize(alias) in title:
            score += 15
            break

    if f"grade {cehrd_book.get('grade')}" in title or f"कक्षा {cehrd_book.get('grade')}" in title:
        score += 10

    if is_supplemental(pusta_book):
        score -= 60

    return score


def extract_detail_cover(book):
    source_url = book.get("sourceUrl")
    if not source_url:
        return None

    response = requests.get(source_url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    expected_alt = normalize(book.get("title"))

    for image in soup.find_all("img"):
        src = (image.get("src") or image.get("data-src") or "").strip()
        alt = normalize(image.get("alt"))
        if not src or "/media/uploads/thumbnails/document/" not in src:
            continue
        if expected_alt and alt and expected_alt != alt:
            continue
        return urljoin(source_url, src)

    for image in soup.find_all("img"):
        src = (image.get("src") or image.get("data-src") or "").strip()
        if "/media/uploads/thumbnails/document/" in src:
            return urljoin(source_url, src)

    return None


def refresh_pustakalaya_covers(pustakalaya_books, delay, dry_run):
    refreshed = 0
    failed = 0

    for book in pustakalaya_books:
        if not book.get("sourceUrl"):
            continue
        try:
            detail_cover = extract_detail_cover(book)
        except Exception as exc:
            failed += 1
            print(f"cover fetch failed: {book.get('id')} ({exc})")
            continue

        if detail_cover and detail_cover != book.get("coverUrl"):
            refreshed += 1
            print(f"refreshed: {book.get('title')} -> {detail_cover}")
            if not dry_run:
                book["coverUrl"] = detail_cover

        if delay:
            time.sleep(delay)

    return refreshed, failed


def best_cover_match(cehrd_book, pustakalaya_books):
    candidates = [
        (score_match(cehrd_book, candidate), candidate)
        for candidate in pustakalaya_books
    ]
    candidates = [(score, book) for score, book in candidates if score >= 85]
    if not candidates:
        return None, 0

    candidates.sort(key=lambda item: (item[0], not is_supplemental(item[1])), reverse=True)
    return candidates[0][1], candidates[0][0]


def apply_cover_matches(cehrd_books, merged_books, pustakalaya_books, delay, dry_run):
    by_id = {book.get("id"): book for book in merged_books if book.get("id")}
    refreshed_match_ids = set()
    changed = 0
    unmatched = []

    for book in cehrd_books:
        match, score = best_cover_match(book, pustakalaya_books)
        if not match:
            unmatched.append(book.get("id"))
            continue

        if match.get("id") not in refreshed_match_ids:
            try:
                detail_cover = extract_detail_cover(match)
            except Exception as exc:
                print(f"match cover fetch failed: {match.get('id')} ({exc})")
                detail_cover = None
            if detail_cover:
                match["coverUrl"] = detail_cover
            refreshed_match_ids.add(match.get("id"))
            if delay:
                time.sleep(delay)

        new_cover = match.get("coverUrl")
        if book.get("coverUrl") == new_cover:
            continue

        changed += 1
        print(f"matched: {book.get('id')} <- {match.get('title')} ({score})")
        if dry_run:
            continue

        book["localCoverUrl"] = book.get("localCoverUrl") or book.get("coverUrl")
        book["coverUrl"] = new_cover
        book["coverSource"] = "pustakalaya"
        book["coverSourceUrl"] = match.get("sourceUrl")

        merged = by_id.get(book.get("id"))
        if merged:
            merged["localCoverUrl"] = merged.get("localCoverUrl") or merged.get("coverUrl")
            merged["coverUrl"] = new_cover
            merged["coverSource"] = "pustakalaya"
            merged["coverSourceUrl"] = match.get("sourceUrl")

    return changed, unmatched


def main():
    parser = argparse.ArgumentParser(description="Sync CEHRD cover URLs from matching Pustakalaya detail pages")
    parser.add_argument("--refresh-archive", action="store_true", help="Refresh every archived Pustakalaya cover URL before matching")
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between Pustakalaya detail requests")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing JSON")
    args = parser.parse_args()

    cehrd_books = load_json(CEHRD_PATH)
    merged_books = load_json(MERGED_PATH) if MERGED_PATH.exists() else list(cehrd_books)
    pustakalaya_books = load_json(PUSTAKALAYA_PATH)

    if args.refresh_archive:
        refreshed, failed = refresh_pustakalaya_covers(pustakalaya_books, args.delay, args.dry_run)
        print(f"detail covers refreshed: {refreshed}; failed: {failed}")

    changed, unmatched = apply_cover_matches(cehrd_books, merged_books, pustakalaya_books, args.delay, args.dry_run)
    print(f"CEHRD covers matched: {changed}; unmatched: {len(unmatched)}")

    if args.dry_run:
        return

    save_json(PUSTAKALAYA_PATH, pustakalaya_books)
    save_json(CEHRD_PATH, cehrd_books)
    save_json(MERGED_PATH, merged_books)


if __name__ == "__main__":
    main()
