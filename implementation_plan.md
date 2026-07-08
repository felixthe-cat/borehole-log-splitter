# Implementation Plan: Resilient Batch Extraction of Split Borehole Logs

This plan describes how we will implement a resilient, resumeable batch extraction tool to process all 91 split borehole logs under `individual borehole logs/` using the Gemini API. It ensures we do not overwrite the existing master CSV or individual logs, and implements a checkpoint/resume mechanism to handle potential internet disconnections or agent reloads.

---

## User Review Required

> [环境保护] [IMPORTANT]
> The batch process runs Phase 2 (Gemini extraction) and Phase 3 (verification/normalisation) on all 91 split PDFs in `individual borehole logs/`.
> To prevent overwriting the existing master CSV (`results/borehole_stratigraphy.csv`), we will auto-detect the next available versioned path (e.g. `results/borehole_stratigraphy_v1.csv` or `results/borehole_stratigraphy_v2.csv`) at the start of the batch run and save this path in a progress JSON checkpoint.

---

## Proposed Changes

We will implement the changes in the following components:

### 1. Versioning and Standard Naming Helpers

We will update the library to add:
- Auto-incrementing master CSV version helper.
- Auto-incrementing borehole name version helper (for the rows inside the CSV).
- Filename verification checks to enforce naming conventions.

#### [MODIFY] [writer.py](file:///c:/Users/lawfe/VS Code Projects/Borehole Log Splitter/borehole_extractor_lib/writer.py)
- Implement `get_next_master_csv_path(base_path: str) -> str`: Finds the next available file path (e.g., `results/borehole_stratigraphy_v1.csv`) if the base path already exists.
- Implement `get_next_borehole_version(hole_name: str, master_csv_path: str) -> str`: Scans the `Hole No` column in the master CSV to determine the next version suffix (e.g., `DH7_v1`, `DH7_v2`) for that borehole.
- Implement naming formatters:
  - `get_standard_pdf_name(hole_no: str, prefix: str = None) -> str`
  - `get_standard_excel_name(hole_name: str, prefix: str = None) -> str`

#### [MODIFY] [validation.py](file:///c:/Users/lawfe/VS Code Projects/Borehole Log Splitter/borehole_extractor_lib/validation.py)
- Implement filename verification checks:
  - `verify_pdf_filename(filename: str) -> bool`: Checks if the PDF filename matches `[Prefix]_Borehole_[Hole_No].pdf` or `Borehole_[Hole_No].pdf`.
  - `verify_excel_filename(filename: str) -> bool`: Checks if the CSV log filename matches `[Prefix]_Borehole_[Hole_No]_stratigraphy.csv` or `Borehole_[Hole_No]_stratigraphy.csv`.

#### [MODIFY] [__init__.py](file:///c:/Users/lawfe/VS Code Projects/Borehole Log Splitter/borehole_extractor_lib/__init__.py)
- Export the new helper and verification functions.

---

### 2. Resilient Batch Extraction Orchestration Script

We will create a new orchestration script `jobs/extract_all_gemini.py` specifically for processing all split logs in batch.

#### [NEW] [extract_all_gemini.py](file:///c:/Users/lawfe/VS Code Projects/Borehole Log Splitter/jobs/extract_all_gemini.py)
- Scan `individual borehole logs/` for all PDF files.
- Check for `outputs/extraction_progress.json`. If it exists, read it to resume the previous run; otherwise, initialize it:
  - Select the output master CSV path using `get_next_master_csv_path`.
  - Set `completed_files = {}`.
- Loop through each PDF file:
  - If the file is already marked as completed in `outputs/extraction_progress.json`, skip it.
  - Parse the borehole name and prefix from the filename (e.g., `Jun1996_Borehole_DH19.pdf` -> hole: `DH19`, prefix: `Jun1996`).
  - Render the PDF pages natively to PIL images using PyMuPDF.
  - Initialize the Gemini API client and run the extraction with the fallback chain of models:
    - Primary: `gemini-3.5-flash`
    - Fallbacks: `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`.
  - Apply normalisations (resolve "As Sheet X", merge consecutive identical layers, degree symbols).
  - Perform validation checks (depth continuity, termination depth, title block consistency, classification).
  - Run the self-correction retry loop (up to 3 times) if validations fail.
  - Set rows' `Hole No` to `versioned_hole = get_next_borehole_version(hole, master_csv_path)`.
  - Append rows to `master_csv_path`.
  - Save the individual raw extraction CSV to `outputs/` named via `get_standard_excel_name`.
  - Verify filename conventions of the split PDF and raw CSV before proceeding.
  - Record the PDF file as completed in `outputs/extraction_progress.json` and write the JSON file to disk.
  - Log progress to the console.
  - Sleep for 4 seconds to comply with rate limits.
- Handle connection errors and API quota exhaustion:
  - If a connection error occurs, retry the call up to 3 times. If it still fails, print a message and exit cleanly. The progress is saved, allowing the user/agent to resume the script later.
  - If the daily API quota is exhausted for all models in the fallback chain, log the issue and exit cleanly.

---

## Verification Plan

### Automated Tests
- Validate syntax and compile scripts:
  ```powershell
  python -m py_compile borehole_splitter.py jobs/extract_all_gemini.py borehole_extractor_lib/writer.py borehole_extractor_lib/validation.py
  ```

### Manual Verification
1. Run `python jobs/extract_all_gemini.py` on a small subset of logs or interrupt it after a few files to check:
   - Check if `outputs/extraction_progress.json` is created with the correct `master_csv_path` and `completed_files`.
   - Run the script again and verify that it skips the completed files.
   - Verify that the master CSV is named uniquely (e.g. `results/borehole_stratigraphy_v1.csv` or similar) and not overwriting the existing `results/borehole_stratigraphy.csv`.
   - Verify that individual CSV files in `outputs/` are named correctly (e.g., `Jun1996_Borehole_DH19_v1_stratigraphy.csv`) and are verified by `verify_excel_filename`.
