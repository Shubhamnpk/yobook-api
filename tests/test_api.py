from api import app


def test_health_and_stats_are_available():
    client = app.test_client()

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json["success"] is True

    stats = client.get("/api/stats")
    assert stats.status_code == 200
    assert stats.json["success"] is True
    assert "totalBooks" in stats.json["data"]


def test_invalid_pagination_returns_400_json():
    client = app.test_client()
    response = client.get("/api/books?page=abc")

    assert response.status_code == 400
    assert response.json["success"] is False
    assert "page" in response.json["error"]


def test_book_not_found_is_consistent_error():
    client = app.test_client()
    response = client.get("/api/books/not-a-real-book-id")

    assert response.status_code == 404
    assert response.json == {"success": False, "error": "Book not found"}


def test_disallowed_proxy_host_is_rejected():
    client = app.test_client()
    response = client.get("/api/pdf?url=https://example.com/book.pdf")

    assert response.status_code == 403
    assert response.json["success"] is False
