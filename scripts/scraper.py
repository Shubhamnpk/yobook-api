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
from urllib.parse import urlencode, quote, unquote, urljoin

import requests
from bs4 import BeautifulSoup

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
SOURCE_FILE_PRIORITY = [
    "cehrd_learning.json",
    "cehrd_stories.json",
    "pustakalaya_stories.json",
    "cehrd_nfe.json",
    "cehrd_audio.json",
]
SOURCE_FOLDER_PRIORITY = [
    "Literature and Arts",
    "Reference Materials",
    "Course Materials",
    "Teaching Materials",
    "Other Educational Materials",
]
HEADERS = {
    "User-Agent": "YoBookAPI-Scraper/1.0 (Educational Research; Nepal Digital Library)",
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9,ne;q=0.8",
}
RATE_LIMIT = 1.5  # seconds between requests


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def save_json(filename, data):
    """Save data to JSON file in data/ directory."""
    ensure_data_dir()
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ Saved {len(data)} items → {filepath}")
    return filepath


def load_json(filename):
    """Load existing JSON data."""
    filepath = os.path.join(DATA_DIR, filename)
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
def scrape_pustakalaya_stories(limit=None):
    """
    Scrape storybooks from E-Pustakalaya collections.
    Collections:
      1. Nepali Children's Literature
      2. English Children's Literature
      3. Hamro Ramailo Kathaharu (Our Fun Stories)
      4. Nepali Literature (Novels/Stories)
      5. Literature in Other Nepali Languages
    """
    BASE = "https://pustakalaya.org"
    # Load existing to avoid redundant detail page fetches
    filename = "pustakalaya_stories.json"
    existing_books = load_json(filename)
    books_dict = {b["id"]: b for b in existing_books}

    collections = [
        # ── Literature & Arts ─────────────────────────────────────
        "Nepali Literature [[नेपाली साहित्य]]",                                        # 700
        "Nepali Children's Literature [[नेपाली बाल साहित्य]]",                         # 754
        "Literature in Other Nepali Languages [[अन्य नेपाली भाषाहरूको साहित्य]]",     # 194
        "English Literature [[अङ्‍ग्रेजी साहित्य]]",                                   # 1599
        "Inspirational Materials [[प्रेरक सामग्री]]",                                   # 14
        "Traditional Art [[परम्परागत कलाकृति]]",                                        # 33
        "Do It Yourself [[आफैँ गर्नुहोस्]]",                                            # 39
        "English Children's Literature [[English Children's Literature]]",              # 1122
        "Hamro Ramailo Kathaharu [[हाम्रो रमाइलो कथाहरू]]",                           # 50
    ]

    new_books_count = 0
    detail_fetches = 0
    scraped_at = datetime.utcnow().isoformat() + "Z"

    for col in collections:
        col_clean = col.split("[[")[0].strip()
        print(f"\n📚 Pustakalaya Stories: Scanning Collection '{col_clean}'...")
        page = 1
        col_books_found = 0

        while True:
            # Build search url with page and collection filter
            filter_obj = {"collections": [col], "type": ["document"]}
            url = f"{BASE}/search/?page={page}&q=&form-filter={quote(json.dumps(filter_obj))}"
            
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                
                # Check pagination or search items to see if we reached the end
                items = soup.find_all("a", href=re.compile(r"/documents/detail/[a-f0-9-]+"))
                if not items:
                    break
                
                page_books_found = 0
                for link in items:
                    title = link.get_text(strip=True)
                    href = link.get("href", "")
                    uuid_match = re.search(r"detail/([a-f0-9-]+)", href)

                    if not uuid_match or not title or len(title) < 3:
                        continue
                    if title.lower() in ("read", "document"):
                        continue

                    uuid = uuid_match.group(1)
                    book_id = f"pustakalaya-{uuid}"

                    # If book is already scraped and has pdfUrl, we don't need to re-scrape
                    if book_id in books_dict and books_dict[book_id].get("pdfUrl"):
                        # Ensure keywords list has this collection
                        if col_clean not in books_dict[book_id].get("keywords", []):
                            books_dict[book_id]["keywords"].append(col_clean)
                        continue

                    # Attempt to find thumbnail cover on the search results page
                    cover_url = None
                    try:
                        parent = link.find_parent("div", class_="document-list-item") or \
                                 link.find_parent("div", class_="row")
                        if parent:
                            img = parent.find("img")
                            if img:
                                i_src = img.get("src")
                                cover_url = i_src if i_src.startswith("http") else f"{BASE}{i_src}"
                    except:
                        pass

                    # Populate basic metadata
                    book_data = books_dict.get(book_id, {
                        "id": book_id,
                        "title": title,
                        "author": "Unknown",
                        "grade": extract_grade(title),
                        "subject": extract_subject(title) or "Literature",
                        "language": detect_language(title),
                        "country": "np",
                        "curriculum": "None",
                        "source": "pustakalaya-stories",
                        "sourceUrl": f"{BASE}/documents/detail/{uuid}/",
                        "readUrl": f"{BASE}/documents/detail/{uuid}/",
                        "coverUrl": cover_url,
                        "category": "Story",
                        "keywords": [col_clean],
                        "scrapedAt": scraped_at,
                    })

                    if col_clean not in book_data["keywords"]:
                        book_data["keywords"].append(col_clean)

                    # If we don't have pdfUrl, fetch the detail page
                    if not book_data.get("pdfUrl"):
                        if limit is not None and detail_fetches >= limit:
                            # Still save basic details if new
                            if book_id not in books_dict:
                                books_dict[book_id] = book_data
                            continue
                        
                        detail_fetches += 1
                        print(f"    [{detail_fetches}] Fetching details for: {title[:40]}...")
                        
                        # Fetch detail page
                        try:
                            d_resp = requests.get(book_data["sourceUrl"], headers=HEADERS, timeout=15)
                            d_resp.raise_for_status()
                            d_soup = BeautifulSoup(d_resp.text, "lxml")
                            
                            # Extract PDF URL
                            pdf_match = re.search(r"pdfUrl\s*=\s*['\"](.*?)['\"]", d_resp.text)
                            if pdf_match:
                                book_data["pdfUrl"] = urljoin(BASE, pdf_match.group(1))
                            
                            # Extract detail cover
                            img_div = d_soup.find("div", class_="det-img-cont")
                            if img_div:
                                img = img_div.find("img")
                                if img and img.get("src"):
                                    book_data["coverUrl"] = urljoin(BASE, img.get("src"))

                            # Extract metadata table
                            table = d_soup.find("table")
                            if table:
                                for tr in table.find_all("tr"):
                                    th = tr.find("th")
                                    td = tr.find("td")
                                    if th and td:
                                        key = th.get_text(strip=True).replace(":", "").lower()
                                        val = td.get_text(" ", strip=True)
                                        if "author" in key:
                                            book_data["author"] = ", ".join([a.get_text(strip=True) for a in td.find_all("a")] or [val])
                                        elif "illustrator" in key:
                                            book_data["illustrator"] = val
                                        elif "editor" in key:
                                            book_data["editor"] = val
                                        elif "publisher" in key:
                                            book_data["publisher"] = val
                                        elif "pages" in key:
                                            book_data["pageCount"] = val
                                        elif "language" in key:
                                            book_data["language"] = "ne" if "नेपाली" in val else "en" if "english" in val.lower() else val
                                        elif "keywords" in key:
                                            kws = [a.get_text(strip=True) for a in td.find_all("a")]
                                            book_data["keywords"] = list(set(book_data["keywords"] + kws))
                            
                            # Extract description
                            desc_p = d_soup.find("p", class_="acc_paragraph")
                            if desc_p:
                                book_data["description"] = desc_p.get_text(strip=True)

                        except Exception as de:
                            print(f"      ❌ Detail fetch error: {de}")
                        
                        # Polite rate-limiting
                        time.sleep(RATE_LIMIT)

                    books_dict[book_id] = book_data
                    page_books_found += 1
                    col_books_found += 1
                    new_books_count += 1
                
                print(f"    Page {page}: processed {page_books_found} books")
                page += 1
                time.sleep(RATE_LIMIT)

                if page_books_found == 0 and not items:
                    break

            except Exception as e:
                print(f"    ❌ Error on page {page}: {e}")
                break
        
        print(f"  Finished collection '{col_clean}': total {col_books_found} books processed.")
        # Save progress after each collection
        save_json(filename, list(books_dict.values()))

    # Final save
    final_books = list(books_dict.values())
    save_json(filename, final_books)
    print(f"  🎉 Pustakalaya Stories Scrape completed. Total dataset size: {len(final_books)} books.")
    return final_books


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
                    "author": "CEHRD",
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


