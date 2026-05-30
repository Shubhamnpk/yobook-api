"""Scrape audio links from the E-Pustakalaya grade-wise API.

Usage:
  python scripts/scrapers/scrape_gradewise_audio_links.py
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILE = ROOT / "data" / "gradewise_audio_links.json"

BASE_URL = "https://pustakalaya.org"
GRADEWISE_URL = "https://gradewise.pustakalaya.org"
API_TOKEN = "544a934849123310b953fa95828d8c812d9e9d19"
REQUEST_DELAY_SECONDS = 0.02

HEADERS = {
    "Authorization": f"Token {API_TOKEN}",
    "Accept": "application/json",
    "User-Agent": "YoBookAPI-Scraper/1.0 (Educational Research; Grade-wise Audio Links)",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def api_url(path: str) -> str:
    return f"{BASE_URL}{path}"


def absolute_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        return f"{BASE_URL}{url}"
    return f"{BASE_URL}/{url}"


def split_name(value: str | None) -> dict[str, str | None]:
    if not value:
        return {"raw": value, "english": value, "nepali": None}
    if "[[" in value and value.endswith("]]"):
        english, nepali = value.split("[[", 1)
        return {
            "raw": value,
            "english": english.strip(),
            "nepali": nepali[:-2].strip(),
        }
    return {"raw": value, "english": value, "nepali": None}


def display_name(value: str | None) -> str | None:
    name = split_name(value)
    return name["english"] or name["nepali"] or name["raw"]


def quoted_slug(slug: str) -> str:
    return quote(str(slug), safe="")


def get_json(session: requests.Session, path: str) -> dict[str, Any]:
    response = session.get(api_url(path), timeout=30)
    response.raise_for_status()
    return response.json()


def iter_audio_uploads(item: dict[str, Any]) -> list[dict[str, Any]]:
    uploads: list[dict[str, Any]] = []

    if item.get("type") == "audio" and item.get("link"):
        uploads.append(item)

    for key in ("file_upload", "embed_link", "link_info"):
        value = item.get(key)
        if not isinstance(value, list):
            continue
        for upload in value:
            if isinstance(upload, dict) and upload.get("type") == "audio" and upload.get("link"):
                uploads.append(upload)

    return uploads


def nest_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grades: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for record in records:
        grade_number = record["grade"]
        subject_name = record["subject"]

        grade = grades.setdefault(
            str(grade_number),
            {"grade": grade_number, "subjects": OrderedDict()},
        )
        subject = grade["subjects"].setdefault(
            subject_name,
            {"subject": subject_name, "chapters": []},
        )
        subject["chapters"].append(
            {
                "chapter": record["chapter"],
                "chapterName": record["chapterTitle"],
                "unit": record["audioTitle"],
                "url": record["audioUrl"],
            }
        )

    nested_grades = []
    for grade in grades.values():
        grade["subjects"] = list(grade["subjects"].values())
        nested_grades.append(grade)

    return nested_grades


def scrape() -> dict[str, Any]:
    session = requests.Session()
    session.headers.update(HEADERS)
    scraped_at = utc_now()

    grades_payload = get_json(session, "/api/v1/grade/list/")
    records: list[dict[str, Any]] = []
    stats = {
        "gradesScanned": 0,
        "subjectsScanned": 0,
        "chaptersScanned": 0,
        "gradesWithAudio": 0,
        "subjectsWithAudio": 0,
        "chaptersWithAudio": 0,
        "audioLinksFound": 0,
    }

    seen: set[tuple[str, str, str, str]] = set()
    grades_with_audio: dict[str, dict[str, Any]] = {}
    subjects_with_audio: set[tuple[str, str]] = set()

    for grade in grades_payload.get("grades", []):
        stats["gradesScanned"] += 1
        grade_slug = grade["slug"]
        print(f"Grade {grade_slug}: loading subjects")
        subjects_payload = get_json(session, f"/api/v1/grade/{quoted_slug(grade_slug)}/subject/list/")
        time.sleep(REQUEST_DELAY_SECONDS)

        for subject in subjects_payload.get("subjects", []):
            stats["subjectsScanned"] += 1
            subject_slug = subject["slug"]
            print(f"  Subject {subject_slug}: loading chapters")
            chapters_payload = get_json(
                session,
                f"/api/v1/grade/{quoted_slug(grade_slug)}/subject/{quoted_slug(subject_slug)}/chapter/list/",
            )
            time.sleep(REQUEST_DELAY_SECONDS)

            for chapter in chapters_payload.get("chapters", []):
                stats["chaptersScanned"] += 1
                chapter_slug = chapter["slug"]
                chapter_path = (
                    f"/api/v1/grade/{quoted_slug(grade_slug)}/subject/{quoted_slug(subject_slug)}"
                    f"/chapter/{quoted_slug(chapter_slug)}/"
                )
                chapter_payload = get_json(session, chapter_path)
                time.sleep(REQUEST_DELAY_SECONDS)

                chapter_audio_count = 0
                for item in chapter_payload.get("items", []):
                    for upload in iter_audio_uploads(item):
                        audio_url = absolute_url(upload.get("link"))
                        if not audio_url:
                            continue
                        dedupe_key = (grade_slug, subject_slug, chapter_slug, audio_url)
                        if dedupe_key in seen:
                            continue
                        seen.add(dedupe_key)
                        chapter_audio_count += 1

                        records.append(
                            {
                                "grade": grade.get("name_en_number"),
                                "subject": display_name(subject.get("name")),
                                "chapter": chapter.get("number_en"),
                                "chapterTitle": display_name(chapter.get("name")),
                                "audioTitle": upload.get("name") or item.get("title"),
                                "audioUrl": audio_url,
                            }
                        )

                if chapter_audio_count:
                    stats["chaptersWithAudio"] += 1
                    stats["audioLinksFound"] += chapter_audio_count
                    grades_with_audio[grade_slug] = {
                        "number": grade.get("name_en_number"),
                    }
                    subjects_with_audio.add((grade_slug, subject_slug))

    stats["gradesWithAudio"] = len(grades_with_audio)
    stats["subjectsWithAudio"] = len(subjects_with_audio)

    return {
        "source": GRADEWISE_URL,
        "scrapedAt": scraped_at,
        "stats": {
            "grades": stats["gradesWithAudio"],
            "subjects": stats["subjectsWithAudio"],
            "chapters": stats["chaptersWithAudio"],
            "audioLinks": stats["audioLinksFound"],
        },
        "grades": nest_records(records),
    }


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = scrape()
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Wrote grade-wise audio data to {OUTPUT_FILE}")
    print(json.dumps(data["stats"], indent=2))


if __name__ == "__main__":
    main()
