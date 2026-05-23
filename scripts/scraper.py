"""
YoBook API Scraper
=======================
Scrapes Nepali educational books from multiple sources and saves to JSON.

Sources:
  1. E-Pustakalaya (pustakalaya.org) â€” Nepal's digital library
  2. CDC Nepal (moecdc.gov.np) â€” Official government textbooks
  3. Internet Archive â€” Digitized Nepal books
  4. Open Library â€” Supplementary catalog

Usage:
  python scripts/scraper.py                    # Scrape all sources
  python scripts/scraper.py --source pustakalaya  # Scrape only E-Pustakalaya
  python scripts/scraper.py --source cdc          # Scrape only CDC
  python scripts/scraper.py --source archive      # Scrape only Internet Archive
  python scripts/scraper.py --source openlibrary  # Scrape only Open Library
  python scripts/scraper.py --grade 9            # Scrape only grade 9
"""

import json
import os
import re
import sys
import time
import argparse
from datetime import datetime
from urllib.parse import urlencode, quote, urljoin

import requests
from bs4 import BeautifulSoup

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
ARCHIVE_DATA_DIR = os.path.join(DATA_DIR, "archive_data")
SOURCE_FILE_PRIORITY = [
    "cehrd_learning.json",
]
ARCHIVED_SOURCE_FILES = {
    "pustakalaya.json",
    "cdc_nepal.json",
    "archive_org.json",
    "open_library.json",
}
HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/1.0 (Educational Research; Nepal Digital Library)",
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}
RATE_LIMIT = 1.5  # seconds between requests


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DATA_DIR, exist_ok=True)


