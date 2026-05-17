const SOURCE_PRIORITY = {
  "cehrd-learning": 0,
  "cdc-nepal": 1,
  "pustakalaya": 2,
  "archive-org": 3,
  openlibrary: 4,
};

function asText(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map(String).join(" ");
  }
  return String(value);
}

function sourceRank(bookOrSource) {
  const source = typeof bookOrSource === "string" ? bookOrSource : bookOrSource.source;
  return SOURCE_PRIORITY[source] ?? 99;
}

function normalizeCoverUrl(book) {
  if (typeof book.coverUrl === "string" && book.coverUrl.startsWith("/covers/")) {
    return { ...book, coverUrl: book.coverUrl.replace("/covers/", "/data/covers/") };
  }
  return book;
}

export async function loadBooks(env, request) {
  const dataUrl = new URL("/data/all_books.json", request.url);
  const response = await env.ASSETS.fetch(dataUrl);

  if (!response.ok) {
    throw new Error(`Unable to load catalog: ${response.status}`);
  }

  const books = await response.json();
  return books
    .map(normalizeCoverUrl)
    .sort((a, b) => {
      return (
        sourceRank(a) - sourceRank(b) ||
        (a.grade || 99) - (b.grade || 99) ||
        asText(a.subject).localeCompare(asText(b.subject)) ||
        asText(a.title).localeCompare(asText(b.title))
      );
    });
}

export function filterBooks(books, searchParams) {
  const q = (searchParams.get("q") || "").toLowerCase();
  const source = searchParams.get("source") || "";
  const grade = searchParams.get("grade") || "";
  const subject = (searchParams.get("subject") || "").toLowerCase();
  const language = searchParams.get("language") || "";
  const category = (searchParams.get("category") || "").toLowerCase();

  let result = books;

  if (q) {
    result = result.filter((book) => {
      return (
        asText(book.title).toLowerCase().includes(q) ||
        asText(book.subject).toLowerCase().includes(q) ||
        asText(book.description).toLowerCase().includes(q) ||
        asText(book.titleLocal).toLowerCase().includes(q) ||
        (book.keywords || []).some((keyword) => asText(keyword).toLowerCase().includes(q))
      );
    });
  }

  if (source) {
    result = result.filter((book) => book.source === source);
  }

  if (grade) {
    const gradeNumber = Number.parseInt(grade, 10);
    if (!Number.isNaN(gradeNumber)) {
      result = result.filter((book) => book.grade === gradeNumber);
    }
  }

  if (subject) {
    result = result.filter((book) => asText(book.subject).toLowerCase().includes(subject));
  }

  if (language) {
    result = result.filter((book) => book.language === language);
  }

  if (category) {
    result = result.filter((book) => asText(book.category).toLowerCase().includes(category));
  }

  return result;
}

export function paginate(books, searchParams) {
  const page = Math.max(1, Number.parseInt(searchParams.get("page") || "1", 10));
  const limit = Math.min(200, Math.max(1, Number.parseInt(searchParams.get("limit") || "50", 10)));
  const total = books.length;
  const start = (page - 1) * limit;
  const data = books.slice(start, start + limit);

  return {
    data,
    meta: {
      total,
      page,
      limit,
      pages: Math.ceil(total / limit),
    },
  };
}

export function json(data, init = {}) {
  return Response.json(data, {
    headers: {
      "Cache-Control": "public, max-age=300",
      ...(init.headers || {}),
    },
    ...init,
  });
}

export { asText, sourceRank };
