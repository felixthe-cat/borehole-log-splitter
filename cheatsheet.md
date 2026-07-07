# Borehole Log Splitter — Developer Cheatsheet

This cheatsheet catalogs the core regular expressions, heuristics, and API call patterns for the Borehole Log Splitter & Extractor.

---

## 1. Local OCR Regexes & Heuristics

### Borehole Identifier Detection (`HOLE_PATTERNS`)
Used to extract the borehole identifier (e.g. `DH7`, `BH-01`).
```python
import re
HOLE_PATTERNS = [
    re.compile(r"\bHOLE\s+NO\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
    re.compile(r"\bBOREHOLE\s+NO\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
    re.compile(r"\bHOLE\s+N0\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
]
```
> [!WARNING]
> Use `[ \t]*` rather than `\s*` to prevent regex matching across line breaks.

### Sheet Sequence Extraction (`SHEET_PATTERNS`)
Used to parse "Sheet X of Y" page headers.
```python
SHEET_PATTERNS = [
    re.compile(r"\bSHEET\s*NO\.?\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bPAGE\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*NO\.?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*(\d+)\b", re.IGNORECASE),
]
```

### Page Classification Heuristics
- **Trash Keywords**: Cover page, indices, core photographs, photographic record:
  `["CORE PHOTOGRAPH", "PHOTOGRAPHIC RECORD", "COVER", "PHOTO LOG", "PHOTOGRAPHS", "KEY TO SHEET"]`
  Always use word boundaries `\b` when matching trash keywords (e.g. `\bCOVER\b`) to avoid false positive matches on words like `RECOVERY`.
- **Log Page Keywords**: Pages with keywords like:
  `["DRILLHOLE RECORD", "BOREHOLE RECORD", "BOREHOLE LOG", "DRILLHOLE LOG", "FLUSHING MEDIUM", "PENETRATION TEST", "METHOD = ROTARY", "ROTARY CO-ORDINATES", "AS SHEET"]`
  If a log page keyword is present, bypass the trash keyword filter.

---

## 2. PyMuPDF Native Page Rendering

Always use PyMuPDF (`fitz`) natively to render PDF pages into images in-memory, bypassing external `pdf2image` (Poppler) installation.

```python
import fitz
from PIL import Image
import gc

doc = fitz.open(pdf_path)
page = doc[page_index]  # 0-indexed
pix = page.get_pixmap(dpi=200)
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

# Perform operations...

# Cleanup is mandatory to prevent RAM bloat
img.close()
del img
doc.close()
gc.collect()
```

---

## 3. Gemini Multimodal Stratigraphy Extraction

### System Instruction
```
Act as an expert geotechnical engineer analyzing raw borehole log images.
Disregard peripheral data (flushing mediums, shift times, coordinates).
Focus entirely on Depth and Soil/Rock Description.
Ensure depth ranges are strictly continuous; if there is a gap, bridge it logically.
Classify a concise 'Soil/Rock Type'.
Provide the output strictly as raw CSV text with the headers:
Hole No,Sheet No,Start Depth,End Depth,Soil/Rock Description,Soil/Rock Type,Confidence Level
```

### Models & API Client
Initialize the client using the `google-generativeai` SDK:
```python
import google.generativeai as genai

genai.configure(api_key=api_key)
model = genai.GenerativeModel(
    model_name="gemini-3.5-flash",  # Default model
    system_instruction=system_instruction
)
```
Preferred models:
- `"gemini-3.5-flash"` (Default, high speed and reliable free quota)
- `"gemini-2.5-pro"` (For high-detail geotechnical extractions, subject to billing quota)

### Retry Logic (Exponential Backoff)
Handle rate limits (`429 ResourceExhausted`) and timeouts using exponential backoff:
```python
import time
import google.api_core.exceptions

def extract_stratigraphy_with_retry(model, images, borehole_name, max_retries=5, initial_delay=4.0, backoff_factor=2.0):
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            # Prepare content containing both PIL Images and text instructions
            content = list(images) + [f"Extract stratigraphy from this borehole log document for {borehole_name}."]
            response = model.generate_content(content)
            return response.text
        except google.api_core.exceptions.ResourceExhausted as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(delay)
            delay *= backoff_factor
```

---

## 4. CLI Argument Schema

| Option | Shorthand | Type | Default | Purpose |
|---|---|---|---|---|
| `--input` | `-i` | String | *Required* | Path to the scanned multipage input PDF. |
| `--output-csv` | `-o` | String | `borehole_stratigraphy.csv` | Master CSV location for stratigraphy data. |
| `--splits-dir` | | String | `temp_splits` | Temporary folder to save split borehole log PDFs. |
| `--keep-splits` | | Flag | `False` | Keep split PDFs instead of deleting them after extraction. |
| `--tesseract-path`| | String | `C:\Program Files\Tesseract-OCR\tesseract.exe` | Explicit path to the Tesseract OCR binary. |
| `--dpi` | | Integer | `200` | PDF page rendering DPI for OCR and extraction. |
| `--gemini-key` | | String | *None* | Override env `GEMINI_API_KEY` directly from CLI. |
| `--model` | | String | `gemini-3.5-flash` | The Gemini model name to use. |
| `--extract-only` | | Flag | `False` | Skip splitting/triage, process the input file directly. |
| `--hole-name` | | String | *None* | Explicit hole name when running `--extract-only`. |
