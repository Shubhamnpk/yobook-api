# 📚 BitLibrary Book API

Nepal educational book scraper & API. Scrapes books from 4 major sources, saves to JSON, and serves through a simple Flask API.

## Architecture

```
scraper.py  →  data/*.json  ←  api.py
  (Python)      (storage)      (Flask)
```

**It's that simple.** No TypeScript, no build step, no database.

## Sources

| Source | Type | Books | What it gets |
|---|---|---|---|
| **E-Pustakalaya** | HTML Scraping | ~200 | Nepal CDC textbooks, grade 1-12, Nepali & English |
| **CDC Nepal** | Static + Scraping | ~33 | Official govt textbook PDFs from moecdc.gov.np |
| **Internet Archive** | JSON API | ~107 | Digitized Nepal education books |
| **Open Library** | JSON API | ~81 | Supplementary catalog |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the scraper (scrapes all 4 sources)
python scraper.py

# Start the API
python api.py
# → http://localhost:5000
```

## Scraper Usage

```bash
# Scrape everything
python scraper.py

# Scrape specific source
python scraper.py --source pustakalaya
python scraper.py --source cdc
python scraper.py --source archive
python scraper.py --source openlibrary

# Scrape specific grade only
python scraper.py --source pustakalaya --grade 9

# Scrape any URL for PDFs/links
python scraper.py --source url --url https://example.com/books
```

## API Endpoints

### `GET /api/books` — Search & filter books
| Param | Description | Example |
|---|---|---|
| `q` | Search query | `?q=mathematics` |
| `grade` | Filter by grade (1-12) | `?grade=9` |
| `subject` | Filter by subject | `?subject=Science` |
| `source` | Filter by source | `?source=pustakalaya` |
| `language` | Filter by language | `?language=ne` |
| `category` | Filter by category | `?category=Textbook` |
| `page` | Page number | `?page=2` |
| `limit` | Results per page (max 200) | `?limit=20` |

### `GET /api/books/<id>` — Single book
### `GET /api/sources` — List all data sources with counts
### `GET /api/stats` — Collection statistics

## Data Format

Each book object:
```json
{
  "id": "pustakalaya-0b884ef4-c4c8-459e-87c8-a931e0b49a33",
  "title": "My Mathematics Grade 1",
  "titleLocal": "मेरो गणित - कक्षा १",
  "author": "CDC Nepal",
  "grade": 1,
  "subject": "Mathematics",
  "language": "en",
  "country": "np",
  "curriculum": "CDC Nepal",
  "source": "pustakalaya",
  "sourceUrl": "https://pustakalaya.org/documents/detail/...",
  "readUrl": "https://pustakalaya.org/documents/detail/...",
  "pdfUrl": "https://moecdc.gov.np/storage/gallery/...",
  "chapters": ["Numbers", "Addition", "Subtraction"],
  "keywords": ["math", "grade 1", "CDC"],
  "category": "Textbook"
}
```

## File Structure

```
book-api/
├── scraper.py          # All scrapers (run this first)
├── api.py              # Flask API server
├── requirements.txt    # Python deps
├── data/               # Auto-generated JSON files
│   ├── all_books.json      # Merged catalog (419 books)
│   ├── pustakalaya.json    # E-Pustakalaya results
│   ├── cdc_nepal.json      # CDC official textbooks
│   ├── archive_org.json    # Internet Archive results
│   └── open_library.json   # Open Library results
└── README.md
```