def scrape_cehrd_stories():
    """Scrape English and Nepali story PDFs from CEHRD Moodle pages."""
    BASE = "https://learning.cehrd.gov.np"
    story_pages = [
        {
            "url": f"{BASE}/mod/page/view.php?id=159",
            "subject": "English Stories",
            "language": "en",
        },
        {
            "url": f"{BASE}/mod/page/view.php?id=161",
            "subject": "Nepali Stories",
            "language": "ne",
        },
    ]
    session = requests.Session()
    session.headers.update(HEADERS)
    stories = []
    seen = set()

    print("  CEHRD Stories: Loading story pages...")
    for page in story_pages:
        try:
            resp = session.get(page["url"], timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"    Error loading {page['url']}: {e}")
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        content = soup.select_one("#region-main .no-overflow") or soup.select_one(".no-overflow")
        if not content:
            continue

        for story in _extract_cehrd_page_stories(content, page["url"], BASE):
            pdf_url = story["pdfUrl"]
            if pdf_url in seen:
                continue
            seen.add(pdf_url)

            title = story["title"]
            story_id = f"cehrd-stories-{page['language']}-{_slugify(title)}"
            stories.append({
                "id": story_id,
                "title": title,
                "author": "CEHRD",
                "subject": page["subject"],
                "language": page["language"],
                "country": "np",
                "curriculum": "CDC Nepal",
                "source": "cehrd-stories",
                "sourceUrl": page["url"],
                "readUrl": pdf_url,
                "pdfUrl": pdf_url,
                "coverUrl": story.get("coverUrl"),
                "category": "Story",
                "keywords": ["CEHRD", "CDC", "story", "Nepal", page["subject"]],
                "scrapedAt": datetime.utcnow().isoformat() + "Z",
            })
            print(f"    {title}: story PDF found")
            time.sleep(0.3)

    print(f"  CEHRD Stories total: {len(stories)} stories")
    return stories


