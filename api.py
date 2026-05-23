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
from flask import Flask, jsonify, request, render_template, send_from_directory
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
SOURCE_PRIORITY = {
    "cehrd-learning": 0,
    "cdc-nepal": 1,
    "pustakalaya": 2,
    "archive-org": 3,
    "openlibrary": 4,
}


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


def load_all_books():
    """Load the merged catalog or combine individual source files."""
    # Try merged file first
    merged = os.path.join(DATA_DIR, "all_books.json")
    if os.path.exists(merged):
        with open(merged, "r", encoding="utf-8") as f:
            return sorted(json.load(f), key=lambda b: (source_rank(b), b.get("grade") or 99, _str(b.get("subject")), _str(b.get("title"))))

    # Fallback: load all individual source files
    all_books = []
    seen = set()
    if not os.path.exists(DATA_DIR):
        return []

    for filename in os.listdir(DATA_DIR):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(DATA_DIR, filename)
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
    return render_template("index.html")


@app.route("/playground.html")
def playground():
    return send_from_directory(os.path.dirname(__file__), "playground.html")


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
            "GET /api/books/<id>": "Get single book",
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
        }
    })


@app.route("/openapi.json")
def serve_openapi():
    return send_from_directory(os.path.dirname(__file__), "openapi.json")


@app.route("/covers/<path:filename>")
def serve_cover(filename):
    return send_from_directory(COVERS_DIR, filename)


@app.route("/data/<path:filename>")
def serve_data_file(filename):
    return send_from_directory(DATA_DIR, filename)


@app.route("/api/books")
def get_books():
    books = load_all_books()

    # â”€â”€ Filters â”€â”€
    q = request.args.get("q", "").lower()
    source = request.args.get("source", "")
    grade = request.args.get("grade", "")
    subject = request.args.get("subject", "").lower()
    language = request.args.get("language", "")
    category = request.args.get("category", "").lower()

    if q:
        books = [b for b in books if
                 q in _str(b.get("title")).lower() or
                 q in _str(b.get("subject")).lower() or
                 q in _str(b.get("description")).lower() or
                 q in _str(b.get("titleLocal")).lower() or
                 any(q in _str(kw).lower() for kw in b.get("keywords", []))]

    if source:
        books = [b for b in books if b.get("source") == source]

    if grade:
        try:
            grade_int = int(grade)
            books = [b for b in books if b.get("grade") == grade_int]
        except ValueError:
            pass

    if subject:
        books = [b for b in books if subject in _str(b.get("subject")).lower()]

    if language:
        books = [b for b in books if b.get("language") == language]

    if category:
        books = [b for b in books if category in _str(b.get("category")).lower()]

    # â”€â”€ Pagination â”€â”€
    page = max(1, int(request.args.get("page", 1)))
    limit = min(200, max(1, int(request.args.get("limit", 50))))
    total = len(books)
    start = (page - 1) * limit
    end = start + limit
    paginated = books[start:end]

    return jsonify({
        "success": True,
        "data": paginated,
        "meta": {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
        }
    })


@app.route("/api/books/<book_id>")
def get_book(book_id):
    books = load_all_books()
    book = next((b for b in books if b.get("id") == book_id), None)

    if not book:
        return jsonify({"success": False, "error": "Book not found"}), 404

    return jsonify({"success": True, "data": book})


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

