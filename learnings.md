# Civil Engineering Learnings

This file logs theoretical/conceptual Q&A pairs, explanation summaries, and civil/software/data engineering concepts.

# 1. Software Engineering & PDF Processing

## 1.1 PDF Page Rendering to Image

### 1.1.1 What are the key differences between pdf2image and PyMuPDF (fitz) for PDF rendering in Python on Windows?
- **Definitional / Conceptual (TYPE 1):** pdf2image is a Python wrapper around the external command-line utility `pdftoppm` (part of the Poppler C/C++ library), whereas PyMuPDF (fitz) is a comprehensive set of Python bindings for MuPDF, a lightweight PDF rendering engine.
- **Key Characteristics:** pdf2image requires external binary compilation and path environment configuration on Windows, whereas PyMuPDF is fully compiled as a self-contained wheel installable directly via `pip`.
- **Usage Condition:** Prefer PyMuPDF when deploying to workstations without administrative privileges (avoiding complex installation of external tools) and when speed and ease of setup are critical. Prefer pdf2image if you need specific pdftoppm features.

# 11. Geotechnical

## 11.1 Ground Investigation Data Extraction

### 11.1.1 How do you automate the splitting and classification of multi-page scanned PDF borehole logs?

- **Workflow Overview**:
  - `Load Master PDF` > `Convert Page to Image (pdf2image)` > `Extract Text (Tesseract OCR)` > `Filter/Classify Page (Trash Keywords & Regex)` > `Accumulate Valid Page Indices` > `Slice & Save Grouped PDF (PyMuPDF)`
- **Key Implementation Parameters**:
  - Image conversion DPI set to `200` [alternative: higher DPI is more accurate but slower].
  - File name sanitization replaces characters like `\ / : * ? " < > |` with underscores (`_`) to avoid Windows filesystem path violations.
  - Page classification checks for trash keywords (`CORE PHOTOGRAPH`, `PHOTOGRAPHIC RECORD`, `INDEX`, `COVER`, `PHOTO LOG`, `PHOTOGRAPHS`, `KEY TO SHEET`) and uses regex `r"HOLE\s*NO\.?\s*([A-Za-z0-9\-]+)"` (case-insensitive) to anchor pages.
  - Memory leaks are avoided by processing page-by-page (using `first_page=page_num, last_page=page_num` in `pdf2image.convert_from_path`) rather than rendering the entire document at once, closing PIL image handles immediately, and triggering garbage collection (`gc.collect()`).

Example: Borehole Log Splitter [Project: e453e88d-dd70-4dd4-8e96-8e564594c9d0]
Situation:
  - Scanned, flat multipage PDFs containing mixed ground investigation logs (borehole records, core photos, cover pages, indices) needed to be split into separate documents per borehole while filtering out administrative trash pages.
Action:
  - Developed `borehole_splitter.py` utilizing `pdf2image` to render pages individually (reducing RAM load) at 200 DPI.
  - Applied pytesseract OCR and searched for borehole anchors using regex `r"HOLE\s*NO\.?\s*([A-Za-z0-9\-]+)"` and filtered out irrelevant pages containing keywords like "CORE PHOTOGRAPHS" or "INDEX".
  - Utilized PyMuPDF (`fitz`) to slice page groups and write them to `Borehole_[Hole_No].pdf` (with append support for non-contiguous pages).
Result:
  - Successfully automated the pipeline to process large scanned PDFs, outputting sanitized, grouped borehole records with zero manual intervention.

## 11.2 Sequence Verification & Alignment Process

### 11.2.1 How do you verify and correct OCR-read borehole names against the cover-page expected list?

- **Workflow Overview**:
  - `Extract Expected List`: Search cover page text (Page 2 / Page 1) for the bracketed list of expected boreholes (e.g. `(HOLE NOS. ...)`). Expand ranges (e.g., `B2a-B2c` -> `B2A, B2B, B2C`).
  - `Compute Prefix Priority`: Extract prefixes from raw page block votes and establish their relative sequence (e.g., pile `P` series first, then `B` series). Sort the expected cover list using this prefix priority to match the physical page order.
  - `Sequence Alignment via Dynamic Programming`: Align raw voted block names (including `None` for missing names) with the sorted expected list using a skip-capable Needleman-Wunsch DP alignment.
  - `Save & Output`: Correct OCR errors using aligned names (e.g. `BI` -> `B1`, `CE` -> `C6`, `GA` -> `C3A`, `None` -> `C4`) and split/save individual PDFs.

### 11.2.2 What bugs were encountered during implementation and how were they resolved?

1. **Greedy OCR Suffix Letter Parsing**:
   * *Problem*: Digit-like letters (like `A` and `B` which map in `OCR_MAP` to 4 and 8) were parsed as core numbers (e.g. `"B2A"` -> `("B", 24, "")` and `"B2B"` -> `("B", 28, "")`) instead of suffix letters.
   * *Solution*: Conditioned suffix letter parsing to match any alphabetic character if preceded by a digit (since suffix letters are always at the very end of the string), without excluding digit-like characters. Added suffix fallback for single-character remains (e.g. `"GA"` parses as prefix `"G"`, core `0`, suffix `"A"` representing `C3a`), preventing it from wrongly matching `"C4"`.
2. **Strict 1-to-1 Sequence Alignment Failure**:
   * *Problem*: Strict 1-to-1 matching DP alignment failed when there were more split page blocks than expected entries (`m > n`), which commonly occurs due to photo/discard pages or OCR splits.
   * *Solution*: Refactored the DP alignment algorithm to allow skips (gaps in block sequence) and match empty blocks to gap slots by introducing a skip transition `score_skip = dp[i-1][j]`.
3. **Loose Block Splitting Conditions**:
   * *Problem*: Splitting page blocks every time `sheet_x == 1` was encountered separated summary sheets (which lack sheet numbers) from log sheets (which start at sheet 1).
   * *Solution*: Removed the raw `sheet_x == 1` split rule. Implemented a name-change split rule that only splits when the name changes to a valid expected name, with an exception that consecutive sheet increments (e.g. sheet 1 -> 2 -> 3) never trigger splits.
4. **Outlier Total Sheet Counts**:
   * *Problem*: OCR misread `Sheet 2 of 3` as `Sheet 2 of 863`, setting the expected sheet count to `863` and causing verification checks to fail.
   * *Solution*: Filtered out outlier expected sheet counts `> 20` and defaulted to `max(max_detected_x, len(bpages))`.