def scrape_cehrd_nfe_materials():
    """Scrape NFE NQF Level 1-3 learning material PDFs from CEHRD folders."""
    BASE = "https://learning.cehrd.gov.np"
    section_url = f"{BASE}/course/section.php?id=191"
    folders = [
        {"level": 1, "url": f"{BASE}/mod/folder/view.php?id=264"},
        {"level": 2, "url": f"{BASE}/mod/folder/view.php?id=265"},
        {"level": 3, "url": f"{BASE}/mod/folder/view.php?id=266"},
    ]
    session = requests.Session()
    session.headers.update(HEADERS)
    materials = []
    seen = set()

    print("  CEHRD NFE: Loading Level 1-3 folders...")
    for folder in folders:
        level = folder["level"]
        try:
            resp = session.get(folder["url"], timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"    Error loading Level {level}: {e}")
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        main = soup.select_one("#region-main") or soup.select_one("[role=main]") or soup
        for link in main.find_all("a", href=True):
            href = link.get("href", "")
            text = link.get_text(" ", strip=True)
            if "pluginfile.php" not in href or ".pdf" not in href.lower():
                continue

            pdf_url = _normalize_cehrd_pdf_url(urljoin(BASE, href))
            if pdf_url in seen:
                continue
            seen.add(pdf_url)

            title = _clean_pdf_title(text) or _title_from_filename(pdf_url)
            material_id = f"cehrd-nfe-l{level}-{_slugify(title)}"
            materials.append({
                "id": material_id,
                "title": title,
                "author": "CEHRD",
                "subject": f"NFE Level {level}",
                "level": level,
                "language": detect_language(title),
                "country": "np",
                "curriculum": "NFE NQF",
                "source": "cehrd-nfe",
                "sourceUrl": section_url,
                "readUrl": pdf_url,
                "pdfUrl": pdf_url,
                "category": "Non Formal Learning Material",
                "keywords": ["CEHRD", "NFE", "NQF", "Nepal", f"level {level}"],
                "scrapedAt": datetime.utcnow().isoformat() + "Z",
            })
            print(f"    Level {level}: {title}")
            time.sleep(0.2)

    print(f"  CEHRD NFE total: {len(materials)} materials")
    return materials


