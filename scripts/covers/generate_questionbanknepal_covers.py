"""
Generate deterministic local SVG covers for Question Bank Nepal exam groups.

This updates the grouped question-paper catalog with coverUrl values and removes
legacy per-paper ``paper_part`` values if they are present.
"""

import html
import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "data" / "Course Materials" / "questionbanknepal_question_papers.json"
COVER_DIR = ROOT / "data" / "covers" / "questionbanknepal"

PALETTES = {
    "Lok Sewa Preparation": ("#0f766e", "#f59e0b", "#f8fafc"),
    "Bank Exam Preparation": ("#1d4ed8", "#16a34a", "#f8fafc"),
    "College Exam Preparation": ("#7c3aed", "#db2777", "#f8fafc"),
    "Corporation Job Exams": ("#334155", "#ea580c", "#f8fafc"),
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def wrap_words(text, width=20, max_lines=3):
    words = clean(text).split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        remaining = " ".join(words[sum(len(line.split()) for line in lines):])
        lines.append(remaining if len(remaining) <= width else remaining[: width - 1].rstrip() + "…")
    return lines or [text]


def cover_svg(record):
    exam = clean(record.get("exam_name") or record.get("title"))
    collection = clean(record.get("collection_name"))
    papers = len(record.get("question_papers", []))
    primary, accent, paper = PALETTES.get(collection, ("#0f172a", "#0ea5e9", "#f8fafc"))
    title_lines = wrap_words(exam, width=18, max_lines=3)
    line_svgs = []
    y = 188
    for line in title_lines:
        line_svgs.append(
            f'<text x="48" y="{y}" font-size="34" font-weight="800" fill="#ffffff">'
            f"{html.escape(line)}</text>"
        )
        y += 42

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="960" viewBox="0 0 640 960" role="img" aria-label="{html.escape(exam)} question paper cover">
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
  <path d="M0 735 C140 655 245 830 388 742 C502 671 566 690 640 640 L640 960 L0 960 Z" fill="{accent}" opacity="0.92"/>
  <rect x="64" y="448" width="410" height="310" rx="18" fill="url(#paper)" opacity="0.98"/>
  <rect x="104" y="506" width="280" height="15" rx="7" fill="#94a3b8"/>
  <rect x="104" y="552" width="324" height="15" rx="7" fill="#cbd5e1"/>
  <rect x="104" y="598" width="292" height="15" rx="7" fill="#cbd5e1"/>
  <rect x="104" y="644" width="250" height="15" rx="7" fill="#cbd5e1"/>
  <circle cx="491" cy="725" r="78" fill="#ffffff" opacity="0.96"/>
  <text x="491" y="714" text-anchor="middle" font-size="42" font-weight="800" fill="{primary}">{papers}</text>
  <text x="491" y="750" text-anchor="middle" font-size="18" font-weight="700" fill="#475569">PAPERS</text>
  <text x="48" y="82" font-size="19" font-weight="800" fill="{accent}" letter-spacing="1">QUESTION BANK NEPAL</text>
  <text x="48" y="126" font-size="22" font-weight="700" fill="#e5e7eb">{html.escape(collection)}</text>
  {''.join(line_svgs)}
  <text x="48" y="854" font-size="21" font-weight="700" fill="#ffffff">Exam Question Papers</text>
  <text x="48" y="890" font-size="17" font-weight="600" fill="#e5e7eb">Grouped by exam name</text>
</svg>
"""


def main():
    with CATALOG_PATH.open("r", encoding="utf-8") as file:
        records = json.load(file)

    COVER_DIR.mkdir(parents=True, exist_ok=True)
    for record in records:
        record_id = record.get("id")
        if not record_id:
            continue

        filename = f"{record_id}.svg"
        cover_path = COVER_DIR / filename
        cover_path.write_text(cover_svg(record), encoding="utf-8")
        record["coverUrl"] = f"/covers/questionbanknepal/{filename}"

        for paper in record.get("question_papers", []):
            paper.pop("paper_part", None)

    with CATALOG_PATH.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"Updated {len(records)} records")
    print(f"Wrote covers to {COVER_DIR}")


if __name__ == "__main__":
    main()
