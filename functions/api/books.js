import { filterBooks, json, loadBooks, paginate } from "../_lib/catalog.js";

export async function onRequestGet({ env, request }) {
  try {
    const url = new URL(request.url);
    const books = await loadBooks(env, request);
    const filtered = filterBooks(books, url.searchParams);
    const page = paginate(filtered, url.searchParams);

    return json({
      success: true,
      data: page.data,
      meta: page.meta,
    });
  } catch (error) {
    return json({ success: false, error: error.message }, { status: 500 });
  }
}
