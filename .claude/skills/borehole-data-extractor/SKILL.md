---
name: borehole-data-extractor
description: Project-specific skill to extract geological stratigraphy CSV from split borehole logs with continuous depth verification, duplicate/overlap detection, 'As Sheet X' description resolution, consecutive layer merging, and title block consistency checks.
---
# Borehole Data Extractor Skill

This project-specific skill ingests split, single-borehole PDF log documents, renders pages natively to PIL images using PyMuPDF, queries the Gemini API to perform multimodal stratigraphy extraction, applies pre-validation data normalisation, and runs a suite of geological verification checks to guarantee data quality before writing the final CSV.

## Prerequisites

- **Python Libraries**: `google-generativeai`, `python-dotenv`, `pymupdf` (fitz), `pytesseract`, `pillow`.
- **API Key**: A valid `GEMINI_API_KEY` configured in the local `.env` file.

## CLI Usage

Run the direct data extraction on a pre-split log PDF:

```powershell
python borehole_splitter.py `
  --input "individual borehole logs/Borehole_DH7.pdf" `
  --output-csv "results/borehole_stratigraphy.csv" `
  --extract-only `
  --model "gemini-3.5-flash"
```

### Key Arguments

| Argument | Description |
| :--- | :--- |
| `--input` / `-i` | Path to the input PDF (pre-split log sheet). Required. |
| `--extract-only` | Skip Phase 1 (splitting/triage) and extract directly. |
| `--output-csv` / `-o` | Output master CSV file path. |
| `--model` | Gemini model name (default: `gemini-3.5-flash`). |
| `--hole-name` | Override the borehole name parsed from the filename. |
| `--dpi` | Page rendering DPI (default: `150`). |

---

## Processing Pipeline Order

After calling Gemini and parsing the raw CSV, the pipeline applies the following steps **in order** before running validation checks:

### Step 1 — Resolve "As Sheet X" References (`resolve_as_sheet_descriptions`)
- **Trigger**: When a layer description reads `"As Sheet X of Y"`, `"Per Sheet X"`, or `"Refer to Sheet X"`, it indicates the actual description is on Sheet X.
- **Rule**: Look up the bottom-most layer on Sheet X and copy its description and soil/rock type to the current layer.
- **Why**: Scanned GI reports sometimes repeat a layer reference for a thick stratum that spans multiple sheets.

### Step 2 — Merge Consecutive Identical Layers (`merge_consecutive_identical_layers`)
- **Trigger**: Two or more adjacent layers (when sorted by start depth) share the exact same description.
- **Rule**: If consecutive layers are depth-continuous and have identical descriptions (case-insensitive match), merge them into a single layer spanning the full combined depth range.
- **Why**: Thick strata often span multiple borehole log sheets, producing duplicated rows in the extracted CSV that should be a single geological unit.

---

## Geological Verification Checks

After normalisation, the pipeline runs the following six checks. Failures trigger the self-correction retry loop (see below).

### Check 1 — Depth Range Validity and Ordering
- `Start Depth < End Depth` for every layer.
- Layers are in strictly increasing depth order.
- No duplicate depth ranges (identical start/end pairs) exist.
- No overlaps between consecutive layers.
- No gaps between consecutive layers (`End Depth[i] == Start Depth[i+1]`).

### Check 2 — Final Layer vs. Termination Depth
- The `End Depth` of the final geological layer must equal the borehole's stated termination depth.
- Termination depth is located at the bottom-left corner or the bottom title block of the last log sheet (keywords: `Termination Depth`, `End of Hole`, `EOB`).

### Check 3 — Title Block Consistency Across Sheets
- `Hole No`, `Project Name`, and `Project Number` extracted from each sheet's title block must be identical across all sheets for a single borehole.

### Check 4 — Column Count Consistency
- Every row of the output CSV must have exactly the same number of columns as the header row (7 columns). No extra columns from unquoted commas or malformed rows are allowed.

