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
