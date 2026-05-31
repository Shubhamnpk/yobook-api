"""
Group Shisir Library question-paper records by similar exam names.

Input:
  data/Course Materials/shisir_question_papers.json

Output:
  data/Course Materials/shisir_question_papers_grouped.json
"""

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INPUT_PATH = os.path.join(ROOT, "data", "Course Materials", "shisir_question_papers.json")
OUTPUT_PATH = os.path.join(ROOT, "data", "Course Materials", "shisir_question_papers_grouped.json")

NEPALI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
YEAR_RE = re.compile(r"\b(20[0-9]{2}|20[5-8][0-9]|20882)\b")

CATEGORY_ALIASES = {
    "Aayog": None,
    "Aurveda": "Ayurveda",
    "HA": "Health Assistant (HA)",
    "Health Assistant": "Health Assistant (HA)",
    "HA License": "Health Assistant (HA)",
    "KAHS Jumla": "Health Assistant (HA)",
    "Various Local Level": "Health Assistant (HA)",
    "प्रा.अम. मेडिकल (CMA/HA)": "Health Assistant (HA)",
    "ANM": "ANM",
    "AHW": "AHW",
    "Lab Assistant": "Laboratory",
    "Laboratory": "Laboratory",
    "Pharmacy": "Pharmacy",
    "Pharmacy Assistant": "Pharmacy",
    "Pharmacy Officer": "Pharmacy",
    "Radiographer": "Radiography",
    "Staff Nurse": "Staff Nurse",
    "Staff Nurse (General Nursing)": "Staff Nurse",
    "Staff Nurse/PHN": "Staff Nurse / PHN",
    "Public Health Nurse (PHN)": "PHN",
    "Public Health Nursing (PHN)": "PHN",
    "Nursing Officer": "Nursing Officer",
    "School Health Nurse (SHN)": "School Health Nurse (SHN)",
    "प्रा.सु. सैनिक उपचारिका (Staff Nurse)": "Staff Nurse",
    "प्रा.अम.डेण्टल (Dental)": "Dental",
    "Dentistry": "Dental",
    "Opthalmic Assistant": "Ophthalmic Assistant",
    "Third Year": "CTEVT Third Year",
    "Chapter-wise MCQs": "Health MCQs",
    "Model Questions": "Health MCQs",
    "Subjective Question Paper": "Health MCQs",
    "Health Science Entrance Exam (Question Bank)": "Health Science Entrance Exam",
    "Nepal Army (Military)": "Nepal Army",
    "Nepal Police": "Nepal Police",
    "Armed Police Inspector": "Armed Police Force",
    "Patan Hospital": "Patan Hospital",
    "Civil Hospital": "Civil Hospital",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "shisir-question-papers"


def stable_id(exam_name):
    digest = hashlib.sha1(exam_name.encode("utf-8")).hexdigest()[:10]
    return f"slg-{slugify(exam_name)}-{digest}"


def english_year(value):
    text = clean(value).translate(NEPALI_DIGITS)
    match = YEAR_RE.search(text)
    return match.group(1) if match else None


def infer_aayog_exam(title, keywords):
    text = f"{title} {' '.join(keywords)}".lower()
    if "nursing" in text or "staff nurse" in text:
        return "Staff Nurse"
    if "ha " in text or "health assistant" in text or "health instructor" in text:
        return "Health Assistant (HA)"
    return "Aayog"


def exam_name_for(item):
    category = clean(item.get("libraryCategory"))
    title = clean(item.get("title"))
    keywords = [clean(keyword) for keyword in item.get("keywords", [])]
    alias = CATEGORY_ALIASES.get(category, category)
    if alias:
        return alias
    return infer_aayog_exam(title, keywords)


def collection_name_for(item):
    keywords = " ".join(clean(keyword) for keyword in item.get("keywords", [])).lower()
    category = clean(item.get("libraryCategory")).lower()
    title = clean(item.get("title")).lower()
    text = f"{keywords} {category} {title}"
    if "license" in text:
        return "Health License Exams"
    if "entrance" in text:
        return "Health Entrance Exams"
    if "nepal army" in text or "military" in text:
        return "Nepal Army Exams"
    if "nepal police" in text:
        return "Nepal Police Exams"
    if "armed police" in text or "apf" in text:
        return "Armed Police Force Exams"
    if "hospital" in text or "pahs" in text:
        return "Hospital Exams"
    if "loksewa" in text or "लोक सेवा" in text or "aayog" in text or "आयोग" in text:
        return "Health Loksewa"
    return "Health Question Papers"


def paper_record(item):
    return {
        "title": clean(item.get("title")),
        "year": english_year(item.get("publishedYear")) or english_year(item.get("title")),
        "readUrl": item.get("readUrl") or item.get("downloadUrl"),
        "sourceUrl": item.get("sourceUrl"),
        "coverUrl": item.get("coverUrl"),
        "fileSize": item.get("fileSize"),
    }


def main():
    with open(INPUT_PATH, "r", encoding="utf-8") as file:
        items = json.load(file)

    groups = defaultdict(list)
    collections = defaultdict(set)
    for item in items:
        exam_name = exam_name_for(item)
        groups[exam_name].append(item)
        collections[exam_name].add(collection_name_for(item))

    scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    output = []
    for exam_name in sorted(groups):
        papers = sorted(
            (paper_record(item) for item in groups[exam_name]),
            key=lambda paper: (paper.get("year") or "", paper["title"].lower()),
            reverse=True,
        )
        source_pages = sorted(
            {item.get("sourceUrl") for item in groups[exam_name] if item.get("sourceUrl")}
        )
        collection_names = sorted(collections[exam_name])
        collection_name = collection_names[0] if len(collection_names) == 1 else " / ".join(collection_names)
        record_id = stable_id(exam_name)
        output.append(
            {
                "id": record_id,
                "title": exam_name,
                "collection_name": collection_name,
                "author": "Shisir Library",
                "language": "en",
                "country": "np",
                "source": "shisir-library-grouped",
                "sourceUrl": source_pages[0] if source_pages else "",
                "coverUrl": f"/covers/shisir-question-papers/{record_id}.svg",
                "category": "Question Papers",
                "keywords": [
                    "Shisir Library",
                    exam_name,
                    collection_name,
                    "Question Papers",
                ],
                "scrapedAt": scraped_at,
                "description": f"{exam_name} question papers grouped from Shisir Library.",
                "question_papers": papers,
            }
        )

    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"Wrote {len(output)} groups from {len(items)} papers")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
