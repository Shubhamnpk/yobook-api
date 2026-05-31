"""
Generate deterministic local SVG covers for grouped Shisir question-paper records.

The script also normalizes the grouped collection shape:
- no duplicate ``exam_name`` field
- no top-level ``readUrl``
- each paper keeps its own ``readUrl``
"""

import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "data" / "Course Materials" / "shisir_question_papers_grouped.json"
COVER_DIR = ROOT / "data" / "covers" / "shisir-question-papers"

PALETTES = {
    "Health Loksewa": ("#0f766e", "#22c55e", "#f8fafc"),
    "Health License Exams": ("#1d4ed8", "#06b6d4", "#f8fafc"),
    "Health Entrance Exams": ("#7c3aed", "#ec4899", "#f8fafc"),
    "Hospital Exams": ("#be123c", "#f97316", "#fff7ed"),
    "Nepal Army Exams": ("#365314", "#84cc16", "#f7fee7"),
    "Nepal Police Exams": ("#1e3a8a", "#38bdf8", "#eff6ff"),
    "Armed Police Force Exams": ("#334155", "#f59e0b", "#f8fafc"),
    "Health Question Papers": ("#0f172a", "#14b8a6", "#f8fafc"),
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def first_collection(collection_name):
    return clean(collection_name).split(" / ")[0]


def wrap_words(text, width=18, max_lines=3):
    words = clean(text).split()
    lines = []
    current = ""
    index = 0
    while index < len(words) and len(lines) < max_lines:
        word = words[index]
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            index += 1
            continue
        if current:
            lines.append(current)
            current = ""
            continue
        lines.append(word[: width - 1] + "…")
        index += 1

    if current and len(lines) < max_lines:
        lines.append(current)
    if index < len(words) and lines:
        lines[-1] = lines[-1].rstrip("…")[: width - 1].rstrip() + "…"
    return lines or [text]


def cover_svg(record):
    title = clean(record.get("title"))
    collection = clean(record.get("collection_name"))
    papers = len(record.get("question_papers", []))
    primary, accent, paper = PALETTES.get(first_collection(collection), PALETTES["Health Question Papers"])
    title_lines = wrap_words(title)
    y = 192
    line_markup = []
    for line in title_lines:
        line_markup.append(
            f'<text x="48" y="{y}" font-size="36" font-weight="800" fill="#ffffff">'
            f"{html.escape(line)}</text>"
        )
        y += 44

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="960" viewBox="0 0 640 960" role="img" aria-label="{html.escape(title)} question paper cover">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{primary}"/>
      <stop offset="1" stop-color="#111827"/>
    </linearGradient>
    <linearGradient id="paper" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{paper}"/>
      <stop offset="1" stop-color="#dbeafe"/>
    </linearGradient>
  </defs>
  <rect width="640" height="960" fill="url(#bg)"/>
  <rect x="66" y="444" width="395" height="312" rx="18" fill="url(#paper)"/>
  <rect x="104" y="506" width="276" height="14" rx="7" fill="#94a3b8"/>
  <rect x="104" y="552" width="318" height="14" rx="7" fill="#cbd5e1"/>
  <rect x="104" y="598" width="288" height="14" rx="7" fill="#cbd5e1"/>
  <rect x="104" y="644" width="238" height="14" rx="7" fill="#cbd5e1"/>
  <path d="M0 728 C128 650 238 826 382 740 C500 668 560 688 640 632 L640 960 L0 960 Z" fill="{accent}" opacity="0.92"/>
  <circle cx="492" cy="724" r="78" fill="#ffffff" opacity="0.96"/>
  <text x="492" y="714" text-anchor="middle" font-size="42" font-weight="800" fill="{primary}">{papers}</text>
  <text x="492" y="750" text-anchor="middle" font-size="18" font-weight="700" fill="#475569">PAPERS</text>
  <text x="48" y="82" font-size="19" font-weight="800" fill="{accent}">SHISIR LIBRARY</text>
  <text x="48" y="126" font-size="22" font-weight="700" fill="#e5e7eb">{html.escape(first_collection(collection))}</text>
  {''.join(line_markup)}
  <text x="48" y="854" font-size="21" font-weight="700" fill="#ffffff">Grouped Question Papers</text>
  <text x="48" y="890" font-size="17" font-weight="600" fill="#e5e7eb">Health exam collection</text>
</svg>
"""


def normalize_paper(paper):
    read_url = paper.get("readUrl") or paper.get("url") or paper.get("downloadUrl")
    normalized = {
        "title": paper.get("title"),
        "year": paper.get("year"),
        "readUrl": read_url,
    }
    if paper.get("sourceUrl") or paper.get("source_page_url"):
        normalized["sourceUrl"] = paper.get("sourceUrl") or paper.get("source_page_url")
    if paper.get("coverUrl"):
        normalized["coverUrl"] = paper.get("coverUrl")
    if paper.get("fileSize"):
        normalized["fileSize"] = paper.get("fileSize")
    return normalized


def main():
    with CATALOG_PATH.open("r", encoding="utf-8") as file:
        records = json.load(file)

    COVER_DIR.mkdir(parents=True, exist_ok=True)
    for record in records:
        record_id = record.get("id")
        if not record_id:
            continue
        record.pop("exam_name", None)
        record.pop("readUrl", None)
        record["question_papers"] = [
            normalize_paper(paper)
            for paper in record.get("question_papers", [])
        ]

        filename = f"{record_id}.svg"
        (COVER_DIR / filename).write_text(cover_svg(record), encoding="utf-8")
        record["coverUrl"] = f"/covers/shisir-question-papers/{filename}"

    with CATALOG_PATH.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"Updated {len(records)} records")
    print(f"Wrote covers to {COVER_DIR}")


if __name__ == "__main__":
    main()