### Check 5 — Strict Numeric Formatting
- Columns intended to be numbers (`Sheet No`, `Start Depth`, `End Depth`) must strictly contain numeric values (a single positive integer for `Sheet No`, and floats for depths). Range formats (like `1-3`) or text suffixes are prohibited to avoid Excel formatting issues.

### Check 6 — Description Reference Resolution
- Final layer descriptions must not contain unresolved `"As Sheet X"` style references. The actual material descriptions must be resolved from the reference sheets.

### Check 7 — Classification Method Consistency
- Interval descriptions mentioning "wash boring", "no recovery", or "core loss" must be classified as "No Recovery" or "Wash Boring" (or "Fill" if fill material is washed out). They must not be misclassified as primary geological soil/rock types (e.g. Granite, Sand, Clay).

---

## Output Naming & Confidence Configurations

### 1. Run Isolation and Clean Hole Naming
- **Single-Run Scope**: The output master CSV must only contain borehole data extracted during the current run. Accumulating or retaining records from past runs in the final output is prohibited.
- **Base Borehole Identifiers**: Do not append auto-increment version suffixes (like `_v1`, `_v2`, etc.) to the borehole names. The `Hole No` column in the final output must strictly contain the clean, base borehole identifier (e.g., `DH7`, `B6A`).

### 2. OCR-Driven Confidence Levels
- **Tesseract OCR Confidence Mapping**: The `Confidence Level` column in the output CSV must be derived programmatically from the average pytesseract OCR word confidence score across the log sheet pages:
  - **High**: Average word confidence $\ge 85\%$
  - **Medium**: $70\% \le$ Average word confidence $< 85\%$
  - **Low**: Average word confidence $< 70\%$

---

## Self-Correction Retry Workflow

If any verification check fails, the pipeline:
1. Aggregates all validation errors into a structured list.
2. Sends the current CSV extraction and the full error list back to Gemini in a follow-up query, asking it to re-analyse the images and correct the discrepancies.
3. Re-applies normalisation passes (sheet resolution, consecutive merging, degree symbols).
4. Re-runs all verification checks.
5. Repeats up to **3 times**. If errors persist after 3 attempts, writes the best-effort CSV and prints a final **Geological Validation Issues Summary**.

---

## Canonical Validation Rule Reference

The following is the complete list of data-quality rules derived from real project experience with scanned GI reports. All rules are programmatically enforced in `borehole_extractor_lib/validation.py`.

| # | Rule | Violation Type | Detection Method |
| :-- | :--- | :--- | :--- |
| V1 | `Start Depth < End Depth` for every layer | Invalid range | Programmatic |
| V2 | Depth ranges are strictly increasing with no overlaps | Overlap | Programmatic |
| V3 | No duplicate depth ranges (exact start/end pair) | Duplicate | Programmatic |
| V4 | No depth gaps between consecutive layers | Gap | Programmatic |
| V5 | Final layer `End Depth` matches stated termination depth | Depth mismatch | Gemini query |
| V6 | Title block `Hole No` is identical across all sheets | Admin mismatch | Gemini query |
| V7 | Title block `Project Name` is identical across all sheets | Admin mismatch | Gemini query |
| V8 | Title block `Project Number` is identical across all sheets | Admin mismatch | Gemini query |
| V9 | Row column count matches header count (exactly 7 columns) | Structural mismatch | Programmatic |
| V10 | Sheet No and Depths are strictly numeric values (no text or ranges like '1-3') | Format mismatch | Programmatic |
| V11 | No unresolved '"As Sheet"' references remain in descriptions | Reference mismatch | Programmatic |
| V12 | Description wash boring/no recovery matches classified type | Classification mismatch | Programmatic |
| N1 | `"As Sheet X"` descriptions resolved to actual material | Normalisation | Programmatic |
| N2 | Consecutive identical layers merged into one | Normalisation | Programmatic |
| N3 | Degree symbols (°) normalized to the word 'degrees' | Normalisation | Programmatic |

> **Note**: Rules prefixed `V` are validations (they trigger correction retries on failure). Rules prefixed `N` are normalisation pre-passes (they transform the data silently before validation runs).
