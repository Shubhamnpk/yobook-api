const DATA_URL = "/data/all_books.json";
const LIST_FIELDS = [
  "id",
  "title",
  "titleLocal",
  "author",
  "grade",
  "subject",
  "language",
  "country",
  "source",
  "readUrl",
  "downloadUrl",
  "coverUrl",
  "category",
  "materialType",
  "keywords",
  "description",
];

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "cache-control": "public, max-age=300",
    },
  });
}

function html(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=300",
    },
  });
}

function textValue(value) {
  if (value == null) return "";
  if (Array.isArray(value)) return value.join(" ");
  return String(value);
}

function bookText(book) {
  return [
    book.title,
    book.titleLocal,
    book.author,
    book.subject,
    book.category,
    book.materialType,
    book.language,
    book.source,
    ...(Array.isArray(book.keywords) ? book.keywords : []),
  ]
    .map(textValue)
    .join(" ")
    .toLowerCase();
}

function matchesFilter(book, key, expected) {
  if (!expected) return true;
  return textValue(book[key]).toLowerCase() === expected.toLowerCase();
}

function listBook(book, full) {
  if (full) return book;
  const result = {};
  for (const key of LIST_FIELDS) {
    if (book[key] !== undefined) result[key] = book[key];
  }
  return result;
}

async function loadBooks(request, env) {
  const url = new URL(DATA_URL, request.url);
  const response = await env.ASSETS.fetch(new Request(url, request));
  if (!response.ok) {
    throw new Error(`Unable to load ${DATA_URL}`);
  }
  return response.json();
}

function filterBooks(books, params, extraPredicate = () => true) {
  const q = (params.get("q") || "").trim().toLowerCase();
  const source = params.get("source");
  const grade = params.get("grade");
  const subject = params.get("subject");
  const language = params.get("language");
  const category = params.get("category");

  return books.filter((book) => {
    if (!extraPredicate(book)) return false;
    if (q && !bookText(book).includes(q)) return false;
    if (!matchesFilter(book, "source", source)) return false;
    if (!matchesFilter(book, "subject", subject)) return false;
    if (!matchesFilter(book, "language", language)) return false;
    if (!matchesFilter(book, "category", category)) return false;
    if (grade && textValue(book.grade) !== grade) return false;
    return true;
  });
}

function paginate(books, params, name = "books") {
  const page = Math.max(parseInt(params.get("page") || "1", 10), 1);
  const limit = Math.min(Math.max(parseInt(params.get("limit") || "50", 10), 1), 200);
  const full = ["1", "true", "yes"].includes((params.get("full") || "").toLowerCase());
  const start = (page - 1) * limit;
  const pageItems = books.slice(start, start + limit).map((book) => listBook(book, full));

  return {
    success: true,
    data: pageItems,
    pagination: {
      page,
      limit,
      total: books.length,
      totalPages: Math.ceil(books.length / limit),
      hasNext: start + limit < books.length,
      hasPrev: page > 1,
    },
    endpoint: name,
  };
}

function categoryText(book) {
  return `${textValue(book.category)} ${textValue(book.materialType)}`.toLowerCase();
}

function isTextbook(book) {
  return categoryText(book).includes("textbook");
}

function isCourseMaterial(book) {
  return textValue(book.category).toLowerCase() === "course materials";
}

function isTeacherGuide(book) {
  return categoryText(book).includes("teacher guide");
}

function isCurriculum(book) {
  return categoryText(book).includes("curriculum");
}

