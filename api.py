"""
YoBook API
===================
Simple Flask API that serves the scraped JSON data.

Endpoints:
  GET /api/books                   â€” All books
  GET /api/books?source=cehrd-learning â€” Filter by source
  GET /api/books?grade=9            â€” Filter by grade
  GET /api/books?subject=Science    â€” Filter by subject
  GET /api/books?q=math             â€” Search query
  GET /api/books/<id>               â€” Single book by ID
  GET /api/sources                  â€” Available data sources
  GET /api/stats                    â€” Collection statistics

Usage:
  python api.py                  # Run on port 5000
  python api.py --port 8080      # Custom port
"""

import argparse
import hashlib
import json
import logging
import os
import re
import time
import uuid
from email.utils import formatdate
from urllib.parse import urlparse

import requests
from flask import (
    Flask,
    Response,
    g,
    jsonify,
    make_response,
    request,
    send_from_directory,
    stream_with_context,
)
from flask_cors import CORS
from flask_swagger_ui import get_swaggerui_blueprint
from werkzeug.exceptions import BadRequest, HTTPException

app = Flask(__name__)
CORS(app)

# â”€â”€ Swagger Configuration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SWAGGER_URL = "/docs"
API_URL = "/openapi.json"
swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL,
    API_URL,
    config={
        "app_name": "YoBook API"
    }
)
app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
CATALOG_HELPER_JSON_FILES = {
    "gradewise_audio_links.json",
    "tucl_thesis_dissertations.json",
    "tu_reports.json",
}
THESIS_DATA_FILE = os.path.join(DATA_DIR, "Reference Materials", "tucl_thesis_dissertations.json")
REPORT_DATA_FILE = os.path.join(DATA_DIR, "Reference Materials", "tu_reports.json")
TU_RESEARCH_DATA_FILES = (THESIS_DATA_FILE, REPORT_DATA_FILE)
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
}
LIST_BOOK_FIELDS = (
    "id",
    "title",
    "titleLocal",
    "author",
    "grade",
    "subject",
    "language",
    "source",
    "coverUrl",
    "downloadUrl",
    "category",
    "materialType",
    "level",
    "collection_name",
    "audioUrl",
)
CACHE_TTL_SECONDS = int(os.environ.get("CATALOG_CACHE_TTL_SECONDS", "300"))
PUBLIC_CACHE_MAX_AGE = int(os.environ.get("PUBLIC_CACHE_MAX_AGE", "300"))
PUBLIC_CACHE_SWR = int(os.environ.get("PUBLIC_CACHE_STALE_WHILE_REVALIDATE", "300"))
UPSTREAM_TIMEOUT_SECONDS = int(os.environ.get("UPSTREAM_TIMEOUT_SECONDS", "20"))
MAX_PROXY_BYTES = int(os.environ.get("MAX_PROXY_BYTES", str(50 * 1024 * 1024)))
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS_PER_MINUTE", "120"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
EXCLUDED_IDS_FILE = os.path.join(DATA_DIR, "pustakalaya_duplicates.json")
EXCLUDED_IDS = []
ALLOWED_PROXY_HOSTS = {
    "learning.cehrd.gov.np",
    "cehrd.gov.np",
    "www.cehrd.gov.np",
    "pustakalaya.org",
    "www.pustakalaya.org",
    "archive.org",
    "www.archive.org",
    "ia601407.us.archive.org",
    "assets.openstax.org",
    "ncert.nic.in",
    "standardebooks.org",
    "questionbanknepal.com",
    "old.questionbanknepal.com",
    "shisiradhikari.com.np",
}
CATALOG_CACHE = {
    "books": [],
    "last_loaded": 0.0,
    "last_mtime": 0.0,
    "fingerprint": "bootstrap",
}
GRADEWISE_AUDIO_CACHE = {
    "data": None,
    "last_loaded": 0.0,
    "last_mtime": 0.0,
}
TU_RESEARCH_CACHE = {
    "items": [],
    "last_loaded": 0.0,
    "last_mtime": 0.0,
    "fingerprint": "tu-research-bootstrap",
}
RATE_LIMIT_BUCKETS = {}
app.logger.setLevel(logging.INFO)


def _load_excluded_ids():
    if os.path.exists(EXCLUDED_IDS_FILE):
        try:
            with open(EXCLUDED_IDS_FILE, "r", encoding="utf-8") as f:
                EXCLUDED_IDS[:] = json.load(f)
        except Exception:
            EXCLUDED_IDS[:] = []


