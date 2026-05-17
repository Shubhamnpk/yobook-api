import { asText, json, loadBooks } from "../_lib/catalog.js";

function increment(counter, key) {
  const safeKey = asText(key) || "unknown";
  counter[safeKey] = (counter[safeKey] || 0) + 1;
}

export async function onRequestGet({ env, request }) {
  try {
    const books = await loadBooks(env, request);
    const byGrade = {};
    const bySubject = {};
    const bySource = {};
    const byLanguage = {};

    for (const book of books) {
      if (book.grade) {
        increment(byGrade, book.grade);
      }
      increment(bySubject, book.subject);
      increment(bySource, book.source);
      increment(byLanguage, book.language);
    }

    return json({
      success: true,
      data: {
        totalBooks: books.length,
        byGrade: Object.fromEntries(Object.entries(byGrade).sort(([a], [b]) => Number(a) - Number(b))),
        bySubject: Object.fromEntries(Object.entries(bySubject).sort()),
        bySource,
        byLanguage,
      },
    });
  } catch (error) {
    return json({ success: false, error: error.message }, { status: 500 });
  }
}
