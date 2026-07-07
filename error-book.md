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

## 3. Windows UnicodeEncodeError in Console Output
* **Bug / Error:** Printing raw OCR text containing symbols like `\xab` or copyright signs throws `UnicodeEncodeError: 'cp950' codec can't encode character...` on Windows.
* **API/Library:** Standard Python `print` and `sys.stdout`
* **Verified Solution:** Reconfigure standard output to use UTF-8 encoding at the beginning of scripts on Windows:
  ```python
  if sys.platform.startswith('win'):
      import io
      sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
  ```

## 4. Greedy Regex Match Crossing newlines
* **Bug / Error:** Regular expression patterns using `\s*` match newline characters, causing them to capture tokens from the next line if the current line is truncated or misread.
* **API/Library:** `re` module
* **Verified Solution:** Replace `\s*` with `[ \t]*` in anchor regexes to ensure the match stays on the same line.

## 5. False Positive Trash Filtering due to Column Headers
* **Bug / Error:** Discarding pages containing the keyword `"INDEX"` filters out valid log sheets because they contain column headers like `"Plasticity Index"`.
* **API/Library:** Custom classification logic
* **Verified Solution:** Check for clear log sheet indicators (e.g. `"DRILLHOLE RECORD"`, `"FLUSHING MEDIUM"`, `"PISTON SAMPLE"`) and bypass the trash filter if they are present.