def source_rank(book_or_source):
    source = book_or_source if isinstance(book_or_source, str) else book_or_source.get("source", "")
    return SOURCE_PRIORITY.get(source, 99)


def _str(val):
    """Safely get a string from a value that might be a list, None, etc."""
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(v) for v in val)
    return str(val)


def _bool_arg(name, default=False):
    value = request.args.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "full"}


def _int_arg(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise BadRequest(f"Query parameter '{name}' must be an integer") from exc

    if minimum is not None and value < minimum:
        raise BadRequest(f"Query parameter '{name}' must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise BadRequest(f"Query parameter '{name}' must be <= {maximum}")
    return value


def _client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _json_error(message, status=400):
    return jsonify({"success": False, "error": message}), status


def _normalize_grade_sort_key(value):
    text = _str(value).strip().lower()
    if not text:
        return (2, "zz")
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return (0, int(digits))
    return (1, text)


def _normalize_text(value):
    text = _str(value).lower()
    text = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", text)
    return " ".join(text.split())


def _grade_from_book(book):
    grade = _str(book.get("grade")).strip()
    if grade:
        return grade

    text = " ".join([
        _str(book.get("title")),
        _str(book.get("titleLocal")),
        " ".join(_str(keyword) for keyword in book.get("keywords", [])),
    ]).lower()
    match = re.search(r"\b(?:grade|class)\s*[-:]?\s*(\d{1,2})\b", text)
    if match:
        return match.group(1)
    return ""


def _data_fingerprint(books, latest_mtime):
    seed = f"{latest_mtime}:{len(books)}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return f"catalog-{digest}"


def _audio_fingerprint(data, latest_mtime):
    stats = data.get("stats", {}) if isinstance(data, dict) else {}
    seed = f"{latest_mtime}:{stats.get('audioLinks', 0)}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return f"gradewise-audio-{digest}"


def _tu_research_fingerprint(items, latest_mtime):
    seed = f"{latest_mtime}:{len(items)}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return f"tu-research-{digest}"


def _set_public_cache_headers(response, etag=None):
    response.headers["Cache-Control"] = (
        f"public, max-age={PUBLIC_CACHE_MAX_AGE}, stale-while-revalidate={PUBLIC_CACHE_SWR}"
    )
    if etag:
        response.headers["ETag"] = etag
    if CATALOG_CACHE.get("last_mtime"):
        response.headers["Last-Modified"] = formatdate(CATALOG_CACHE["last_mtime"], usegmt=True)
    return response


def _json_with_cache(payload):
    response = make_response(jsonify(payload))
    etag = CATALOG_CACHE.get("fingerprint")
    inm = request.headers.get("If-None-Match")
    if etag and inm and etag in [token.strip() for token in inm.split(",")]:
        return _set_public_cache_headers(make_response("", 304), etag=etag)
    return _set_public_cache_headers(response, etag=etag)


def public_book_id(book):
    """Return the stable public identifier used in detail URLs."""
    book_id = _str(book.get("id"))
    if book.get("source") == "cehrd-learning" and book_id.startswith("cehrd-learning-"):
        suffix = book_id.removeprefix("cehrd-learning-")
        if "-" in suffix:
            core, maybe_resource_id = suffix.rsplit("-", 1)
            if maybe_resource_id.isdigit():
                suffix = core
        return f"cehrd-{suffix}"
    return book_id


def book_id_matches(book, requested_id):
    book_id = _str(book.get("id"))
    return book_id == requested_id or public_book_id(book) == requested_id


def compact_book(book):
    """Return the lightweight shape used by list/search responses."""
    data = {field: book[field] for field in LIST_BOOK_FIELDS if field in book}
    if book.get("id"):
        data["detailUrl"] = f"/api/books/{public_book_id(book)}"
    if isinstance(book.get("question_papers"), list):
        data["questionPaperCount"] = len(book["question_papers"])
    return data


def compact_tu_research(item):
    fields = (
        "id",
        "title",
        "author",
        "language",
        "source",
        "sourceUrl",
        "coverUrl",
        "category",
        "subcategory",
        "keywords",
        "publishedYear",
        "academicLevel",
        "institutes",
        "institute",
        "affiliatedInstitute",
        "otherInstitute",
        "publisher",
        "readUrl",
        "downloadUrl",
    )
    data = {field: item[field] for field in fields if field in item}
    if item.get("id"):
        data["detailUrl"] = f"/api/research/{item['id']}"
    return data


def searchable_text(book):
    fields = (
        "title",
        "titleLocal",
        "author",
        "subject",
        "description",
        "publisher",
        "grade",
        "category",
        "source",
        "educationLevel",
        "exam_name",
        "collection_name",
    )
    values = [_str(book.get(field)) for field in fields]
    values.extend(_str(keyword) for keyword in book.get("keywords", []))
    values.extend(
        " ".join(
            _str(paper.get(field))
            for field in ("title", "year")
        )
        for paper in book.get("question_papers", [])
        if isinstance(paper, dict)
    )
    return " ".join(values).lower()


def tu_research_searchable_text(item):
    fields = (
        "title",
        "author",
        "description",
        "publisher",
        "publishedYear",
        "academicLevel",
        "institutes",
        "institute",
        "affiliatedInstitute",
        "otherInstitute",
        "advisor",
        "category",
        "subcategory",
        "source",
    )
    values = [_str(item.get(field)) for field in fields]
    values.extend(_str(keyword) for keyword in item.get("keywords", []))
    return " ".join(values).lower()


def label_text(book):
    values = [
        _str(book.get("title")),
        _str(book.get("titleLocal")),
    ]
    values.extend(_str(keyword) for keyword in book.get("keywords", []))
    return " ".join(values).lower()


def category_text(book):
    values = [
        _str(book.get("category")),
        _str(book.get("materialType")),
    ]
    return " ".join(values).lower()


def grade_matches(book_grade, requested_grade):
    if not requested_grade:
        return True

    requested = _str(requested_grade).strip().lower()
    actual = _str(book_grade).strip().lower()
    if not actual:
        return False

    if actual == requested:
        return True

    digits = "".join(ch for ch in requested if ch.isdigit())
    if not digits:
        return False

    return actual == digits or actual == f"grade {digits}" or actual == f"class {digits}"


def is_teacher_guide(book):
    text = label_text(book)
    needles = (
        "teacher's guide",
        "teachers' guide",
        "teachers guide",
        "teachers guides",
        "teacher guide",
        "teaching manual",
        "शिक्षक निर्देशिका",
    )
    return any(needle in text for needle in needles)


def is_curriculum(book):
    title = f"{_str(book.get('title'))} {_str(book.get('titleLocal'))}".lower()
    if "curriculum" in title or "curricular" in title or "पाठ्यक्रम" in title:
        return True

    for keyword in book.get("keywords", []):
        value = _str(keyword).lower()
        if value in {"curriculum development centre", "पाठ्यक्रम विकास केन्द्र"}:
            continue
        if "curriculum" in value or "curricular" in value or "पाठ्यक्रम" in value:
            return True

    return False


def is_textbook(book):
    if book.get("source") in {"cehrd-learning", "ncert-official"}:
        return True

    text = label_text(book)
    if "textbook" in text or "old textbooks" in text:
        return True

    return _str(book.get("category")).lower() == "textbook"


def is_material_source(book):
    return book.get("source") in {
        "pustakalaya-course",
        "pustakalaya-teaching",
        "pustakalaya-other-educational",
        "cdc-library",
    }


def apply_book_filters(books, forced_filter=None):
    q = request.args.get("q", "").lower().strip()
    source = request.args.get("source", "").strip()
    grade = request.args.get("grade", "").strip()
    subject = request.args.get("subject", "").lower().strip()
    language = request.args.get("language", "").strip()
    category = request.args.get("category", "").lower().strip()

    if forced_filter:
        books = [book for book in books if forced_filter(book)]

    if q:
        terms = [term for term in q.split() if term]
        books = [
            book for book in books
            if all(term in searchable_text(book) for term in terms)
        ]

    if source:
        books = [book for book in books if book.get("source") == source]

    if grade:
        books = [book for book in books if grade_matches(book.get("grade"), grade)]

    if subject:
        books = [book for book in books if subject in _str(book.get("subject")).lower()]

    if language:
        books = [book for book in books if book.get("language") == language]

    if category:
        books = [book for book in books if category in category_text(book)]

    return books


def paginated_response(books, endpoint_name="books"):
    page = _int_arg("page", 1, minimum=1)
    limit = _int_arg("limit", 50, minimum=1, maximum=200)
    total = len(books)
    start = (page - 1) * limit
    end = start + limit
    full = _bool_arg("full")
    paginated = books[start:end]

    return _json_with_cache({
        "success": True,
        "data": paginated if full else [compact_book(book) for book in paginated],
        "meta": {
            "endpoint": endpoint_name,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
            "detail": "full" if full else "compact",
        }
    })


def is_catalog_resource_url(url, fields=("downloadUrl", "readUrl")):
    if not url or not url.startswith(("http://", "https://")):
        return False

    for book in load_all_books():
        for field in fields:
            value = book.get(field)
            if isinstance(value, str) and value == url:
                return True
            if isinstance(value, list) and url in value:
                return True
        if fields and "chapterDownloadUrls" in fields:
            for chapter in book.get("chapterDownloadUrls", []):
                if chapter.get("downloadUrl") == url:
                    return True
        if fields and "chapterPdfUrls" in fields:
            for chapter in book.get("chapterPdfUrls", []):
                if chapter.get("pdfUrl") == url:
                    return True
        for paper in book.get("question_papers", []):
            if isinstance(paper, dict):
                for field in ("readUrl", "downloadUrl", "url"):
                    if paper.get(field) == url:
                        return True

    if "audioUrl" in fields and is_gradewise_audio_url(url):
        return True

    for thesis in load_tu_research():
        for field in fields:
            value = thesis.get(field)
            if isinstance(value, str) and value == url:
                return True
            if isinstance(value, list) and url in value:
                return True

    host = urlparse(url).hostname or ""
    if host not in ALLOWED_PROXY_HOSTS:
        return False

    return False


def load_gradewise_audio():
    filepath = os.path.join(DATA_DIR, "gradewise_audio_links.json")
    if not os.path.exists(filepath):
        return {"source": "", "scrapedAt": "", "stats": {}, "grades": []}

    now = time.time()
    mtime = os.path.getmtime(filepath)
    if (
        GRADEWISE_AUDIO_CACHE["data"] is not None
        and GRADEWISE_AUDIO_CACHE["last_mtime"] == mtime
        and (now - GRADEWISE_AUDIO_CACHE["last_loaded"]) < CACHE_TTL_SECONDS
    ):
        return GRADEWISE_AUDIO_CACHE["data"]

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    GRADEWISE_AUDIO_CACHE["data"] = data
    GRADEWISE_AUDIO_CACHE["last_loaded"] = now
    GRADEWISE_AUDIO_CACHE["last_mtime"] = mtime
    return data


def is_gradewise_audio_url(url):
    for grade in load_gradewise_audio().get("grades", []):
        for subject in grade.get("subjects", []):
            for chapter in subject.get("chapters", []):
                if chapter.get("url") == url:
                    return True
    return False


def filter_gradewise_audio(data, grade=None, subject=None):
    filtered = {
        "source": data.get("source", ""),
        "scrapedAt": data.get("scrapedAt", ""),
        "stats": data.get("stats", {}),
        "grades": [],
    }
    requested_grade = _str(grade).strip() if grade else ""
    requested_subject = _str(subject).strip().lower() if subject else ""

    for grade_item in data.get("grades", []):
        grade_number = _str(grade_item.get("grade"))
        if requested_grade and grade_number != requested_grade:
            continue

        subjects = []
        for subject_item in grade_item.get("subjects", []):
            subject_name = _str(subject_item.get("subject"))
            if requested_subject and subject_name.lower() != requested_subject:
                continue
            subjects.append(subject_item)

        if subjects:
            filtered["grades"].append({
                "grade": grade_item.get("grade"),
                "subjects": subjects,
            })

    audio_count = 0
    chapter_keys = set()
    for grade_item in filtered["grades"]:
        for subject_item in grade_item.get("subjects", []):
            for chapter in subject_item.get("chapters", []):
                audio_count += 1
                chapter_keys.add((
                    grade_item.get("grade"),
                    subject_item.get("subject"),
                    chapter.get("chapter"),
                    chapter.get("chapterName"),
                ))
    filtered["stats"] = {
        "grades": len(filtered["grades"]),
        "subjects": sum(len(grade_item.get("subjects", [])) for grade_item in filtered["grades"]),
        "chapters": len(chapter_keys),
        "audioLinks": audio_count,
    }
    return filtered


def _read_json_list(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def load_tu_research():
    now = time.time()
    latest_mtime = 0.0
    source_files = []
    for data_file in TU_RESEARCH_DATA_FILES:
        source_files.append(data_file)
        source_files.append(f"{data_file}.progress.jsonl")
    for filepath in source_files:
        if os.path.exists(filepath):
            latest_mtime = max(latest_mtime, os.path.getmtime(filepath))

    if (
        TU_RESEARCH_CACHE["items"]
        and TU_RESEARCH_CACHE["last_mtime"] == latest_mtime
        and (now - TU_RESEARCH_CACHE["last_loaded"]) < CACHE_TTL_SECONDS
    ):
        return TU_RESEARCH_CACHE["items"]

    items_by_id = {}
    for data_file in TU_RESEARCH_DATA_FILES:
        for item in _read_json_list(data_file):
            item_id = item.get("id")
            if item_id:
                items_by_id[item_id] = item

        progress_file = f"{data_file}.progress.jsonl"
        if os.path.exists(progress_file):
            with open(progress_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    item_id = item.get("id")
                    if item_id:
                        items_by_id[item_id] = item

    items = sorted(
        items_by_id.values(),
        key=lambda item: (
            _str(item.get("category")).lower(),
            _str(item.get("subcategory")).lower(),
            _str(item.get("publishedYear")).lower(),
            _str(item.get("title")).lower(),
        ),
    )
    TU_RESEARCH_CACHE["items"] = items
    TU_RESEARCH_CACHE["last_loaded"] = now
    TU_RESEARCH_CACHE["last_mtime"] = latest_mtime
    TU_RESEARCH_CACHE["fingerprint"] = _tu_research_fingerprint(items, latest_mtime)
    return items


def load_tu_theses():
    return load_tu_research()


def apply_tu_research_filters(items, default_category=None):
    q = request.args.get("q", "").lower().strip()
    category = request.args.get("category", default_category or "").lower().strip()
    subcategory = request.args.get("subcategory", "").lower().strip()
    academic_level = request.args.get("academicLevel", "").lower().strip()
    institute = request.args.get("institute", "").lower().strip()
    author = request.args.get("author", "").lower().strip()
    year = request.args.get("year", "").lower().strip()
    language = request.args.get("language", "").strip()

    if q:
        terms = [term for term in q.split() if term]
        items = [
            item for item in items
            if all(term in tu_research_searchable_text(item) for term in terms)
        ]

    if category:
        items = [
            item for item in items
            if category in _str(item.get("category")).lower()
        ]

    if subcategory:
        items = [
            item for item in items
            if subcategory in _str(item.get("subcategory")).lower()
        ]

    if academic_level:
        items = [
            item for item in items
            if academic_level in _str(item.get("academicLevel")).lower()
        ]

    if institute:
        items = [
            item for item in items
            if institute in " ".join(
                _str(item.get(field))
                for field in ("institutes", "institute", "affiliatedInstitute", "otherInstitute", "publisher")
            ).lower()
        ]

    if author:
        items = [
            item for item in items
            if author in _str(item.get("author")).lower()
        ]

    if year:
        items = [
            item for item in items
            if _str(item.get("publishedYear")).lower().startswith(year)
        ]

    if language:
        items = [item for item in items if item.get("language") == language]

    return items


def tu_research_paginated_response(items, endpoint_name="research"):
    page = _int_arg("page", 1, minimum=1)
    limit = _int_arg("limit", 50, minimum=1, maximum=200)
    total = len(items)
    start = (page - 1) * limit
    end = start + limit
    full = _bool_arg("full")
    paginated = items[start:end]
    response = make_response(jsonify({
        "success": True,
        "data": paginated if full else [compact_tu_research(item) for item in paginated],
        "meta": {
            "endpoint": endpoint_name,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
            "detail": "full" if full else "compact",
        }
    }))
    return _set_public_cache_headers(response, etag=TU_RESEARCH_CACHE.get("fingerprint"))


def apply_thesis_filters(theses):
    return apply_tu_research_filters(theses, default_category="Thesis")


def thesis_paginated_response(theses, endpoint_name="theses"):
    return tu_research_paginated_response(theses, endpoint_name)


def load_all_books():
    """Load merged catalog plus any individual resource files not yet merged."""
    if not os.path.exists(DATA_DIR):
        return []
    now = time.time()
    if CATALOG_CACHE["books"] and (now - CATALOG_CACHE["last_loaded"]) < CACHE_TTL_SECONDS:
        return CATALOG_CACHE["books"]

    merged = os.path.join(DATA_DIR, "all_books.json")
    filepaths = []
    if os.path.exists(merged):
        filepaths.append(merged)

    for root, _, files in os.walk(DATA_DIR):
        for filename in sorted(files):
            if (
                not filename.endswith(".json")
                or filename == "all_books.json"
                or filename in CATALOG_HELPER_JSON_FILES
            ):
                continue
            filepaths.append(os.path.join(root, filename))

    _load_excluded_ids()

    latest_mtime = 0.0
    all_books = []
    seen = set()
    for filepath in filepaths:
        latest_mtime = max(latest_mtime, os.path.getmtime(filepath))
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for book in data:
                    if book.get("source") == "tu":
                        continue
                    bid = book.get("id")
                    if bid and bid not in seen:
                        seen.add(bid)
                        all_books.append(book)
        except Exception:
            pass

    indexed_books = [
        book for book in all_books
        if book.get("id") not in EXCLUDED_IDS
    ]
    sorted_books = sorted(
        indexed_books,
        key=lambda b: (
            source_rank(b),
            _normalize_grade_sort_key(b.get("grade")),
            _str(b.get("subject")).lower(),
            _str(b.get("title")).lower(),
        ),
    )
    CATALOG_CACHE["books"] = sorted_books
    CATALOG_CACHE["last_loaded"] = now
    CATALOG_CACHE["last_mtime"] = latest_mtime
    CATALOG_CACHE["fingerprint"] = _data_fingerprint(sorted_books, latest_mtime)
    return sorted_books


def _stream_with_limit(upstream):
    total = 0
    for chunk in upstream.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_PROXY_BYTES:
            break
        yield chunk


@app.before_request
def track_request_context():
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.request_started = time.perf_counter()
    if request.path.startswith("/api"):
        key = (_client_ip(), int(time.time() / RATE_LIMIT_WINDOW_SECONDS))
        RATE_LIMIT_BUCKETS[key] = RATE_LIMIT_BUCKETS.get(key, 0) + 1
        if RATE_LIMIT_BUCKETS[key] > RATE_LIMIT_REQUESTS:
            return _json_error("Rate limit exceeded. Please retry later.", 429)
    return None


@app.after_request
def add_request_metadata(response):
    response.headers["X-Request-ID"] = getattr(g, "request_id", "")
    duration_ms = (time.perf_counter() - getattr(g, "request_started", time.perf_counter())) * 1000
    app.logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
        getattr(g, "request_id", "-"),
        request.method,
        request.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    return _json_error(exc.description, exc.code)


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    app.logger.exception("Unhandled error")
    return _json_error("Internal server error", 500)


# â”€â”€ Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "index.html")


@app.route("/playground.html")
def playground():
    return send_from_directory(os.path.dirname(__file__), "playground.html")


@app.route("/about")
@app.route("/about.html")
def about():
    return send_from_directory(os.path.dirname(__file__), "about.html")


@app.route("/api")
def api_docs_route():
    return jsonify({
        "name": "YoBook API",
        "version": "1.0.0",
        "description": "Nepal educational book catalog API",
        "documentation": "/docs",
        "openapi_spec": "/openapi.json",
        "endpoints": {
            "GET /api/books": "Search & filter books",
            "GET /api/search": "Dedicated search endpoint",
            "GET /api/textbooks": "Student textbook books",
            "GET /api/course-materials": "Course material books",
            "GET /api/teacher-guides": "Teacher guide books",
            "GET /api/curriculum": "Curriculum books",
            "GET /api/ncert": "NCERT textbook collections",
            "GET /api/research": "Dedicated TU research search for theses and reports",
            "GET /api/research/<id>": "Get single TU research item",
            "GET /api/theses": "TU thesis-only search alias",
            "GET /api/theses/<id>": "Get single TU thesis by ID",
            "GET /api/gradewise-audio": "Grade-wise Pustakalaya audio links",
            "GET /api/books/<id>": "Get single book",
            "GET /api/health": "Health check",
            "GET /api/download?url=<downloadUrl>": "Proxy a catalog download for same-origin reading",
            "GET /api/audio?url=<audioUrl>": "Proxy a catalog audio file for same-origin playback",
            "GET /api/sources": "List data sources",
            "GET /api/stats": "Collection statistics",
        },
        "params": {
            "q": "Search query (searches title, subject, keywords, etc.)",
            "source": "Filter by source (cehrd-learning)",
            "grade": "Filter by grade (1-12)",
            "subject": "Filter by subject (Mathematics, Science, English, etc.; also supported by /api/gradewise-audio)",
            "language": "Filter by language (ne, en)",
            "category": "Filter by category (Textbook, Educational Resource, etc.)",
            "research": "Use /api/research for TU theses and reports with q, category, subcategory, academicLevel, institute, author, year, language, page, limit, and full",
            "page": "Page number (default: 1)",
            "limit": "Results per page (default: 50, max: 200)",
            "full": "Set to true/1 to include complete book records in list responses",
            "question_papers": "Grouped question-paper records expose nested paper files in detail/full responses",
        }
    })


@app.route("/openapi.json")
def serve_openapi():
    return send_from_directory(os.path.dirname(__file__), "openapi.json")


@app.route("/covers/<path:filename>")
def serve_cover(filename):
    return send_from_directory(COVERS_DIR, filename)


@app.route("/assets/<path:filename>")
def serve_asset(filename):
    return send_from_directory(ASSETS_DIR, filename)


@app.route("/favicon.ico")
def serve_favicon():
    return send_from_directory(ASSETS_DIR, "yobook-logo.svg", mimetype="image/svg+xml")


@app.route("/data/<path:filename>")
def serve_data_file(filename):
    return send_from_directory(DATA_DIR, filename)


@app.route("/api/health")
def health_check():
    books = load_all_books()
    return _json_with_cache({
        "success": True,
        "status": "ok",
        "books": len(books),
        "sources": len({book.get("source") for book in books if book.get("source")}),
    })


@app.route("/api/books")
def get_books():
    books = load_all_books()
    return paginated_response(apply_book_filters(books), "books")


@app.route("/api/search")
def search_books():
    """Dedicated search endpoint for UI search boxes."""
    books = load_all_books()
    return paginated_response(apply_book_filters(books), "search")


@app.route("/api/research")
def get_research():
    items = load_tu_research()
    return tu_research_paginated_response(apply_tu_research_filters(items), "research")


@app.route("/api/research/<item_id>")
def get_research_item(item_id):
    item = next((record for record in load_tu_research() if record.get("id") == item_id), None)
    if not item:
        return _json_error("Research item not found", 404)
    response = make_response(jsonify({"success": True, "data": item}))
    return _set_public_cache_headers(response, etag=TU_RESEARCH_CACHE.get("fingerprint"))


@app.route("/api/theses")
def get_theses():
    theses = load_tu_theses()
    return thesis_paginated_response(apply_thesis_filters(theses), "theses")


@app.route("/api/theses/<thesis_id>")
def get_thesis(thesis_id):
    thesis = next(
        (
            item for item in load_tu_research()
            if item.get("id") == thesis_id and item.get("category") == "Thesis"
        ),
        None,
    )
    if not thesis:
        return _json_error("Thesis not found", 404)
    response = make_response(jsonify({"success": True, "data": thesis}))
    return _set_public_cache_headers(response, etag=TU_RESEARCH_CACHE.get("fingerprint"))


@app.route("/api/course-materials")
def get_course_materials():
    books = load_all_books()
    books = apply_book_filters(
        books,
        lambda book: _str(book.get("category")).lower() == "course materials",
    )
    return paginated_response(books, "course-materials")


@app.route("/api/textbooks")
def get_textbooks():
    books = load_all_books()
    return paginated_response(apply_book_filters(books, is_textbook), "textbooks")


@app.route("/api/teacher-guides")
def get_teacher_guides():
    books = load_all_books()
    return paginated_response(
        apply_book_filters(books, lambda book: is_material_source(book) and is_teacher_guide(book)),
        "teacher-guides",
    )


@app.route("/api/curriculum")
def get_curriculum():
    books = load_all_books()
    return paginated_response(
        apply_book_filters(books, lambda book: is_material_source(book) and is_curriculum(book)),
        "curriculum",
    )


@app.route("/api/ncert")
def get_ncert_books():
    books = load_all_books()
    books = apply_book_filters(
        books,
        lambda book: book.get("source") == "ncert-official",
    )
    return paginated_response(books, "ncert")


@app.route("/api/gradewise-audio")
def get_gradewise_audio():
    data = load_gradewise_audio()
    result = filter_gradewise_audio(
        data,
        grade=request.args.get("grade"),
        subject=request.args.get("subject"),
    )
    response = make_response(jsonify({"success": True, "data": result}))
    return _set_public_cache_headers(
        response,
        etag=_audio_fingerprint(data, GRADEWISE_AUDIO_CACHE.get("last_mtime", 0.0)),
    )


@app.route("/api/books/<book_id>")
def get_book(book_id):
    books = load_all_books()
    book = next((b for b in books if book_id_matches(b, book_id)), None)

    if not book:
        return _json_error("Book not found", 404)

    return _json_with_cache({"success": True, "data": book})


@app.route("/api/download")
@app.route("/api/pdf")
def proxy_download():
    url = request.args.get("url", "")
    if not is_catalog_resource_url(
        url,
        ("downloadUrl", "readUrl", "chapterDownloadUrls", "pdfUrl", "chapterPdfUrls"),
    ):
        return _json_error("Download URL is not part of the catalog", 403)

    try:
        upstream = requests.get(
            url,
            stream=True,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
            headers={"User-Agent": "YoBook API download reader/1.0"},
        )
        upstream.raise_for_status()
    except requests.RequestException:
        return _json_error("Unable to load download", 502)
    content_length = int(upstream.headers.get("Content-Length", "0") or "0")
    if content_length and content_length > MAX_PROXY_BYTES:
        upstream.close()
        return _json_error("Download exceeds max allowed size", 413)

    content_type = upstream.headers.get("Content-Type") or "application/pdf"
    headers = {
        "Content-Type": content_type,
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=86400",
    }

    return Response(
        stream_with_context(_stream_with_limit(upstream)),
        headers=headers,
    )


@app.route("/api/audio")
def proxy_audio():
    url = request.args.get("url", "")
    if not is_catalog_resource_url(url, ("audioUrl",)):
        return _json_error("Audio URL is not part of the catalog", 403)

    try:
        upstream_headers = {"User-Agent": "YoBook API audio player/1.0"}
        if request.headers.get("Range"):
            upstream_headers["Range"] = request.headers["Range"]

        upstream = requests.get(
            url,
            stream=True,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
            headers=upstream_headers,
        )
        upstream.raise_for_status()
    except requests.RequestException:
        return _json_error("Unable to load audio", 502)
    content_length = int(upstream.headers.get("Content-Length", "0") or "0")
    if content_length and content_length > MAX_PROXY_BYTES:
        upstream.close()
        return _json_error("Audio exceeds max allowed size", 413)

    content_type = upstream.headers.get("Content-Type") or "audio/mpeg"
    headers = {
        "Content-Type": content_type,
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=86400",
        "Accept-Ranges": upstream.headers.get("Accept-Ranges", "bytes"),
    }
    for header in ("Content-Length", "Content-Range"):
        if upstream.headers.get(header):
            headers[header] = upstream.headers[header]

    return Response(
        stream_with_context(_stream_with_limit(upstream)),
        headers=headers,
        status=upstream.status_code,
    )


@app.route("/api/sources")
def get_sources():
    books = load_all_books()
    sources = {}

    for book in books:
        src = book.get("source", "unknown")
        if src not in sources:
            sources[src] = {"name": src, "count": 0, "grades": set(), "subjects": set()}
        sources[src]["count"] += 1
        if book.get("grade"):
            sources[src]["grades"].add(book["grade"])
        if book.get("subject"):
            sources[src]["subjects"].add(book["subject"])

    # Convert sets to sorted lists for JSON
    result = []
    for key, val in sources.items():
        result.append({
            "source": key,
            "count": val["count"],
            "grades": sorted(val["grades"]),
            "subjects": sorted(val["subjects"]),
        })

    result.sort(key=lambda item: source_rank(item["source"]))
    return _json_with_cache({"success": True, "data": result})


@app.route("/api/stats")
def get_stats():
    books = load_all_books()

    grades = {}
    subjects = {}
    sources = {}
    languages = {}

    for book in books:
        g = book.get("grade")
        if g and not isinstance(g, list):
            grades[g] = grades.get(g, 0) + 1

        s = book.get("subject")
        if s and isinstance(s, str):
            subjects[s] = subjects.get(s, 0) + 1

        src = _str(book.get("source")) or "unknown"
        sources[src] = sources.get(src, 0) + 1

        lang = _str(book.get("language")) or "unknown"
        languages[lang] = languages.get(lang, 0) + 1

    by_grade = {
        str(k): v for k, v in sorted(grades.items(), key=lambda item: _normalize_grade_sort_key(item[0]))
    }
    return _json_with_cache({
        "success": True,
        "data": {
            "totalBooks": len(books),
            "byGrade": by_grade,
            "bySubject": dict(sorted(subjects.items())),
            "bySource": sources,
            "byLanguage": languages,
        }
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YoBook API")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"YoBook API running on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)

