import { asText, json, loadBooks, sourceRank } from "../_lib/catalog.js";

export async function onRequestGet({ env, request }) {
  try {
    const books = await loadBooks(env, request);
    const sources = new Map();

    for (const book of books) {
      const key = book.source || "unknown";
      if (!sources.has(key)) {
        sources.set(key, {
          source: key,
          count: 0,
          grades: new Set(),
          subjects: new Set(),
        });
      }

      const source = sources.get(key);
      source.count += 1;
      if (book.grade) {
        source.grades.add(book.grade);
      }
      if (book.subject) {
        source.subjects.add(asText(book.subject));
      }
    }

    const data = Array.from(sources.values())
      .map((source) => ({
        source: source.source,
        count: source.count,
        grades: Array.from(source.grades).sort((a, b) => a - b),
        subjects: Array.from(source.subjects).sort(),
      }))
      .sort((a, b) => sourceRank(a.source) - sourceRank(b.source));

    return json({ success: true, data });
  } catch (error) {
    return json({ success: false, error: error.message }, { status: 500 });
  }
}
