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

## 6. Greedy OCR Suffix Parsing of Digit-like Letters (A, B)
* **Bug / Error:** `parse_name_to_tuple` parsed digit-like letters (like `A` and `B` which are mapped in `OCR_MAP` to 4 and 8) as core numbers instead of suffixes (e.g. `"B2A"` -> `("B", 24, "")` and `"B2B"` -> `("B", 28, "")`).
* **API/Library:** Custom parser logic
* **Verified Solution:** Suffix letters are always at the very end of the string. Change the condition to match any alphabetic suffix if preceded by a digit, without excluding digit-like characters:
  ```python
  if len(rest) >= 2 and rest[-1].isalpha() and is_numeric_char(rest[-2]):
      suffix = rest[-1]
      rest = rest[:-1]
  ```

## 7. Needleman-Wunsch DP Alignment Failure under `m > n`
* **Bug / Error:** Strict 1-to-1 DP sequence alignment fails (returns all unaligned blocks as `None`/empty) if there are more split blocks than expected boreholes (`m > n`), which occurs due to photo/discard pages or name-change splits.
* **API/Library:** Custom DP alignment logic
* **Verified Solution:** Refactor sequence alignment to allow skips (blocks matching nothing) by formulating the DP transition to include `score_skip = dp[i-1][j]`, and trace back skips to empty string `""` values:
  ```python
  score_skip = dp[i-1][j]
  if score_match >= score_skip:
      dp[i][j] = score_match
      parent[i][j] = (i - 1, best_k)
  else:
      dp[i][j] = score_skip
      parent[i][j] = (i - 1, j)
  ```

## 8. Outlier Total Sheet Counts from OCR Misread
* **Bug / Error:** OCR misreads `Sheet 2 of 3` as `Sheet 2 of 863`, setting the expected sheet count to `863` and causing verification checks to fail.
* **API/Library:** Custom verification logic
* **Verified Solution:** Filter out outlier expected sheet counts `> 20` and use `max(max_detected_x, len(bpages))` as fallback.

## 9. Windows CSV File Lock (PermissionError) in Excel
* **Bug / Error:** Attempting to delete or overwrite the master CSV (`results/borehole_stratigraphy.csv`) fails with `PermissionError: [WinError 32] The process cannot access the file because it is being used by another process` if the user has the file open in Microsoft Excel.
* **API/Library:** `os.remove` / `open`
* **Verified Solution:** Implement fallback filename naming logic (e.g. `results/borehole_stratigraphy_v2.csv`, `results/borehole_stratigraphy_v3.csv`) when a `PermissionError` is encountered on the target CSV, allowing execution to continue without crashing.

## 10. Excel CSV Single-Cell Row Aggregation (Semicolon Delimiter)
* **Bug / Error:** Semicolon-delimited CSV files display all data of a row in a single cell (column A) when opened directly in Microsoft Excel on systems where the regional list separator is not semicolon.
* **API/Library:** Microsoft Excel CSV parsing
* **Verified Solution:** Prepend `sep=;` as the very first line of the CSV file. Excel recognizes this special instruction and splits the semicolon-separated values into columns correctly.

## 11. Excel Date Format Auto-Conversion of Sheet Ranges
* **Bug / Error:** Sheet numbers represented as ranges (such as `1-3`) are auto-converted by Excel into a date format (like `1-Mar` or `Jan-03`), corrupting numerical data.
* **API/Library:** Microsoft Excel auto-format
* **Verified Solution:** Sanitize the sheet number by extracting only the first integer digit (e.g., `1-3` becomes `1`), satisfying the integer type check and preventing date conversions.

## 12. Degree Symbol Rendering Glitches in Excel
* **Bug / Error:** Geological joint angle descriptions using the degree symbol (`°` or `º`) render as corrupt ANSI sequences (like `Â°`) in Excel due to UTF-8 to ANSI encoding conflicts on Windows.
* **API/Library:** Microsoft Excel CSV loading
* **Verified Solution:** Implement a normalization step to replace the degree characters (`°` and `º`) in geological descriptions with the plain text `"degrees"`.

## 14. Gemini API Free Tier Daily Quota Exhaustion (429)
* **Bug / Error:** The Gemini API free tier has a strict daily request limit of 20 requests per model. Bulk processing of split borehole logs quickly exhausts this quota for `gemini-3.5-flash`, throwing a `Daily API request limit exceeded` error.
* **API/Library:** `google-generativeai` SDK
* **Verified Solution:**
  1. Catch `DailyQuotaExhaustedError` in the orchestration script.
  2. Implement an automatic fallback chain of alternative models (e.g. `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`) to resume the extraction process.

## 15. Unresolved "As Sheet X" References in Final Stratigraphy CSV
* **Bug / Error:** References like `"As Sheet X"` are not resolved if the reference sheet's bottom-most layer itself is missing or is also a reference, leaving unresolved reference text in the final description.
* **API/Library:** Custom normalisation / verification
* **Verified Solution:** Add a programmatic validation rule `check_description_and_classification` that flags any final description containing sheet reference patterns (e.g., `"As Sheet"`, `"Refer to Sheet"`). Failure triggers the self-correction retry loop, prompting the model to re-analyze the image and output the actual geological description.

