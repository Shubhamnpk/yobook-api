"""
Scrape Question Bank Nepal question-paper links into grouped exam records.

The output groups all paper links for an exam under one ``question_papers`` field,
matching the public catalog shape used by the API while preserving the source
page URL for each paper.
"""

import hashlib
import json
import os
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_PATH = os.path.join(
    ROOT,
    "data",
    "Course Materials",
    "questionbanknepal_question_papers.json",
)
START_URLS = (
    "https://questionbanknepal.com/",
    "https://old.questionbanknepal.com/",
)
MAX_PAGES = 180
ALLOWED_HOSTS = {"questionbanknepal.com", "old.questionbanknepal.com"}
COLLECTIONS = {
    "questionbanknepal.com/lok-sewa-preparation": "Lok Sewa Preparation",
    "questionbanknepal.com/kharidar": "Lok Sewa Preparation",
    "questionbanknepal.com/nayab-subba": "Lok Sewa Preparation",
    "questionbanknepal.com/gyan-sagar-from-gorkhapatra-daily": "Lok Sewa Preparation",
    "questionbanknepal.com/lok-sewa-tips-from-rajdhani-daily": "Lok Sewa Preparation",
    "questionbanknepal.com/bank-exam-preparation": "Bank Exam Preparation",
    "questionbanknepal.com/nepal-rastra-bank": "Bank Exam Preparation",
    "questionbanknepal.com/nepal-bank-limited": "Bank Exam Preparation",
    "questionbanknepal.com/agricultural-development-bank": "Bank Exam Preparation",
    "questionbanknepal.com/rastriya-banijya-bank": "Bank Exam Preparation",
    "questionbanknepal.com/college-university-questions": "College Exam Preparation",
    "questionbanknepal.com/corporation-job-exams": "Corporation Job Exams",
    "old.questionbanknepal.com/slc": "College Exam Preparation",
    "old.questionbanknepal.com/grade11": "College Exam Preparation",
    "old.questionbanknepal.com/grade12": "College Exam Preparation",
    "old.questionbanknepal.com/tu": "College Exam Preparation",
}
SKIP_EXT_RE = re.compile(
    r"\.(jpg|jpeg|png|gif|webp|css|js|ico|zip|rar|doc|docx|xls|xlsx)$",
    re.IGNORECASE,
)
PAPER_EXT_RE = re.compile(r"\.(pdf)$", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(20[5-8]\d|206\d|207\d|208\d)\b")
MENU_WORDS = {
    "home",
    "about us",
    "contact us",
    "go back",
    "question bank nepal",
    "skip to content",
    "view collections",
    "show menu",
}


def clean(value):
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def normalize_url(url):
    url = urldefrag(url)[0]
    parsed = urlparse(url)
    scheme = "https" if parsed.netloc in ALLOWED_HOSTS else parsed.scheme
    path = parsed.path or "/"
    if not path.lower().endswith(".php") and not PAPER_EXT_RE.search(path):
        path = path.rstrip("/") + "/"
    return urlunparse((scheme, parsed.netloc, path, "", parsed.query, ""))


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "questionbanknepal"


def stable_id(exam_name, collection_name, source_url):
    seed = f"{exam_name}|{collection_name}|{source_url}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"qbn-{slugify(exam_name)}-{digest}"


def page_label(soup, url):
    h1 = soup.find("h1")
    if h1 and clean(h1.get_text()):
        return clean(h1.get_text())

    lines = [clean(line) for line in soup.get_text("\n", strip=True).split("\n")]
    lines = [line for line in lines if line]
    breadcrumb = next((line for line in lines if "►" in line), "")
    if breadcrumb:
        return clean(breadcrumb.replace("↓", "").replace("►", " ").strip())

    for line in lines:
        low = line.lower()
        if (
            low in MENU_WORDS
            or low.startswith("question bank nepal |")
            or low.startswith("exams |")
            or "↓" in line
            or line == "‣"
            or len(line) < 3
        ):
            continue
        return line[:180]

    return urlparse(url).path.strip("/") or "Question Bank Nepal"


def canonical_exam_name(value):
    parts = [part for part in clean(value).split(" ") if part]
    if parts and YEAR_RE.fullmatch(parts[-1]):
        parts = parts[:-1]
    if len(parts) >= 2 and parts[0].lower() == "slc":
        return "SLC"
    return clean(" ".join(parts))


def collection_name_for(url, exam_name):
    key = f"{urlparse(url).netloc}{urlparse(url).path}".rstrip("/")
    for prefix, collection_name in COLLECTIONS.items():
        if key.startswith(prefix):
            return collection_name
    if any(word in exam_name.lower() for word in ("kharidar", "subba", "lok sewa")):
        return "Lok Sewa Preparation"
    if "bank" in exam_name.lower():
        return "Bank Exam Preparation"
    return "Question Bank Nepal"


def is_paper_link(title, url):
    if not PAPER_EXT_RE.search(urlparse(url).path):
        return False
    haystack = f"{title} {url}".lower()
    excluded_words = (
        "syllabus",
        "curriculum",
        "vacancy",
        "application",
        "bylaw",
        "bylaws",
        "aain",
        "ain",
    )
    return not any(word in haystack for word in excluded_words)


def extract_year(title):
    match = YEAR_RE.search(title)
    return match.group(1) if match else None


def crawl():
    session = requests.Session()
    session.headers.update({"User-Agent": "YoBook catalog scraper"})
    queue = deque(START_URLS)
    seen = set()
    groups = defaultdict(lambda: {"source_pages": set(), "papers": []})
    paper_urls = set()

    queued = {normalize_url(url) for url in START_URLS}

    while queue and len(seen) < MAX_PAGES:
        url = normalize_url(queue.popleft())
        queued.discard(url)
        parsed = urlparse(url)
        if parsed.netloc not in ALLOWED_HOSTS or SKIP_EXT_RE.search(parsed.path):
            continue
        if url in seen:
            continue

        try:
            response = session.get(url, timeout=10)
        except requests.RequestException:
            continue
        if "text/html" not in response.headers.get("content-type", ""):
            continue

        soup = BeautifulSoup(response.text, "lxml")
        exam_name = canonical_exam_name(page_label(soup, url))
        collection_name = collection_name_for(url, exam_name)
        seen.add(url)

        for anchor in soup.find_all("a", href=True):
            title = clean(anchor.get_text(" ", strip=True))
            href = normalize_url(urljoin(url, anchor["href"]))
            linked = urlparse(href)
            if not title or title.lower() in MENU_WORDS or title == "‣":
                continue
            if linked.netloc not in ALLOWED_HOSTS:
                continue

            if linked.netloc in ALLOWED_HOSTS and not SKIP_EXT_RE.search(linked.path):
                if href not in seen and href not in queued and not PAPER_EXT_RE.search(linked.path):
                    queue.append(href)
                    queued.add(href)

            if not is_paper_link(title, href) or href in paper_urls:
                continue

            paper_urls.add(href)
            key = (exam_name, collection_name)
            groups[key]["source_pages"].add(url)
            groups[key]["papers"].append(
                {
                    "title": title,
                    "year": extract_year(title),
                    "url": href,
                }
            )

    scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    records = []
    for (exam_name, collection_name), value in sorted(groups.items()):
        papers = sorted(value["papers"], key=lambda item: (item["title"].lower(), item["url"]))
        source_pages = sorted(value["source_pages"])
        records.append(
            {
                "id": stable_id(exam_name, collection_name, source_pages[0]),
                "title": exam_name,
                "collection_name": collection_name,
                "coverUrl": f"/covers/questionbanknepal/{stable_id(exam_name, collection_name, source_pages[0])}.svg",
                "author": "Question Bank Nepal",
                "language": "en",
                "country": "np",
                "source": "questionbanknepal",
                "sourceUrl": source_pages[0],
                "category": "Question Papers",
                "keywords": [
                    "Question Bank Nepal",
                    collection_name,
                    exam_name,
                    "Question Papers",
                ],
                "scrapedAt": scraped_at,
                "description": f"{exam_name} question papers from Question Bank Nepal.",
                "question_papers": papers,
            }
        )
    return records


def main():
    records = crawl()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
        file.write("\n")
    paper_count = sum(len(record["question_papers"]) for record in records)
    print(f"Wrote {len(records)} exam groups with {paper_count} question papers")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
