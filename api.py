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

import json
import os
import argparse
import requests
from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS
from flask_swagger_ui import get_swaggerui_blueprint

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
    "cdc-library": 10,
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
    "category",
    "level",
    "audioUrl",
)


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


def compact_book(book):
    """Return the lightweight shape used by list/search responses."""
    data = {field: book[field] for field in LIST_BOOK_FIELDS if field in book}
    if book.get("id"):
        data["detailUrl"] = f"/api/books/{book['id']}"
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
    )
    values = [_str(book.get(field)) for field in fields]
    values.extend(_str(keyword) for keyword in book.get("keywords", []))
    return " ".join(values).lower()


def label_text(book):
    values = [
        _str(book.get("title")),
        _str(book.get("titleLocal")),
    ]
    values.extend(_str(keyword) for keyword in book.get("keywords", []))
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
        books = [book for book in books if category in _str(book.get("category")).lower()]

    return books


def paginated_response(books, endpoint_name="books"):
    page = max(1, int(request.args.get("page", 1)))
    limit = min(200, max(1, int(request.args.get("limit", 50))))
    total = len(books)
    start = (page - 1) * limit
    end = start + limit
    full = _bool_arg("full")
    paginated = books[start:end]

    return jsonify({
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


def is_catalog_resource_url(url, fields=("pdfUrl", "readUrl")):
    if not url or not url.startswith(("http://", "https://")):
        return False

    for book in load_all_books():
        for field in fields:
            value = book.get(field)
            if isinstance(value, str) and value == url:
                return True
        if fields and "chapterPdfUrls" in fields:
            for chapter in book.get("chapterPdfUrls", []):
                if chapter.get("pdfUrl") == url:
                    return True

    return False


def load_all_books():
    """Load merged catalog plus any individual resource files not yet merged."""
    all_books = []
    seen = set()
    if not os.path.exists(DATA_DIR):
        return []

    merged = os.path.join(DATA_DIR, "all_books.json")
    filepaths = []
    if os.path.exists(merged):
        filepaths.append(merged)

    for root, _, files in os.walk(DATA_DIR):
        for filename in sorted(files):
            if not filename.endswith(".json") or filename == "all_books.json":
                continue
            filepaths.append(os.path.join(root, filename))

    for filepath in filepaths:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for book in data:
                    bid = book.get("id")
                    if bid and bid not in seen:
                        seen.add(bid)
                        all_books.append(book)
        except Exception:
            pass

    return sorted(all_books, key=lambda b: (source_rank(b), b.get("grade") or 99, _str(b.get("subject")), _str(b.get("title"))))


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
            "GET /api/books/<id>": "Get single book",
            "GET /api/health": "Health check",
            "GET /api/pdf?url=<pdfUrl>": "Proxy a catalog PDF for same-origin reading",
            "GET /api/audio?url=<audioUrl>": "Proxy a catalog audio file for same-origin playback",
            "GET /api/sources": "List data sources",
            "GET /api/stats": "Collection statistics",
        },
        "params": {
            "q": "Search query (searches title, subject, keywords, etc.)",
            "source": "Filter by source (cehrd-learning)",
            "grade": "Filter by grade (1-12)",
            "subject": "Filter by subject (Mathematics, Science, English, etc.)",
            "language": "Filter by language (ne, en)",
            "category": "Filter by category (Textbook, Educational Resource, etc.)",
            "page": "Page number (default: 1)",
            "limit": "Results per page (default: 50, max: 200)",
            "full": "Set to true/1 to include complete book records in list responses",
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


@app.route("/data/<path:filename>")
def serve_data_file(filename):
    return send_from_directory(DATA_DIR, filename)


@app.route("/api/health")
def health_check():
    books = load_all_books()
    return jsonify({
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


@app.route("/api/books/<book_id>")
def get_book(book_id):
    books = load_all_books()
    book = next((b for b in books if b.get("id") == book_id), None)

    if not book:
        return jsonify({"success": False, "error": "Book not found"}), 404

    return jsonify({"success": True, "data": book})


@app.route("/api/pdf")
def proxy_pdf():
    url = request.args.get("url", "")
    if not is_catalog_resource_url(url, ("pdfUrl", "readUrl", "chapterPdfUrls")):
        return jsonify({"success": False, "error": "PDF URL is not part of the catalog"}), 403

    try:
        upstream = requests.get(
            url,
            stream=True,
            timeout=30,
            headers={"User-Agent": "YoBook API PDF reader/1.0"},
        )
        upstream.raise_for_status()
    except requests.RequestException:
        return jsonify({"success": False, "error": "Unable to load PDF"}), 502

    content_type = upstream.headers.get("Content-Type") or "application/pdf"
    headers = {
        "Content-Type": content_type,
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=86400",
    }

    return Response(
        stream_with_context(upstream.iter_content(chunk_size=64 * 1024)),
        headers=headers,
    )


@app.route("/api/audio")
def proxy_audio():
    url = request.args.get("url", "")
    if not is_catalog_resource_url(url, ("audioUrl",)):
        return jsonify({"success": False, "error": "Audio URL is not part of the catalog"}), 403

    try:
        upstream_headers = {"User-Agent": "YoBook API audio player/1.0"}
        if request.headers.get("Range"):
            upstream_headers["Range"] = request.headers["Range"]

        upstream = requests.get(
            url,
            stream=True,
            timeout=30,
            headers=upstream_headers,
        )
        upstream.raise_for_status()
    except requests.RequestException:
        return jsonify({"success": False, "error": "Unable to load audio"}), 502

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
        stream_with_context(upstream.iter_content(chunk_size=64 * 1024)),
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
    return jsonify({"success": True, "data": result})


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

    return jsonify({
        "success": True,
        "data": {
            "totalBooks": len(books),
            "byGrade": {str(k): v for k, v in sorted(grades.items())},
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