## 16. Misclassification of Drilling Methods as Geological Material Types
* **Bug / Error:** Drilling methods with no recovery (e.g. `"Wash boring (No recovery)"`, `"Core loss"`) are misclassified as geological materials (like `"Granite"`, `"Sand"`) in the output, which is geologically incorrect.
* **API/Library:** Gemini classification / verification
* **Verified Solution:** Add a programmatic validation check that scans descriptions for keywords like "wash boring", "no recovery", or "core loss" and verifies that the `Soil/Rock Type` is classified as `"No Recovery"` or `"Wash Boring"` (or `"Fill"` if it says fill washed out), raising an error to trigger correction retries on failure.

## 17. Prefix Parser Failures on Digit-like Letters (BH1, OH1)
* **Bug / Error:** `parse_name_to_tuple` returned `None` for two-letter prefixes starting with digit-like letters (e.g. `B`, `O`) because they were matched as numeric characters, preventing them from being parsed as part of the prefix.
* **API/Library:** Custom parser logic in `config.py`
* **Verified Solution:** Require that the second character of a two-letter prefix must not be in `OCR_MAP`, allowing prefix groupings like `BH` and `OH` to parse correctly while still maintaining single-letter OCR correction (e.g., `BI` -> `B1`, `ASA` -> `A5A`).

## 18. Spaced Range Expansion Failure in Cover-Page List
* **Bug / Error:** `expand_cover_list` failed to expand ranges containing whitespace around the hyphen (e.g., `"B2a - B2c"` or `"DH53 - DH60"`) because the matching regexes strictly expected no spaces.
* **API/Library:** Custom cover-page parser in `config.py`
* **Verified Solution:** Clean all whitespace from the range string (`p_clean = p.replace(" ", "")`) before running regex matching and expansion.

## 19. Adjacent Borehole Grouping Splitting Safety Failure
* **Bug / Error:** If two boreholes are directly adjacent in the PDF with no photo page separating them, and the second borehole's name is read as `UNKNOWN`, the block-splitting logic failed to split them, outputting them as a single file.
* **API/Library:** Custom page grouping in `triage.py`
* **Verified Solution:** Add a transition split check: if we transition from a page with `sheet_x > 1` to a page with `sheet_x == 1`, it immediately splits the block.

## 20. Spurious Standalone "No Recovery" Layers Splitting Cored Rock Runs
* **Bug / Error:** Manual-verification audit (Project - for Jasmine, cross-checked against a manually-transcribed answer key) found that a brief "No recovery at X-Ym" footnote inside an otherwise fully-described, cored rock/soil run (TCR/SCR/RQD reported, Grade assigned either side) was being extracted as its own standalone `No Recovery` layer, incorrectly overriding the surrounding decomposition-grade classification for that sub-range. Confirmed against source PDF (hole B1, sheet 3: Grade column reads `IV` continuously across 23.82-24.11m even though the description separately notes "No recovery at 23.97m-24.11m").
* **API/Library:** Custom normalisation logic
* **Verified Solution:** Added `absorb_short_no_recovery_annotations` (`borehole_extractor_lib/validation.py`) — merges a short (<=2m), terse "No recovery" row back into the preceding described layer when the gap is small and the neighbour is a real rock/soil classification, leaving genuine multi-metre wash-boring/uncored sections untouched. Also added extraction-prompt rule 15 (`extractor.py` `SYSTEM_INSTRUCTION`) to prevent this at the source.

## 21. Inconsistent "(FILL)"-Suffixed Layers Not Classified as Type=Fill
* **Bug / Error:** Layers whose description explicitly ends in `(FILL)` were sometimes classified with `Soil/Rock Type` set to the specific grain-size material (e.g. `Sand`) instead of `Fill`, inconsistently across different extraction runs of the same site. Also found a `Concrete Slab` layer classified as `Type=Fill` instead of `Type=Concrete`.
* **API/Library:** Custom normalisation logic
* **Verified Solution:** Added `force_fill_and_concrete_types` (`borehole_extractor_lib/validation.py`) — forces `Type=Fill` for any `(FILL)`-suffixed description, and `Type=Concrete` for standalone `Concrete Slab` descriptions. Also added extraction-prompt rule 16.

## 22. Manually-Produced Answer Keys Can Themselves Contain Row-Alignment Errors
* **Bug / Error:** When cross-checking extracted data against a manually-transcribed Excel "answer key" for QA, found that the answer key itself had likely transcription errors for several holes (e.g. DH6: answer key lists weathering grade `V` for 0.00-0.20m, but the source PDF's Grade column is blank there — the layer is literally just "Concrete Slab", no grade recorded). Don't assume a manual answer key is ground truth without spot-checking discrepancies against the primary source.
* **API/Library:** N/A — audit process note
* **Verified Solution:** When running a discrepancy-comparison audit, always render and read the actual source PDF for any flagged mismatch before "correcting" the extraction — the reference data can be wrong too.



