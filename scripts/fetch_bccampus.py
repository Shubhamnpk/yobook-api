"""
Fetch BCcampus OpenEd books from PressBooks WP REST API.
Converts each book into the same format as other sources.

Usage:  python scripts/fetch_bccampus.py
Output: data/bccampus_open_textbooks.json

Download URL pattern:
  PDF:  {link}open/download?type=pdf
  EPUB: {link}open/download?type=epub
  Print PDF: {link}open/download?type=print_pdf
"""

import json, os, re, time, requests
from datetime import datetime, timezone

API_BASE = "https://opentextbc.ca/wp-json/pressbooks/v2/books"
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bccampus_open_textbooks.json")

def slug_from_link(link):
    m = re.search(r"https?://[^/]+/([^/]+)/?$", link)
    return m.group(1) if m else ""

def fetch_all():
    books = []
    page = 1
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    while True:
        url = "%s?page=%d" % (API_BASE, page)
        print("Fetching page %d ..." % page)
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            print("Error: HTTP %d" % r.status_code)
            break
        data = r.json()
        if not data:
            break
        for item in data:
            meta = item.get("metadata", {})
            link = item.get("link", "").rstrip("/")
            slug = slug_from_link(link)

            about_list = meta.get("about", []) or []
            subjects = []
            for a in about_list:
                name = a.get("name", "") if isinstance(a, dict) else ""
                if name:
                    subjects.append(name)

            lang = meta.get("inLanguage", "en")
            if isinstance(lang, dict):
                lang = lang.get("code", "en")
            lang = lang.split("-")[0] if "-" in lang else lang

            authors_list = meta.get("author", []) or []
            authors = []
            for a in authors_list:
                authors.append(a.get("name", "") if isinstance(a, dict) else str(a))
            author_str = ", ".join(filter(None, authors))

            description = meta.get("disambiguatingDescription", "") or ""
            if not description:
                desc = meta.get("description", "") or ""
                description = re.sub(r"<[^>]+>", "", desc)[:500]

            cover = meta.get("thumbnailUrl", "") or meta.get("image", "")

            pdf_url = link + "/open/download?type=pdf" if link else ""
            epub_url = link + "/open/download?type=epub" if link else ""
            print_pdf_url = link + "/open/download?type=print_pdf" if link else ""

            download_urls = []
            if pdf_url:
                download_urls.append(pdf_url)
            if epub_url:
                download_urls.append(epub_url)
            if print_pdf_url:
                download_urls.append(print_pdf_url)

            book = {
                "id": "bccampus-%s" % slug if slug else "bccampus-%d" % item.get("id", 0),
                "title": meta.get("name", ""),
                "author": author_str,
                "language": lang,
                "country": "ca",
                "source": "bccampus",
                "sourceUrl": link + "/" if link else "",
                "downloadUrl": download_urls,
                "coverUrl": cover,
                "category": "Textbook",
                "subject": subjects[0] if subjects else "",
                "publisher": "BCcampus Open Publishing",
                "educationLevel": "Higher Education",
                "scrapedAt": now,
                "description": description,
                "keywords": subjects,
            }
            books.append(book)

        total = r.headers.get("X-WP-Total", "?")
        print("  Fetched %d books (total: %s)" % (len(data), total))
        if len(data) < 10:
            break
        page += 1
        time.sleep(0.5)

    return books

def main():
    books = fetch_all()
    print("\nTotal books fetched: %d" % len(books))

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(books, f, indent=2, ensure_ascii=False)
    print("Written to %s" % OUTPUT)

    langs = {}
    for b in books:
        langs[b.get("language", "?")] = langs.get(b.get("language", "?"), 0) + 1
    print("\nLanguages:", langs)
    print("Sample IDs:", [b["id"] for b in books[:3]])

if __name__ == "__main__":
    main()
