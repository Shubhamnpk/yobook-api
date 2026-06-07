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


def test_cehrd_books_support_short_detail_alias():
    client = app.test_client()

    alias_response = client.get("/api/books/cehrd-g1-mathematics")
    canonical_response = client.get("/api/books/cehrd-learning-g1-mathematics-40")

    assert alias_response.status_code == 200
    assert canonical_response.status_code == 200
    assert alias_response.json["data"]["id"] == "cehrd-learning-g1-mathematics-40"
    assert alias_response.json["data"] == canonical_response.json["data"]


def test_cehrd_list_uses_short_detail_url():
    client = app.test_client()

    response = client.get("/api/books?source=cehrd-learning&grade=1&subject=Mathematics&limit=1")

    assert response.status_code == 200
    assert response.json["data"][0]["id"] == "cehrd-learning-g1-mathematics-40"
    assert response.json["data"][0]["detailUrl"] == "/api/books/cehrd-g1-mathematics"


def test_pustakalaya_duplicate_of_cehrd_textbook_is_hidden_from_index():
    client = app.test_client()

    hidden = client.get("/api/books/pus-f93bc49a-3b04-4562-99cb-52473cc07017")
    official = client.get("/api/books/cehrd-g1-english")
    search = client.get("/api/books?source=pustakalaya-course&q=My%20English%20Grade%201&limit=200")

    assert hidden.status_code == 404
    assert official.status_code == 200
    assert official.json["data"]["id"] == "cehrd-learning-g1-english-42"
    assert all(
        item["id"] != "pus-f93bc49a-3b04-4562-99cb-52473cc07017"
        for item in search.json["data"]
    )


def test_pustakalaya_duplicate_of_cdc_teacher_guide_is_hidden_from_index():
    client = app.test_client()

    hidden = client.get("/api/books/pus-ffe92308-a34f-4091-a9dc-5aba3c9349c7")
    official = client.get("/api/books/cdc-library-teachers-guide-r3823")

    assert hidden.status_code == 404
    assert official.status_code == 200


def test_pustakalaya_cehrd_chapter_material_stays_visible():
    client = app.test_client()

    response = client.get("/api/books/pus-1a77a39a-6a45-4d0c-9360-b6b13ff38e4d")

    assert response.status_code == 200
    assert response.json["data"]["title"] == "Alphabet - My English Grade 1"


def test_tu_theses_have_dedicated_endpoint():
    client = app.test_client()

    response = client.get("/api/theses?limit=5")

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["meta"]["endpoint"] == "theses"
    if response.json["data"]:
        thesis = response.json["data"][0]
        assert thesis["source"] == "tu"
        assert thesis["category"] == "Thesis"
        assert thesis["detailUrl"].startswith("/api/research/")


def test_tu_research_endpoint_includes_reports_and_theses():
    client = app.test_client()

    response = client.get("/api/research?limit=200")

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["meta"]["endpoint"] == "research"
    categories = {item["category"] for item in response.json["data"]}
    assert "Report" in categories
    assert "Thesis" in categories


def test_tu_theses_are_not_in_normal_books():
    client = app.test_client()

    response = client.get("/api/books?source=tu&limit=5")

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["meta"]["total"] == 0


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
