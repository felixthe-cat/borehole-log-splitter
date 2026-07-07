# Error Book

This file logs technical bugs, API quirks, library wrapper issues, compiler/interpreter syntax errors, and their verified solutions.

## 1. pdf2image Poppler Dependency Error
* **Bug / Error:** Running `pdf2image` on Windows raises `Unable to get page count. Is poppler installed and in PATH?` if Poppler's binary folder is missing from system path.
* **API/Library:** `pdf2image`
* **Verified Solution:** Instead of requiring external C binaries like Poppler, refactor the PDF-to-image rendering to use PyMuPDF (`fitz`) natively.
  ```python
  doc = fitz.open(pdf_path)
  page = doc[page_idx]
  pix = page.get_pixmap(dpi=dpi)
  img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
  ```
  This returns a standard PIL `Image` object without any system dependency.

## 2. Google AI Studio gemini-1.5-pro 404/Not Found
* **Bug / Error:** Calling `models/gemini-1.5-pro` returns `404 models/gemini-1.5-pro is not found for API version v1beta`.
* **API/Library:** `google-generativeai` SDK
* **Verified Solution:** The `gemini-1.5-pro` model is deprecated or unavailable in this environment's free tier. 
  1. Add a `--model` command-line argument (defaulting to `gemini-2.5-pro` or `gemini-3.5-flash`) to allow flexibility.
  2. Fall back to `gemini-3.5-flash` for the free tier where `gemini-2.5-pro` quota is exhausted.