def scrape_cehrd_audio_materials():
    """Scrape CEHRD Audio Education Materials from the drama section."""
    BASE = "https://learning.cehrd.gov.np"
    section_url = f"{BASE}/course/section.php?id=224"
    audio_icon = f"{BASE}/theme/image.php/educard/core/1779070821/f/audio?filtericon=1"
    session = requests.Session()
    session.headers.update(HEADERS)
    materials = []
    seen = set()

    print("  CEHRD Audio: Loading drama section...")
    try:
        resp = session.get(section_url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"    Error loading audio section: {e}")
        return materials

    soup = BeautifulSoup(resp.text, "lxml")
    main = soup.select_one("#region-main") or soup.select_one("[role=main]") or soup
    resource_links = []
    for link in main.find_all("a", href=re.compile(r"/mod/resource/view\.php\?id=\d+")):
        resource_url = urljoin(BASE, link.get("href", "").replace("&amp;", "&"))
        resource_id_match = re.search(r"id=(\d+)", resource_url)
        if not resource_id_match:
            continue

        resource_id = resource_id_match.group(1)
        if resource_id in seen:
            continue
        seen.add(resource_id)

        title = _clean_moodle_resource_title(link.get_text(" ", strip=True))
        resource_links.append((resource_id, title, resource_url))

    print(f"    Found {len(resource_links)} audio resources")
    for resource_id, title, resource_url in resource_links:
        audio_url = _resolve_cehrd_audio_resource(session, resource_url, BASE)
        if not audio_url or not _is_working_audio_url(session, audio_url):
            print(f"    {title}: audio not resolved")
            continue

        material_id = f"cehrd-audio-drama-{resource_id}-{_slugify(title)}"
        materials.append({
            "id": material_id,
            "title": title,
            "author": "CEHRD",
            "subject": "Audio Drama",
            "language": detect_language(title),
            "country": "np",
            "curriculum": "CDC Nepal",
            "source": "cehrd-audio",
            "sourceUrl": resource_url,
            "readUrl": audio_url,
            "audioUrl": audio_url,
            "coverUrl": audio_icon,
            "category": "Audio Book",
            "keywords": ["CEHRD", "audio", "audiobook", "drama", "Nepal"],
            "scrapedAt": datetime.utcnow().isoformat() + "Z",
        })
        print(f"    {title}: MP3 found")
        time.sleep(0.2)

    print(f"  CEHRD Audio total: {len(materials)} materials")
    return materials


def _extract_cehrd_page_stories(content, page_url, base_url):
    """Extract story title/PDF/cover triples from CEHRD page content."""
    stories = []
    table = content.find("table")
    if table:
        rows = table.find_all("tr")
        index = 0
        while index < len(rows):
            links = [
                link for link in rows[index].find_all("a", href=True)
                if "pluginfile.php" in link.get("href", "") or ".pdf" in link.get("href", "").lower()
            ]
            if not links:
                index += 1
                continue

            title_cells = rows[index + 1].find_all("td") if index + 1 < len(rows) else []
            for cell_index, link in enumerate(links):
                title = ""
                if cell_index < len(title_cells):
                    title = title_cells[cell_index].get_text(" ", strip=True)
                stories.append(_build_cehrd_story(link, title, page_url, base_url))
            index += 2
        return stories

    for link in content.find_all("a", href=True):
        href = link.get("href", "")
        if "pluginfile.php" not in href and ".pdf" not in href.lower():
            continue
        title = link.get_text(" ", strip=True)
        stories.append(_build_cehrd_story(link, title, page_url, base_url))

    return stories


def _build_cehrd_story(link, title, page_url, base_url):
    pdf_url = urljoin(base_url, link.get("href", ""))
    image = link.find("img", src=True)
    cover_url = _absolute_moodle_url(image.get("src"), base_url) if image else None
    if not title:
        title = _title_from_filename(pdf_url)

    return {
        "title": title,
        "pdfUrl": pdf_url,
        "coverUrl": cover_url,
        "sourceUrl": page_url,
    }


def _title_from_filename(url):
    filename = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    filename = unquote(filename)
    filename = re.sub(r"\.pdf$", "", filename, flags=re.I)
    filename = re.sub(r"[-_]+", " ", filename)
    filename = re.sub(r"\s+", " ", filename).strip()
    return filename.title() if filename else "Untitled Story"


def _clean_pdf_title(value):
    title = re.sub(r"\.pdf$", "", value or "", flags=re.I).strip()
    return re.sub(r"\s+", " ", title)


def _normalize_cehrd_pdf_url(url):
    if "forcedownload=1" in url:
        return url.split("?", 1)[0]
    return url


