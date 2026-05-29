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


def test_gradewise_audio_endpoint_returns_nested_data():
    client = app.test_client()
    response = client.get("/api/gradewise-audio?grade=4&subject=English")

    assert response.status_code == 200
    assert response.json["success"] is True
    data = response.json["data"]
    assert data["stats"]["audioLinks"] > 0
    assert [grade["grade"] for grade in data["grades"]] == [4]
    assert data["grades"][0]["subjects"][0]["subject"] == "English"
    chapter = data["grades"][0]["subjects"][0]["chapters"][0]
    assert set(chapter) == {"chapter", "chapterName", "unit", "url"}


def test_gradewise_audio_url_is_allowed_by_audio_proxy(monkeypatch):
    client = app.test_client()
    catalog_response = client.get("/api/gradewise-audio?grade=4&subject=English")
    audio_url = catalog_response.json["data"]["grades"][0]["subjects"][0]["chapters"][0]["url"]

    class DummyResponse:
        status_code = 200
        headers = {"Content-Type": "audio/mpeg", "Content-Length": "4"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=65536):
            yield b"test"

    monkeypatch.setattr("api.requests.get", lambda *args, **kwargs: DummyResponse())
    response = client.get(f"/api/audio?url={audio_url}")

    assert response.status_code == 200
    assert response.data == b"test"