async function handleApi(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (path === "/api" || path === "/api/") {
    return json({
      name: "YoBook API",
      version: "1.0.0",
      description: "Nepal educational book catalog API",
      endpoints: {
        "GET /api/books": "Search and filter books",
        "GET /api/search": "Dedicated search endpoint",
        "GET /api/books/<id>": "Get single book",
        "GET /api/health": "Health check",
        "GET /api/sources": "List data sources",
        "GET /api/stats": "Collection statistics",
      },
      note: "Cloudflare Worker runtime serves catalog endpoints from data/all_books.json.",
    });
  }

  const books = await loadBooks(request, env);

  if (path === "/api/health") {
    return json({
      success: true,
      status: "ok",
      books: books.length,
      sources: new Set(books.map((book) => book.source).filter(Boolean)).size,
    });
  }

  if (path === "/api/books" || path === "/api/search") {
    return json(paginate(filterBooks(books, url.searchParams), url.searchParams, path.slice(5)));
  }

  if (path === "/api/course-materials") {
    const filtered = filterBooks(books, url.searchParams, isCourseMaterial);
    return json(paginate(filtered, url.searchParams, "course-materials"));
  }

  if (path === "/api/textbooks") {
    const filtered = filterBooks(books, url.searchParams, isTextbook);
    return json(paginate(filtered, url.searchParams, "textbooks"));
  }

  if (path === "/api/teacher-guides") {
    const filtered = filterBooks(books, url.searchParams, isTeacherGuide);
    return json(paginate(filtered, url.searchParams, "teacher-guides"));
  }

  if (path === "/api/curriculum") {
    const filtered = filterBooks(books, url.searchParams, isCurriculum);
    return json(paginate(filtered, url.searchParams, "curriculum"));
  }

  if (path === "/api/ncert") {
    const filtered = filterBooks(books, url.searchParams, (book) => book.source === "ncert-official");
    return json(paginate(filtered, url.searchParams, "ncert"));
  }

  if (path.startsWith("/api/books/")) {
    const id = decodeURIComponent(path.slice("/api/books/".length));
    const book = books.find((item) => item.id === id);
    if (!book) return json({ success: false, error: "Book not found" }, 404);
    return json({ success: true, data: book });
  }

  if (path === "/api/sources") {
    const sources = new Map();
    for (const book of books) {
      const source = book.source || "unknown";
      if (!sources.has(source)) {
        sources.set(source, { source, count: 0, grades: new Set(), subjects: new Set() });
      }
      const entry = sources.get(source);
      entry.count += 1;
      if (book.grade) entry.grades.add(book.grade);
      if (book.subject) entry.subjects.add(book.subject);
    }
    const data = [...sources.values()].map((entry) => ({
      source: entry.source,
      count: entry.count,
      grades: [...entry.grades].sort((a, b) => Number(a) - Number(b)),
      subjects: [...entry.subjects].sort(),
    }));
    return json({ success: true, data });
  }

  if (path === "/api/stats") {
    const countBy = (key) => {
      const result = {};
      for (const book of books) {
        const value = textValue(book[key]) || "unknown";
        result[value] = (result[value] || 0) + 1;
      }
      return result;
    };
    return json({
      success: true,
      data: {
        totalBooks: books.length,
        byGrade: countBy("grade"),
        bySubject: countBy("subject"),
        bySource: countBy("source"),
        byLanguage: countBy("language"),
      },
    });
  }

  return json({ success: false, error: "Endpoint is not available on Cloudflare Worker runtime" }, 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/about") {
      url.pathname = "/about.html";
      return env.ASSETS.fetch(new Request(url, request));
    }
    if (url.pathname === "/favicon.ico") {
      url.pathname = "/assets/yobook-logo.svg";
      const response = await env.ASSETS.fetch(new Request(url, request));
      return new Response(response.body, {
        status: response.status,
        headers: {
          "content-type": "image/svg+xml",
          "cache-control": "public, max-age=31536000, immutable",
        },
      });
    }
    if (url.pathname === "/docs" || url.pathname === "/docs/") {
      return html(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>YoBook API Docs</title>
    <style>
      body { font-family: system-ui, sans-serif; max-width: 760px; margin: 48px auto; padding: 0 20px; line-height: 1.6; }
      code, a { color: #0f766e; }
    </style>
  </head>
  <body>
    <h1>YoBook API Docs</h1>
    <p>Cloudflare Worker runtime is serving the catalog API from <code>data/all_books.json</code>.</p>
    <p><a href="/openapi.json">Open OpenAPI JSON</a></p>
  </body>
</html>`);
    }
    if (url.pathname.startsWith("/api")) {
      try {
        return await handleApi(request, env);
      } catch (error) {
        return json({ success: false, error: error.message || "Worker error" }, 500);
      }
    }
    return env.ASSETS.fetch(request);
  },
};
