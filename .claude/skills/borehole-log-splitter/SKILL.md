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

The behavior of page classification is governed by the following variables inside the script:
1. **`HOLE_PATTERNS`**: Regular expressions used to detect borehole labels. Uses word boundaries (`\bHOLE\s+NO\b`) to prevent false-positives on plural labels like `HOLE NOS.`.
2. **`TRASH_KEYWORDS`**: List of keywords (e.g., `CORE PHOTOGRAPH`, `INDEX`, `COVER`, `PHOTO LOG`) evaluated with word boundaries (`\b`) to avoid false-positives such as matching `RECOVERY` with the word `COVER`.

## Sequence-Based Borehole Name Verification
To handle OCR digit/letter confusion (e.g., misreading `DH5` as `DH55`, `DH38` as `DH3B`, `DH51` as `DHS1`), the splitter applies a strictly ascending sequence check:
1. **Dominant Prefix Detection**: Identifies the primary borehole prefix (e.g., `DH`) for the report.
2. **Subsequence Isolation**: Extracts all blocks that match the dominant sequence and parses their numbers using OCR mappings.
3. **Longest Increasing Subsequence (LIS)**: Computes the LIS to identify guaranteed-correct "anchor" blocks.
4. **Neighbor Interpolation**: Uses neighboring left and right anchors to mathematically interpolate or extrapolate missing or misread names in the sequence (e.g., if index is between `DH12` and `DH14`, the name is forced to `DH13` regardless of the OCR output). Non-conforming or non-dominant prefix logs (like cover sheets or specific site-specific names) are preserved without sequence correction.
5. **Generalized Prefix & Letter Sequences**: Supports sequences with prefix letters (e.g. `a1, a2, a3`, `b1, b2, b3`) and suffix letters (e.g. `a1a, c2a, c3a`) by grouping by prefix and mapping suffix letters to numerical values for sequence sorting and interpolation.

## Cover-Page Borehole List Double-Tracking
As a primary source of truth, the second page (or cover page) text is scanned for bracketed borehole lists (e.g., `(HOLE NOS. DHS5-DHS1, DH53-DH60, B5, B6 & C5)`):
1. **Extraction & Expansion**: The list is extracted and expanded (including range bounds like letter ranges `B2a-B2c` or numeric ranges `DH53-DH60`) into a list of expected boreholes.
2. **Lexicographical Sorting**: The list is sorted lexicographically by prefix and numeric value to match the physical page order in the report.
3. **Dynamic Programming Alignment**: The sequence of split page blocks is aligned with the expected sorted cover page list using a Needleman-Wunsch-based dynamic programming alignment. This corrects page block names to match the expected names while maintaining strictly ascending page order.
4. **Fallback**: If no cover-page list is detected, the splitter falls back to purely sequence-based LIS smoothing.