def _clean_moodle_resource_title(value):
    title = re.sub(r"\bFile\b", "", value or "", flags=re.I)
    title = re.sub(r"\s+", " ", title).strip()
    if title and len(title) % 2 == 0:
        half = len(title) // 2
        if title[:half] == title[half:]:
            title = title[:half].strip()
    return title or "Untitled Audio"


def _resolve_cehrd_audio_resource(session, resource_url, base_url):
    try:
        resp = session.get(resource_url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        source = soup.find("source", src=re.compile(r"\.mp3", re.I))
        if source:
            return urljoin(base_url, source.get("src", ""))

        audio_link = soup.find("a", href=re.compile(r"\.mp3", re.I))
        if audio_link:
            return urljoin(base_url, audio_link.get("href", ""))
    except Exception:
        return None

    return None


def _is_working_audio_url(session, audio_url):
    try:
        resp = session.get(audio_url, stream=True, timeout=20)
        chunk = next(resp.iter_content(32), b"")
        content_type = resp.headers.get("Content-Type", "").lower()
        resp.close()
        return resp.status_code == 200 and (
            "audio" in content_type
            or chunk.startswith(b"ID3")
            or chunk.startswith(b"\xff\xfb")
            or chunk.startswith(b"\xff\xf3")
            or chunk.startswith(b"\xff\xf2")
        )
    except Exception:
        return False


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

    filepaths = [
        os.path.join(DATA_DIR, filename) for filename in SOURCE_FILE_PRIORITY
        if os.path.exists(os.path.join(DATA_DIR, filename))
    ]
    for folder in SOURCE_FOLDER_PRIORITY:
        folder_path = os.path.join(DATA_DIR, folder)
        if os.path.isdir(folder_path):
            filepaths.extend(
                os.path.join(folder_path, filename)
                for filename in sorted(os.listdir(folder_path))
                if filename.endswith(".json")
            )
    handled = {os.path.abspath(path) for path in filepaths}
    for root, _, files in os.walk(DATA_DIR):
        for filename in sorted(files):
            if not filename.endswith(".json") or filename == "all_books.json":
                continue
            filepath = os.path.join(root, filename)
            if os.path.abspath(filepath) not in handled:
                filepaths.append(filepath)
                handled.add(os.path.abspath(filepath))

    for filepath in filepaths:
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
    parser.add_argument("--source", choices=["pustakalaya_stories", "cehrd", "stories", "nfe", "audio", "all", "url"],
                        default="all", help="Which source to scrape")
    parser.add_argument("--grade", type=int, help="Filter by grade (1-12)")
    parser.add_argument("--url", type=str, help="URL to scrape (use with --source url)")
    parser.add_argument("--limit", type=int, help="Limit the number of detail page requests")
    args = parser.parse_args()

    print("=" * 60)
    print("YoBook API Scraper")
    print("=" * 60)

    if args.source == "url":
        if not args.url:
            print("❌ Please provide --url when using --source url")
            sys.exit(1)
        result = scrape_url(args.url)
        if result:
            save_json("scraped_url.json", result)
        return

    if args.source in ("pustakalaya_stories", "all"):
        print("\n📚 Scraping E-Pustakalaya Stories...")
        books = scrape_pustakalaya_stories(limit=args.limit)

    if args.source in ("cehrd", "all"):
        print("\nScraping CEHRD Learning Portal...")
        books = scrape_cehrd_learning(grade_filter=args.grade)
        save_json("cehrd_learning.json", books)

    if args.source in ("stories", "all"):
        print("\nScraping CEHRD Stories...")
        stories = scrape_cehrd_stories()
        save_json("cehrd_stories.json", stories)

    if args.source in ("nfe", "all"):
        print("\nScraping CEHRD NFE Materials...")
        materials = scrape_cehrd_nfe_materials()
        save_json("cehrd_nfe.json", materials)

    if args.source in ("audio", "all"):
        print("\nScraping CEHRD Audio Materials...")
        materials = scrape_cehrd_audio_materials()
        save_json("cehrd_audio.json", materials)

    # Merge active source files into one catalog.
    if args.source in ("all", "cehrd", "stories", "nfe", "audio", "pustakalaya_stories"):
        print("\n🔄 Merging all sources...")
        all_books = merge_all()
        print(f"\n{'=' * 60}")
        print(f"✅ DONE! Total unique books: {len(all_books)}")
        print(f"   Data saved in: {DATA_DIR}/")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
