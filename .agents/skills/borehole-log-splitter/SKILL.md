---
name: borehole-log-splitter
description: Project-specific skill to automate the splitting, classification, and OCR extraction of scanned multipage PDF borehole logs into separate PDF files.
---
# Borehole Log Splitter Skill (Project-Specific)

This project-specific skill allows the agent to process scanned, flat multipage PDFs of Ground Investigation (GI) borehole logs, classify pages, filter out irrelevant cover/index/photo pages, and group valid pages into separate PDFs named after their respective borehole numbers.

## Prerequisites

This skill requires the following tools to be installed on the system:
1. **Tesseract OCR Engine** (for text extraction via OCR)
2. **Python Libraries**: `pymupdf` (fitz), `pytesseract`, `pillow`.
*Note: Poppler is no longer required as PDF page rendering is performed natively using PyMuPDF.*

## Script Location
The utility script is stored in the project-specific skill folder at:
- `c:\Users\lawfe\VS Code Projects\Borehole Log Splitter\.agents\skills\borehole-log-splitter\scripts\borehole_splitter.py`

## CLI Usage

Run the script from the command line:

```powershell
python ".agents/skills/borehole-log-splitter/scripts/borehole_splitter.py" \
  --input "path/to/master.pdf" \
  --splits-dir "individual borehole logs" \
  --keep-splits \
  --tesseract-path "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

### Script Arguments

- `--input` / `-i`: Path to the scanned multipage input PDF. (Required)
- `--splits-dir`: Target folder where the split borehole PDFs will be stored. (Default: `temp_splits`)
- `--keep-splits`: Flag to retain the split PDFs.
- `--tesseract-path`: Path to `tesseract.exe` (defaults to standard `C:\Program Files\Tesseract-OCR\tesseract.exe`).
- `--dpi`: Rendering resolution DPI for OCR image conversion (default: `200`).
- `--gemini-key`: Google AI Studio API key (optional; if omitted, the script exits after generating the splits).
- `--extract-only`: Skip the page triage/splitting phase and extract stratigraphy directly from the input PDF.
- `--hole-name`: Hole name to use for direct extraction (useful when `--extract-only` is set).

## Customization & Heuristics

The behavior of page classification is governed by the following variables inside the script:
1. **`HOLE_PATTERNS`**: Regular expressions used to detect borehole labels. Uses word boundaries (`\bHOLE\s+NO\b`) to prevent false-positives on plural labels like `HOLE NOS.`.
2. **`TRASH_KEYWORDS`**: List of keywords (e.g., `CORE PHOTOGRAPH`, `INDEX`, `COVER`, `PHOTO LOG`) evaluated with word boundaries (`\b`) to avoid false-positives such as matching `RECOVERY` with the word `COVER`.
