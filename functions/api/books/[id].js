import { json, loadBooks } from "../../_lib/catalog.js";

export async function onRequestGet({ env, params, request }) {
  try {
    const books = await loadBooks(env, request);
    const book = books.find((item) => item.id === params.id);

    if (!book) {
      return json({ success: false, error: "Book not found" }, { status: 404 });
    }

    return json({ success: true, data: book });
  } catch (error) {
    return json({ success: false, error: error.message }, { status: 500 });
  }
}
