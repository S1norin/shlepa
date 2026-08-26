---
name: pdf-reading
description: Extract text from PDFs in research/papers/ using LiteParse (run-llama/liteparse) via uvx. Use when the user asks to read/summarize/extract a PDF, when researching a paper referenced in research/papers/ or research/notes/, or when a note needs exact page citations. Falls back to pypdf if LiteParse is unavailable.
---

# PDF reading (LiteParse)

Extract text from research PDFs with **LiteParse**
(`run-llama/LiteParse`), a local Rust-based parser (PDFium + optional
Tesseract OCR). No cloud, no API keys.

## Invocation (verified 2026-08-26 on this machine)

The PyPI package is `liteparse`; its CLI binary is **`lit`** (NOT
`liteparse`). Run it through uvx:

```bash
# Text PDFs (papers) — fast, no OCR
uvx --from liteparse lit parse research/papers/<file>.pdf --format markdown

# Save to file
uvx --from liteparse lit parse <file>.pdf --format markdown -o /tmp/<name>.md

# Specific pages
uvx --from liteparse lit parse <file>.pdf --format markdown --target-pages "1-5,10"

# Scanned / image-only PDFs — enable OCR (slow: Tesseract, ~17s/page measured)
uvx --from liteparse lit parse <file>.pdf --format markdown --ocr
```

Notes:
- Plain `uvx liteparse` fails ("An executable named `liteparse` is not
  provided") — always use `uvx --from liteparse lit ...`.
- First run downloads the package (~13MB wheel) into the uvx cache;
  subsequent runs are instant.
- Text PDFs: `--no-ocr` is the default and extraction is ~2.5s/page.
  OCR by default still scans for image text; pass `--no-ocr` explicitly
  when a PDF is known to be digital to avoid wasted OCR passes.
- JSON output (bbox, blocks) for layout work:
  `--format json --extract-blocks`.
- Remote PDF: `curl -sL <url> | uvx --from liteparse lit parse -`.

## Fallback (if uvx/LiteParse unavailable)

```bash
uv run --no-project --with pypdf python -c "
import sys
from pypdf import PdfReader
r = PdfReader(sys.argv[1])
print('\f'.join((p.extract_text() or '') for p in r.pages))
" <file>.pdf
```

pypdf is much weaker on multi-column layouts and tables; use it only
when LiteParse cannot run (no network for the first download, broken
wheel).

## Workflow for research papers

1. Store the PDF in `research/papers/` named
   `<year>-<firstauthor>-<short-slug>.pdf` (keep the original name in
   a note if it differs).
2. Extract (markdown format preserves headings/tables best).
3. Write/extend the note in `research/notes/` with:
   - the file name + paper URL,
   - 3–7 bullet takeaways,
   - **page citations** for every non-obvious claim, in the form
     `(<file>.pdf, p. N)` or a section+page reference,
   - a "## Actionable for Shlepa" section ONLY if the findings suggest
     concrete repo work (then offer to file issues via the `backlog`
     skill).
4. Notes are English; keep them append-only (new findings get new
   sections, dated).

## Verification checklist

- [ ] `uvx --from liteparse lit --version` (or `--help`) exits 0
- [ ] Extraction of a known digital PDF yields non-empty markdown with
  recognizable titles
- [ ] Any claim copied into a note carries a page citation
