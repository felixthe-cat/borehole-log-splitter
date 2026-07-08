# Walkthrough - Resilient Batch Borehole Log Extraction

This document summarizes the changes, verification steps, and execution results for the resilient batch extraction of all split borehole logs using the Gemini API.

---

## 1. Summary of Changes

### library updates (`borehole_extractor_lib/`)
We implemented versioning helpers, standard naming formatters, and filename verification checks:
- **`writer.py`**:
  - `get_next_master_csv_path(base_path)`: Resolves unique, version-incremented output paths (e.g. `results/borehole_stratigraphy_v1.csv`) so that previous master CSVs are never overwritten.
  - `get_next_borehole_version(hole_name, master_csv_path)`: Scans the master CSV `Hole No` column and increments the borehole suffix (e.g. `DH7_v1`, `DH7_v2`) if records already exist.
  - `get_standard_pdf_name(hole_no, prefix)` and `get_standard_excel_name(hole_name, prefix)`: Generates standard names matching project conventions.
  - Updated `save_borehole_pdf` to enforce standard PDF naming.
- **`validation.py`**:
  - `verify_pdf_filename(filename)`: RegEx-checks split PDF filename structure.
  - `verify_excel_filename(filename)`: RegEx-checks individual CSV log filename structure.
- **`__init__.py`**:
  - Exported all new helper functions for use in orchestration jobs.

### Batch Orchestration Job (`jobs/extract_all_gemini.py`)
We created a new orchestration script `jobs/extract_all_gemini.py` designed for robust batch processing of all split PDFs:
- **Progress Checkpointing**: Saves progress to `outputs/extraction_progress.json` after every successfully completed log. If execution is interrupted (e.g. by network disconnects or API quota limits), the script loads progress and resumes from the exact checkpoint.
- **Fallback Chain Integration**: Loops through fallback models (`gemini-3.5-flash` -> `gemini-2.5-flash` -> `gemini-2.5-flash-lite` -> `gemini-3.1-flash-lite`) if transient error or daily limit quota is encountered.
- **Normalisations & Validations**: Runs depth continuity, termination depth, title block consistency, and classification checks, employing the 3-retry self-correction loop when issues occur.

---

## 2. Verification & Execution Results

### Validation of Script Compilation
We successfully verified that all modified library files and the batch script compile with no errors:
```powershell
python -m py_compile jobs/extract_all_gemini.py borehole_extractor_lib/writer.py borehole_extractor_lib/validation.py borehole_extractor_lib/__init__.py
```

### Batch Processing Execution & Resiliency Check

1. **Initial Run**:
   - The script initialized the master CSV as `results/borehole_stratigraphy_v1.csv`, successfully preserving the original `results/borehole_stratigraphy.csv`.
   - Processed `Aug1996_Borehole_B6A.pdf` and `Aug1996_Borehole_B6B.pdf` successfully, writing results to the master CSV and saving individual raw CSV files.
   - On the 3rd log, the Gemini API daily request limits for free-tier primary models (`gemini-3.5-flash` and `gemini-2.5-flash`) were exhausted.
   - Following that, a network disconnection occurred (causing host lookup and connect timeout errors on the fallback models).
   - The script aborted cleanly and saved progress to `outputs/extraction_progress.json`.

2. **Resume Run**:
   - We triggered a resume. The script loaded `outputs/extraction_progress.json`, identified that the first 2 logs were completed, and skipped them.
   - Resumed extraction on `Aug1996_Borehole_C6A.pdf`.
   - Successfully completed processing all remaining **89 split borehole logs** in the directory.
   - The fallback chain handled daily quota exhaustions on primary models by executing extractions using `gemini-3.1-flash-lite`.

### Final Summary
- **Total Split Logs Scanned**: 91
- **Skipped (Already Processed)**: 2
- **Newly Processed**: 89
- **Failed**: 0
- **Generated Master CSV**: [borehole_stratigraphy_v1.csv](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/results/borehole_stratigraphy_v1.csv)
- **Individual CSV Logs Directory**: [outputs/](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/outputs/) (fully verified via `verify_excel_filename`)

---

## 3. Post-Extraction CSV Cleanup

We performed a cleanup step on the generated `results/borehole_stratigraphy_v1.csv` to create the final cleaned version:
- **Rule**: For duplicate borehole runs, we retained only the highest version (e.g. keeping `DH19_v2` and removing `DH19_v1`).
- **Standardization**: Stripped the version suffixes (`_v1`, `_v2`, etc.) from all `Hole No` entries, leaving only the clean borehole numbers.
- **Output**: Saved the cleaned file as [borehole_stratigraphy_v2.csv](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/results/borehole_stratigraphy_v2.csv).