def save_json(filename, data):
    """Save data to JSON file in data/ directory."""
    ensure_data_dir()
    base_dir = ARCHIVE_DATA_DIR if filename in ARCHIVED_SOURCE_FILES else DATA_DIR
    filepath = os.path.join(base_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  âœ… Saved {len(data)} items â†’ {filepath}")
    return filepath


def load_json(filename):
    """Load existing JSON data."""
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath) and filename in ARCHIVED_SOURCE_FILES:
        filepath = os.path.join(ARCHIVE_DATA_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def detect_language(text):
    """Detect if text is Nepali (Devanagari) or English."""
    if re.search(r"[\u0900-\u097F]", text):
        return "ne"
    return "en"


def extract_grade(text):
    """Extract grade number from text like 'Grade 5', 'Class 10', 'à¤•à¤•à¥à¤·à¤¾ à¥¯'."""
    # English patterns
    match = re.search(r"(?:grade|class|à¤•à¤•à¥à¤·à¤¾)\s*(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    # Nepali numerals
    nepali_digits = "à¥¦à¥§à¥¨à¥©à¥ªà¥«à¥¬à¥­à¥®à¥¯"
    match = re.search(r"à¤•à¤•à¥à¤·à¤¾\s*([" + nepali_digits + r"]+)", text)
    if match:
        num = ""
        for ch in match.group(1):
            idx = nepali_digits.index(ch)
            num += str(idx)
        return int(num)
    return None


def extract_subject(text):
    """Try to detect subject from title text."""
    subject_map = {
        "hamro serofero": "Hamro Serofero", "serofero": "Hamro Serofero",
        "mathematics": "Mathematics", "math": "Mathematics", "à¤—à¤£à¤¿à¤¤": "Mathematics",
        "science": "Science", "à¤µà¤¿à¤œà¥à¤žà¤¾à¤¨": "Science",
        "english": "English", "à¤…à¤‚à¤—à¥à¤°à¥‡à¤œà¥€": "English",
        "nepali": "Nepali", "à¤¨à¥‡à¤ªà¤¾à¤²à¥€": "Nepali",
        "social": "Social Studies", "à¤¸à¤¾à¤®à¤¾à¤œà¤¿à¤•": "Social Studies",
        "health": "Health", "à¤¸à¥à¤µà¤¾à¤¸à¥à¤¥à¥à¤¯": "Health",
        "computer": "Computer", "à¤•à¤®à¥à¤ªà¥à¤¯à¥à¤Ÿà¤°": "Computer",
        "moral": "Moral Education", "à¤¨à¥ˆà¤¤à¤¿à¤•": "Moral Education",
        "sanskrit": "Sanskrit", "à¤¸à¤‚à¤¸à¥à¤•à¥ƒà¤¤": "Sanskrit",
        "environment": "Environment", "à¤µà¤¾à¤¤à¤¾à¤µà¤°à¤£": "Environment",
        "physics": "Physics", "à¤­à¥Œà¤¤à¤¿à¤•": "Physics",
        "chemistry": "Chemistry", "à¤°à¤¸à¤¾à¤¯à¤¨": "Chemistry",
        "biology": "Biology", "à¤œà¥€à¤µà¤µà¤¿à¤œà¥à¤žà¤¾à¤¨": "Biology",
        "accountancy": "Accountancy", "à¤²à¥‡à¤–à¤¾": "Accountancy",
        "economics": "Economics", "à¤…à¤°à¥à¤¥à¤¶à¤¾à¤¸à¥à¤¤à¥à¤°": "Economics",
    }
    lower = text.lower()
    for key, val in subject_map.items():
        if key in lower or key in text:
            return val
    return None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SCRAPER 1: E-Pustakalaya
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def scrape_pustakalaya(grade_filter=None):
    """
    Scrape E-Pustakalaya (pustakalaya.org).
    Returns list of book dicts.
    """
    BASE = "https://pustakalaya.org"
    all_books = []
    seen_ids = set()

    grades = [grade_filter] if grade_filter else list(range(1, 13))

    for grade in grades:
        for keyword in [f"Grade {grade}", f"à¤•à¤•à¥à¤·à¤¾ {grade}"]:
            print(f"  ðŸ“š Pustakalaya: Scraping '{keyword}'...")
            filter_obj = json.dumps({"keywords": [keyword], "type": ["document"]})
            url = f"{BASE}/search/?q=&form-filter={quote(filter_obj)}"

            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")

                for link in soup.find_all("a", href=re.compile(r"/documents/detail/[a-f0-9-]+")):
                    title = link.get_text(strip=True)
                    href = link.get("href", "")
                    uuid_match = re.search(r"detail/([a-f0-9-]+)", href)

                    if not uuid_match or not title or len(title) < 3:
                        continue
                    if title.lower() in ("read", "document"):
                        continue

                    uuid = uuid_match.group(1)
                    book_id = f"pustakalaya-{uuid}"

                    if book_id in seen_ids:
                        continue
                    seen_ids.add(book_id)

                    # â”€â”€ Try to find thumbnail in parent container â”€â”€
                    cover_url = None
                    try:
                        # Pustakalaya search items are often in divs with thumbnails
                        parent = link.find_parent("div", class_="document-list-item") or \
                                 link.find_parent("div", class_="row")
                        if parent:
                            img = parent.find("img")
                            if img:
                                i_src = img.get("src")
                                cover_url = i_src if i_src.startswith("http") else f"{BASE}{i_src}"
                    except:
                        pass

                    all_books.append({
                        "id": book_id,
                        "title": title,
                        "author": "CDC Nepal",
                        "grade": grade,
                        "subject": extract_subject(title),
                        "language": detect_language(title),
                        "country": "np",
                        "curriculum": "CDC Nepal",
                        "source": "pustakalaya",
                        "sourceUrl": f"{BASE}/documents/detail/{uuid}/",
                        "readUrl": f"{BASE}/documents/detail/{uuid}/",
                        "coverUrl": cover_url,
                        "category": "Educational Resource",
                        "scrapedAt": datetime.utcnow().isoformat() + "Z",
                    })

                print(f"    Found {len([b for b in all_books if b['grade'] == grade])} books for grade {grade}")
                time.sleep(RATE_LIMIT)

            except Exception as e:
                print(f"    âŒ Error: {e}")
                time.sleep(RATE_LIMIT)

    # Also scrape by general textbook keywords
    for keyword in ["Textbook", "CDC", "New Textbook"]:
        print(f"  ðŸ“š Pustakalaya: Scraping keyword '{keyword}'...")
        filter_obj = json.dumps({"keywords": [keyword], "type": ["document"]})
        url = f"{BASE}/search/?q=&form-filter={quote(filter_obj)}"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            for link in soup.find_all("a", href=re.compile(r"/documents/detail/[a-f0-9-]+")):
                title = link.get_text(strip=True)
                href = link.get("href", "")
                uuid_match = re.search(r"detail/([a-f0-9-]+)", href)

                if not uuid_match or not title or len(title) < 3:
                    continue
                if title.lower() in ("read", "document"):
                    continue

                uuid = uuid_match.group(1)
                book_id = f"pustakalaya-{uuid}"

                if book_id in seen_ids:
                    continue
                seen_ids.add(book_id)

                all_books.append({
                    "id": book_id,
                    "title": title,
                    "grade": extract_grade(title),
                    "subject": extract_subject(title),
                    "author": "CDC Nepal",
                    "language": detect_language(title),
                    "country": "np",
                    "curriculum": "CDC Nepal",
                    "source": "pustakalaya",
                    "sourceUrl": f"{BASE}/documents/detail/{uuid}/",
                    "readUrl": f"{BASE}/documents/detail/{uuid}/",
                    "category": "Textbook",
                    "scrapedAt": datetime.utcnow().isoformat() + "Z",
                })

            time.sleep(RATE_LIMIT)
        except Exception as e:
            print(f"    âŒ Error: {e}")

    print(f"  ðŸ“Š Pustakalaya total: {len(all_books)} books")
    return all_books


def scrape_pustakalaya_detail(uuid):
    """Scrape detail page for a single book â€” gets keywords, related titles."""
    BASE = "https://pustakalaya.org"
    url = f"{BASE}/documents/detail/{uuid}/"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Extract keywords from filter links
        keywords = []
        for link in soup.find_all("a", href=re.compile(r"form-filter")):
            text = link.get_text(strip=True)
            if text and len(text) > 1 and "E-Pustakalaya" not in text:
                keywords.append(text)

        # Try to find title
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

        return {
            "title": title,
            "keywords": keywords,
            "grade": extract_grade(" ".join(keywords)),
            "subject": extract_subject(" ".join(keywords)),
        }
    except Exception as e:
        print(f"    âŒ Detail error: {e}")
        return None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SCRAPER 2: CDC Nepal (moecdc.gov.np)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# =============================================================================
# SCRAPER 2: CEHRD Learning Portal (learning.cehrd.gov.np)
# =============================================================================
def scrape_cehrd_learning(grade_filter=None):
    """
    Scrape CEHRD's Moodle learning portal for grade textbook resources.

    The portal hierarchy is category -> grade course -> subject section ->
    Moodle resource -> pluginfile PDF redirect.
    """
    BASE = "https://learning.cehrd.gov.np"
    CATEGORY_URL = f"{BASE}/course/index.php?categoryid=3"
    session = requests.Session()
    session.headers.update(HEADERS)
    books = []
    seen_resources = set()

    print("  CEHRD Learning: Loading reading materials category...")
    try:
        resp = session.get(CATEGORY_URL, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Error loading CEHRD category: {e}")
        return books

    soup = BeautifulSoup(resp.text, "lxml")
    courses = []
    seen_courses = set()
    course_images_by_grade = {}

    for img in soup.find_all("img", src=True):
        grade = extract_grade(img.get("alt", ""))
        if grade and grade not in course_images_by_grade:
            course_images_by_grade[grade] = _absolute_moodle_url(img.get("src"), BASE)

    for link in soup.find_all("a", href=re.compile(r"/course/view\.php\?id=\d+")):
        href = urljoin(BASE, link.get("href", ""))
        text = link.get_text(" ", strip=True)
        img = link.find("img")
        grade = extract_grade(text)

        if not grade:
            grade = extract_grade(img.get("alt", "")) if img else None

        if not grade or (grade_filter and grade != grade_filter):
            continue

        course_id = re.search(r"id=(\d+)", href).group(1)
        if course_id in seen_courses:
            continue

        seen_courses.add(course_id)
        courses.append({
            "id": course_id,
            "grade": grade,
            "url": f"{BASE}/course/view.php?id={course_id}",
            "coverUrl": (_absolute_moodle_url(img.get("src"), BASE) if img else None) or course_images_by_grade.get(grade),
        })

    courses.sort(key=lambda item: item["grade"])
    print(f"    Found {len(courses)} grade courses")

    for course in courses:
        grade = course["grade"]
        print(f"    Grade {grade}: scanning subject sections...")
        try:
            course_resp = session.get(course["url"], timeout=20)
            course_resp.raise_for_status()
        except Exception as e:
            print(f"      Error loading grade {grade}: {e}")
            continue

        course_soup = BeautifulSoup(course_resp.text, "lxml")
        sections = []
        seen_sections = set()

        section_pattern = r"/course/view\.php\?id=\d+(?:&amp;|&)section=\d+"
        for link in course_soup.find_all("a", href=re.compile(section_pattern)):
            href = urljoin(BASE, link.get("href", "").replace("&amp;", "&"))
            section_match = re.search(r"section=(\d+)", href)
            if not section_match:
                continue

            section = int(section_match.group(1))
            if section == 0 or section in seen_sections:
                continue

            label = link.get_text(" ", strip=True)
            if not label or "grade" in label.lower():
                continue

            seen_sections.add(section)
            sections.append({"section": section, "subject_label": label, "url": href})

        sections.sort(key=lambda item: item["section"])

        for section in sections:
            subject_label = section["subject_label"]
            subject = extract_subject(subject_label) or subject_label
            try:
                section_resp = session.get(section["url"], timeout=20)
                section_resp.raise_for_status()
            except Exception as e:
                print(f"      Error loading {subject_label}: {e}")
                continue

            section_soup = BeautifulSoup(section_resp.text, "lxml")
            section_img = section_soup.find("img", src=re.compile(r"/course/section/", re.I))
            cover_url = _absolute_moodle_url(section_img.get("src"), BASE) if section_img else course.get("coverUrl")
            resource_links = []

            for link in section_soup.find_all("a", href=re.compile(r"/mod/resource/view\.php\?id=\d+")):
                text = link.get_text(" ", strip=True)
                if "textbook" not in text.lower():
                    continue

                resource_url = urljoin(BASE, link.get("href", ""))
                resource_id = re.search(r"id=(\d+)", resource_url).group(1)
                if resource_id in seen_resources:
                    continue

                seen_resources.add(resource_id)
                resource_links.append((resource_id, resource_url))

            for resource_id, resource_url in resource_links:
                pdf_url = _resolve_cehrd_resource_pdf(session, resource_url, BASE)
                title = f"{subject} - Grade {grade}"
                book_id = f"cehrd-learning-g{grade}-{_slugify(subject)}-{resource_id}"

                books.append({
                    "id": book_id,
                    "title": title,
                    "author": "Centre for Education and Human Resource Development",
                    "grade": grade,
                    "subject": subject,
                    "language": detect_language(title),
                    "country": "np",
                    "curriculum": "CDC Nepal",
                    "source": "cehrd-learning",
                    "sourceUrl": resource_url,
                    "readUrl": resource_url,
                    "pdfUrl": pdf_url,
                    "coverUrl": cover_url,
                    "category": "Textbook",
                    "keywords": ["CEHRD", "CDC", "textbook", "Nepal", f"class {grade}", subject],
                    "scrapedAt": datetime.utcnow().isoformat() + "Z",
                })

                status = "PDF found" if pdf_url else "resource found, PDF not resolved"
                print(f"      {title}: {status}")
                time.sleep(0.3)

    print(f"  CEHRD Learning total: {len(books)} books")
    return books


def _resolve_cehrd_resource_pdf(session, resource_url, base_url):
    """Resolve a Moodle resource view URL to its pluginfile PDF URL."""
    try:
        resp = session.get(resource_url, allow_redirects=False, timeout=20)
        location = resp.headers.get("Location")
        if location:
            pdf_url = urljoin(base_url, location)
            if ".pdf" in pdf_url.lower() or "pluginfile.php" in pdf_url.lower():
                return pdf_url

        if resp.text:
            soup = BeautifulSoup(resp.text, "lxml")
            pdf_link = soup.find("a", href=re.compile(r"(pluginfile\.php|\.pdf)", re.I))
            if pdf_link:
                return urljoin(base_url, pdf_link.get("href", ""))
    except Exception:
        return None

    return None


def _absolute_moodle_url(url, base_url):
    """Normalize Moodle URLs, including protocol-relative image links."""
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    return urljoin(base_url, url)


def _slugify(value):
    """Create a short stable id segment."""
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-") or "book"


def scrape_cdc():
    """
    Scrape moecdc.gov.np for textbook links. Also includes
    a curated static catalog of known textbook PDFs.
    """
    BASE = "https://moecdc.gov.np"
    books = []
    seen = set()

    # â”€â”€ Part A: Static curated catalog (known PDF URLs) â”€â”€â”€â”€
    print("  ðŸ“š CDC: Loading curated catalog...")
    static = _get_cdc_static_catalog()
    books.extend(static)
    for b in static:
        seen.add(b["id"])

    # â”€â”€ Part B: Live scrape moecdc.gov.np â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print("  ðŸ“š CDC: Scraping live site...")
    targets = [
        BASE, 
        f"{BASE}/publications/general-education",
        f"{BASE}/publications/technical-and-vocational-education"
    ]
    
    for target_url in targets:
        print(f"    Scanning: {target_url}...")
        try:
            resp = requests.get(target_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Find all content links
            for link in soup.find_all("a", href=re.compile(r"/content/\d+/")):
                href = link.get("href", "")
                text = link.get_text(strip=True)
                
                if not text:
                    # Look for a title in the same card/container
                    container = link.find_parent("div", class_="card") or link.find_parent("div", class_="image-size-70")
                    if container:
                        title_tag = container.find(["h3", "h4", "h5", "p"])
                        if title_tag:
                            text = title_tag.get_text(strip=True)
                
                if not text:
                    continue

                # Only process textbook-like links
                has_class = re.search(r"à¤•à¤•à¥à¤·à¤¾|class|grade", text, re.IGNORECASE)
                if not has_class:
                    continue

                cid_match = re.search(r"/content/(\d+)/", href)
                if not cid_match:
                    continue

                content_id = cid_match.group(1)
                book_id = f"cdc-live-{content_id}"
                if book_id in seen:
                    continue
                seen.add(book_id)

                grade = extract_grade(text)
                subject = extract_subject(text)
                source_url = href if href.startswith("http") else f"{BASE}{href}"

                # â”€â”€ Follow link to get PDF and Cover â”€â”€
                print(f"      ðŸ“„ Fetching details for: {text[:40]}...")
                pdf_url = None
                cover_url = None
                try:
                    c_resp = requests.get(source_url, headers=HEADERS, timeout=10)
                    c_soup = BeautifulSoup(c_resp.text, "lxml")
                    
                    # Look for PDF in specialized download links
                    pdf_link = c_soup.find("a", class_=re.compile(r"df-ui-download|ti-download")) or \
                               c_soup.find("a", attrs={"title": re.compile(r"Download", re.I)}) or \
                               c_soup.find("a", href=re.compile(r"\.pdf$"))
                    
                    if pdf_link:
                        p_href = pdf_link.get("href")
                        pdf_url = p_href if p_href.startswith("http") else f"{BASE}{p_href}"
                    
                    # Look for cover image
                    img_container = c_soup.find("div", class_="image-size-70")
                    img = img_container.find("img") if img_container else None
                    if not img:
                        img = c_soup.find("img", src=re.compile(r"/storage/gallery/"))
                    if not img:
                        img = c_soup.find("img", attrs={"class": "img-responsive"})
                    
                    if img:
                        i_src = img.get("src")
                        cover_url = i_src if i_src.startswith("http") else f"{BASE}{i_src}"
                    
                    time.sleep(0.5)
                except:
                    pass

                books.append({
                    "id": book_id,
                    "title": text,
                    "titleLocal": text if detect_language(text) == "ne" else None,
                    "author": "Curriculum Development Center",
                    "grade": grade,
                    "subject": subject,
                    "language": detect_language(text),
                    "country": "np",
                    "curriculum": "CDC Nepal",
                    "source": "cdc-nepal",
                    "sourceUrl": source_url,
                    "pdfUrl": pdf_url,
                    "coverUrl": cover_url,
                    "category": "Textbook",
                    "keywords": ["CDC", "textbook", "Nepal"],
                    "scrapedAt": datetime.utcnow().isoformat() + "Z",
                })
        except Exception as e:
            print(f"    âŒ CDC target error ({target_url}): {e}")

    print(f"  ðŸ“Š CDC total: {len(books)} books")
    return books


def _get_cdc_static_catalog():
    """Curated list of known CDC textbook PDFs."""
    now = datetime.utcnow().isoformat() + "Z"
    BASE_PDF = "https://moecdc.gov.np/storage/gallery"
    BASE_PUSTA = "https://pustakalaya.org/documents/detail"

    catalog = [
        # â”€â”€ Class 1 â”€â”€
        {"id": "cdc-np-1-nepali", "title": "Mero Nepali - Class 1", "titleLocal": "à¤®à¥‡à¤°à¥‹ à¤¨à¥‡à¤ªà¤¾à¤²à¥€ - à¤•à¤•à¥à¤·à¤¾ à¥§",
         "grade": 1, "subject": "Nepali", "language": "ne",
         "pdfUrl": f"{BASE_PDF}/1704094300.pdf",
         "readUrl": f"{BASE_PUSTA}/b4d3cab6-a8fb-4754-acc7-18e0beaad793/",
         "chapters": ["à¤µà¤°à¥à¤£à¤®à¤¾à¤²à¤¾", "à¤¶à¤¬à¥à¤¦à¤œà¥à¤žà¤¾à¤¨", "à¤µà¤¾à¤•à¥à¤¯à¤œà¥à¤žà¤¾à¤¨", "à¤•à¤¥à¤¾", "à¤•à¤µà¤¿à¤¤à¤¾"]},

        {"id": "cdc-np-1-english", "title": "My English - Class 1", "titleLocal": "My English - à¤•à¤•à¥à¤·à¤¾ à¥§",
         "grade": 1, "subject": "English", "language": "en",
         "pdfUrl": f"{BASE_PDF}/1672307877.pdf",
         "readUrl": f"{BASE_PUSTA}/f93bc49a-3b04-4562-99cb-52473cc07017/",
         "chapters": ["Alphabet", "My School", "My Family", "Animals", "Fruits and Vegetables"]},

        {"id": "cdc-np-1-math", "title": "My Mathematics - Class 1", "titleLocal": "à¤®à¥‡à¤°à¥‹ à¤—à¤£à¤¿à¤¤ - à¤•à¤•à¥à¤·à¤¾ à¥§",
         "grade": 1, "subject": "Mathematics", "language": "en",
         "readUrl": f"{BASE_PUSTA}/0b884ef4-c4c8-459e-87c8-a931e0b49a33/",
         "chapters": ["Numbers 1-100", "Addition", "Subtraction", "Shapes", "Measurement"]},

        {"id": "cdc-np-1-serofero", "title": "Hamro Serophero - Class 1", "titleLocal": "à¤¹à¤¾à¤®à¥à¤°à¥‹ à¤¸à¥‡à¤°à¥‹à¤«à¥‡à¤°à¥‹ - à¤•à¤•à¥à¤·à¤¾ à¥§",
         "grade": 1, "subject": "Social Studies", "language": "ne",
         "readUrl": f"{BASE_PUSTA}/b2e1f0d2-adc8-4f56-9c5a-8f66ff52fc27/",
         "chapters": ["à¤®à¥‡à¤°à¥‹ à¤ªà¤°à¤¿à¤µà¤¾à¤°", "à¤®à¥‡à¤°à¥‹ à¤µà¤¿à¤¦à¥à¤¯à¤¾à¤²à¤¯", "à¤®à¥‡à¤°à¥‹ à¤¸à¤®à¥à¤¦à¤¾à¤¯"]},

        # â”€â”€ Class 4 â”€â”€
        {"id": "cdc-np-4-nepali", "title": "Mero Nepali - Class 4", "titleLocal": "à¤®à¥‡à¤°à¥‹ à¤¨à¥‡à¤ªà¤¾à¤²à¥€ - à¤•à¤•à¥à¤·à¤¾ à¥ª",
         "grade": 4, "subject": "Nepali", "language": "ne",
         "pdfUrl": f"{BASE_PDF}/1681727544.pdf",
         "readUrl": f"{BASE_PUSTA}/bd96f677-d357-4ad9-b65f-f48a180869cc/"},

        {"id": "cdc-np-4-english", "title": "English Coursebook - Class 4",
         "grade": 4, "subject": "English", "language": "en",
         "readUrl": f"{BASE_PUSTA}/f4ad35cd-5ee3-4807-ac86-36397e047180/"},

        # â”€â”€ Class 5 â”€â”€
        {"id": "cdc-np-5-nepali", "title": "Mero Nepali - Class 5", "titleLocal": "à¤®à¥‡à¤°à¥‹ à¤¨à¥‡à¤ªà¤¾à¤²à¥€ - à¤•à¤•à¥à¤·à¤¾ à¥«",
         "grade": 5, "subject": "Nepali", "language": "ne",
         "pdfUrl": f"{BASE_PDF}/1681211870.pdf"},

        {"id": "cdc-np-5-english", "title": "English Coursebook - Class 5",
         "grade": 5, "subject": "English", "language": "en",
         "readUrl": f"{BASE_PUSTA}/da7e0224-cbfd-4c72-9b82-af32570d5273/"},

        {"id": "cdc-np-5-math", "title": "My Mathematics - Class 5", "titleLocal": "à¤®à¥‡à¤°à¥‹ à¤—à¤£à¤¿à¤¤ - à¤•à¤•à¥à¤·à¤¾ à¥«",
         "grade": 5, "subject": "Mathematics", "language": "en",
         "readUrl": f"{BASE_PUSTA}/ce02150a-b592-4a14-b122-ecefea2ac5c8/",
         "chapters": ["Whole Numbers", "Fractions", "Decimals", "Geometry", "Measurement", "Statistics"]},

        # â”€â”€ Class 6 â”€â”€
        {"id": "cdc-np-6-nepali", "title": "Nepali - Class 6", "titleLocal": "à¤¨à¥‡à¤ªà¤¾à¤²à¥€ - à¤•à¤•à¥à¤·à¤¾ à¥¬",
         "grade": 6, "subject": "Nepali", "language": "ne",
         "readUrl": f"{BASE_PUSTA}/098ae88f-b976-4a62-8890-17278a52a26e/"},

        # â”€â”€ Class 8 â”€â”€
        {"id": "cdc-np-8-english", "title": "English Coursebook - Class 8",
         "grade": 8, "subject": "English", "language": "en",
         "readUrl": f"{BASE_PUSTA}/b00628b2-e45b-4f77-b4be-a187bf34a848/"},

        # â”€â”€ Class 9 â”€â”€
        {"id": "cdc-np-9-math", "title": "Grade 9 Mathematics", "titleLocal": "à¤—à¤£à¤¿à¤¤ à¤•à¤•à¥à¤·à¤¾ à¥¯",
         "grade": 9, "subject": "Mathematics", "language": "en",
         "readUrl": f"{BASE_PUSTA}/e2c33be8-0ab1-4d14-aec4-def0bce7f5fe/",
         "chapters": ["Sets", "Arithmetic", "Algebra", "Geometry", "Trigonometry", "Statistics"]},

        {"id": "cdc-np-9-social", "title": "Social Studies - Class 9", "titleLocal": "à¤¸à¤¾à¤®à¤¾à¤œà¤¿à¤• à¤…à¤§à¥à¤¯à¤¯à¤¨ à¤•à¤•à¥à¤·à¤¾ à¥¯",
         "grade": 9, "subject": "Social Studies", "language": "ne",
         "readUrl": f"{BASE_PUSTA}/c090e32d-3698-406a-b5c6-1eff0b38c14c/"},

        # â”€â”€ Class 11 â”€â”€
        {"id": "cdc-np-11-english", "title": "Communicative English - Class 11",
         "grade": 11, "subject": "English", "language": "en",
         "readUrl": f"{BASE_PUSTA}/4b8ad729-5d9f-441a-bbc4-70f245d9ee4d/"},

        # â”€â”€ Class 12 â”€â”€
        {"id": "cdc-np-12-english", "title": "English Grade Twelve (Compulsory)",
         "grade": 12, "subject": "English", "language": "en",
         "readUrl": f"{BASE_PUSTA}/effe52c5-4bf1-4691-8e1d-f6b81ef8dc79/"},
    ]

    # Add common fields to all
    for book in catalog:
        book.setdefault("author", "Curriculum Development Center")
        book.setdefault("country", "np")
        book.setdefault("curriculum", "CDC Nepal")
        book.setdefault("source", "cdc-nepal")
        book.setdefault("sourceUrl", "https://moecdc.gov.np")
        book.setdefault("category", "Textbook")
        book.setdefault("keywords", ["CDC", "textbook", "Nepal", f"class {book.get('grade', '')}"])
        book.setdefault("scrapedAt", now)

    return catalog


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SCRAPER 3: Internet Archive
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def scrape_archive_org():
    """Scrape Internet Archive for Nepal education books using their API."""
    BASE = "https://archive.org"
    books = []
    seen = set()

    queries = [
        "nepal textbook",
        "nepal curriculum CDC",
        "nepali education",
        "nepal school book",
    ]

    for query in queries:
        print(f"  ðŸ“š Archive.org: Searching '{query}'...")
        url = (
            f"{BASE}/advancedsearch.php?"
            f"q={quote(query + ' AND mediatype:texts')}"
            f"&fl[]=identifier&fl[]=title&fl[]=creator&fl[]=date"
            f"&fl[]=description&fl[]=subject&fl[]=language&fl[]=imagecount"
            f"&rows=50&page=1&output=json"
        )

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for doc in data.get("response", {}).get("docs", []):
                identifier = doc.get("identifier", "")
                book_id = f"archive-{identifier}"

                if book_id in seen or not identifier:
                    continue
                seen.add(book_id)

                subjects = doc.get("subject", [])
                if isinstance(subjects, str):
                    subjects = [subjects]

                books.append({
                    "id": book_id,
                    "title": doc.get("title", "Unknown"),
                    "author": doc.get("creator", "Unknown"),
                    "language": doc.get("language", "en"),
                    "country": "np",
                    "source": "archive-org",
                    "sourceUrl": f"{BASE}/details/{identifier}",
                    "readUrl": f"{BASE}/details/{identifier}",
                    "coverUrl": f"{BASE}/services/img/{identifier}",
                    "description": doc.get("description", ""),
                    "keywords": subjects[:10] if subjects else [],
                    "publishedYear": doc.get("date", ""),
                    "pageCount": int(doc["imagecount"]) if doc.get("imagecount") else None,
                    "category": "Archived Book",
                    "scrapedAt": datetime.utcnow().isoformat() + "Z",
                })

            print(f"    Found {len(data.get('response', {}).get('docs', []))} results")
            time.sleep(RATE_LIMIT)
        except Exception as e:
            print(f"    âŒ Error: {e}")

    print(f"  ðŸ“Š Archive.org total: {len(books)} books")
    return books


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SCRAPER 4: Open Library
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def scrape_open_library():
    """Scrape Open Library for Nepal education books using their API."""
    BASE = "https://openlibrary.org"
    books = []
    seen = set()

    queries = ["nepal textbook", "nepali education", "nepal curriculum"]

    for query in queries:
        print(f"  ðŸ“š OpenLibrary: Searching '{query}'...")
        url = f"{BASE}/search.json?q={quote(query)}&limit=50"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for doc in data.get("docs", []):
                key = doc.get("key", "").replace("/works/", "")
                book_id = f"ol-{key}"

                if book_id in seen or not key:
                    continue
                seen.add(book_id)

                cover_id = doc.get("cover_i")
                subjects = doc.get("subject", [])

                books.append({
                    "id": book_id,
                    "title": doc.get("title", "Unknown"),
                    "author": doc.get("author_name", ["Unknown"])[0] if doc.get("author_name") else "Unknown",
                    "language": doc.get("language", ["en"])[0] if doc.get("language") else "en",
                    "country": "np",
                    "source": "openlibrary",
                    "sourceUrl": f"{BASE}/works/{key}",
                    "readUrl": f"{BASE}/works/{key}",
                    "coverUrl": f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None,
                    "keywords": subjects[:10] if subjects else [],
                    "publishedYear": str(doc.get("first_publish_year", "")) if doc.get("first_publish_year") else None,
                    "category": "Library Book",
                    "scrapedAt": datetime.utcnow().isoformat() + "Z",
                })

            print(f"    Found {len(data.get('docs', []))} results")
            time.sleep(RATE_LIMIT)
        except Exception as e:
            print(f"    âŒ Error: {e}")

    print(f"  ðŸ“Š OpenLibrary total: {len(books)} books")
    return books


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SCRAPER 5: Generic URL Scraper
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def scrape_url(url):
    """
    Scrape any URL for book/PDF data.
    Extracts: title, links, PDF URLs, images, metadata.
    """
    print(f"  ðŸŒ Scraping URL: {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        result = {
            "url": url,
            "title": soup.title.string.strip() if soup.title else "",
            "description": "",
            "pdfs": [],
            "images": [],
            "links": [],
            "scrapedAt": datetime.utcnow().isoformat() + "Z",
        }

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            result["description"] = meta_desc.get("content", "")

        # Find all PDF links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".pdf") or "/storage/gallery/" in href:
                full_url = href if href.startswith("http") else f"{url.rstrip('/')}/{href.lstrip('/')}"
                result["pdfs"].append({
                    "url": full_url,
                    "text": a.get_text(strip=True) or "PDF Document",
                })

        # Find images
        for img in soup.find_all("img", src=True):
            src = img["src"]
            full_url = src if src.startswith("http") else f"{url.rstrip('/')}/{src.lstrip('/')}"
            result["images"].append({
                "url": full_url,
                "alt": img.get("alt", ""),
            })

        # Find interesting links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if text and len(text) > 3 and not href.startswith("#"):
                full_url = href if href.startswith("http") else f"{url.rstrip('/')}/{href.lstrip('/')}"
                result["links"].append({"url": full_url, "text": text})

        print(f"    Found {len(result['pdfs'])} PDFs, {len(result['images'])} images, {len(result['links'])} links")
        return result

    except Exception as e:
        print(f"    âŒ Error: {e}")
        return None


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MAIN: Run all scrapers and merge
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def merge_all():
    """Merge active source JSON files into one master catalog."""
    all_books = []
    seen_ids = set()

    filenames = [
        filename for filename in SOURCE_FILE_PRIORITY
        if os.path.exists(os.path.join(DATA_DIR, filename))
    ]
    filenames.extend(
        sorted(
            filename for filename in os.listdir(DATA_DIR)
            if filename.endswith(".json")
            and filename != "all_books.json"
            and filename not in filenames
        )
    )

    for filename in filenames:
        filepath = os.path.join(DATA_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for book in data:
                    bid = book.get("id")
                    if bid and bid not in seen_ids:
                        seen_ids.add(bid)
                        all_books.append(book)
        except Exception:
            pass

    save_json("all_books.json", all_books)
    return all_books


def main():
    parser = argparse.ArgumentParser(description="YoBook API Scraper")
    parser.add_argument("--source", choices=["pustakalaya", "cehrd", "cdc", "archive", "openlibrary", "all", "url"],
                        default="all", help="Which source to scrape")
    parser.add_argument("--grade", type=int, help="Filter by grade (1-12)")
    parser.add_argument("--url", type=str, help="URL to scrape (use with --source url)")
    args = parser.parse_args()

    print("=" * 60)
    print("YoBook API Scraper")
    print("=" * 60)

    if args.source == "url":
        if not args.url:
            print("âŒ Please provide --url when using --source url")
            sys.exit(1)
        result = scrape_url(args.url)
        if result:
            save_json("scraped_url.json", result)
        return

    if args.source in ("pustakalaya", "all"):
        print("\nðŸ‡³ðŸ‡µ Scraping E-Pustakalaya...")
        books = scrape_pustakalaya(grade_filter=args.grade)
        save_json("pustakalaya.json", books)

    if args.source in ("cehrd", "all"):
        print("\nScraping CEHRD Learning Portal...")
        books = scrape_cehrd_learning(grade_filter=args.grade)
        save_json("cehrd_learning.json", books)

    if args.source in ("cdc", "all"):
        print("\nðŸ›ï¸ Scraping CDC Nepal...")
        books = scrape_cdc()
        save_json("cdc_nepal.json", books)

    if args.source in ("archive", "all"):
        print("\nðŸ“¦ Scraping Internet Archive...")
        books = scrape_archive_org()
        save_json("archive_org.json", books)

    if args.source in ("openlibrary", "all"):
        print("\nðŸ“– Scraping Open Library...")
        books = scrape_open_library()
        save_json("open_library.json", books)

    # Merge all into one file
    if args.source == "all":
        print("\nðŸ”€ Merging all sources...")
        all_books = merge_all()
        print(f"\n{'=' * 60}")
        print(f"âœ… DONE! Total unique books: {len(all_books)}")
        print(f"   Data saved in: {DATA_DIR}/")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

