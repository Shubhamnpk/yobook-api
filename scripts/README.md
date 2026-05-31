# Scripts

Helper scripts are grouped by workflow:

- `scrapers/` - source scrapers and catalog merge helpers
- `covers/` - cover image and thumbnail generation/sync helpers
- `uploads/` - optional upload helpers for generated image assets
- `validation/` - catalog validation scripts

Run scripts from the repository root so relative data paths stay consistent.

Question-paper collection helpers:

```bash
python scripts/scrapers/scrape_questionbanknepal_question_papers.py
python scripts/covers/generate_questionbanknepal_covers.py
python scripts/scrapers/group_shisir_question_papers.py
python scripts/covers/generate_shisir_grouped_question_paper_covers.py
```

Grouped question-paper records are collection records. Their top-level `coverUrl`
is a local SVG collection cover, and individual paper files live under
`question_papers[].readUrl` or `question_papers[].url`.
