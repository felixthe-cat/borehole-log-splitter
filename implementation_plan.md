# Implementation Plan - Robust Borehole Log Splitter & Verification

This plan outlines the enhancements to the Borehole Log Splitter script to address wrong splitting results, add a sequence verification mechanism that ensures all sheets of a borehole log are present, automatically trace missing sheets from the report, and audit the existing split logs in `individual borehole logs`.

## User Review Required

> [!IMPORTANT]
> **New Splitting Heuristic**
> We are changing the splitting algorithm from a single-pass contiguous loop to a two-pass **Block-Based OCR Extraction and Sequence Verification** algorithm. This logic will:
> 1. Normalize borehole names to handle OCR errors (e.g. `DHa2` -> `DH42`, `DHSS` -> `DH55`, `OHI` -> `DH19`).
> 2. Skip the trash filter for any page containing `DRILLHOLE RECORD` or `BOREHOLE RECORD` to prevent column headers like `PLASTICITY INDEX` from discarding valid sheets.
> 3. Group consecutive log sheets into blocks.
> 4. Verify that each block contains exactly the number of sheets `Y` indicated by the "Sheet X of Y" page header.
> 5. If any sheets are missing, search the other pages of the document to trace and insert the missing sheets.
> 6. Only output/save the split PDF when verification is fully satisfied.

## Proposed Changes

### 1. Skill Script & Root Script Updates

#### [MODIFY] [borehole_splitter.py](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/borehole_splitter.py)
#### [MODIFY] [scripts/borehole_splitter.py](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/.agents/skills/borehole-log-splitter/scripts/borehole_splitter.py)

We will modify both scripts to:
- Relax the whitespace boundary in `HOLE_PATTERNS` to use `[ \t]*` instead of `\s*` to prevent matching across newlines.
- Modify `classify_page` to check if a page is a log sheet (`is_log_sheet`) by searching for keywords: `DRILLHOLE RECORD`, `BOREHOLE RECORD`, `BOREHOLE LOG`, `DRILLHOLE LOG`.
- If `is_log_sheet` is True, bypass the `TRASH_KEYWORDS` check (such as `INDEX`).
- Parse the page for "Sheet X of Y" or "Page X of Y" using regex patterns and extract the values `X` and `Y`.
- Normalize borehole numbers:
  - Match characters case-insensitively.
  - Correct known OCR substitutions: `DHa` -> `DH4`, `DHSS` -> `DH55`, `DHS5` -> `DH55`, `OHI` -> `DH19`.
- Implement block grouping:
  - Identify blocks of consecutive log sheets.
  - Determine block hole number by majority vote of normalized names.
  - Determine total sheets `Y` from the block's pages.
- Implement sequence verification:
  - If block length matches `Y`, write the split PDF.
  - If block length is less than `Y`, identify which sheet numbers `X` are missing.
  - Scan the remaining document pages (including those classified as trash or not initially in the block) for any page that has:
    - Borehole name matching this block's borehole.
    - Sheet number matching the missing `X`.
  - Add the traced pages to the block in correct sheet order.
  - Re-verify. Only write the output PDF when verification is satisfied.

---

### 2. Batch Split Auditing & Re-extraction Script

#### [NEW] [audit_and_reextract.py](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/scratch/audit_and_reextract.py)
We will create a Python script to audit the `individual borehole logs` directory:
- Scan all existing split PDF files.
- OCR the pages of each split PDF.
- Identify the borehole number and verify if the page count matches the total sheet count `Y` in "Sheet X of Y".
- If pages are missing, find the correct report in the `Borehole Reports` folder, trace the missing pages, re-extract them, and recreate the split PDF.

---

## Verification Plan

### Automated Tests
1. Verify script syntax:
   ```powershell
   python -m py_compile borehole_splitter.py
   ```
2. Run the newly modified splitter on the Sep 1996 report:
   ```powershell
   python borehole_splitter.py --input "Borehole Reports\SI for D-Wall and Barrettes By Bachy dated Sep1996 1.pdf" --splits-dir "individual borehole logs" --keep-splits
   ```
3. Run the audit script to verify that all split logs in `individual borehole logs` are complete and correct:
   ```powershell
   python scratch/audit_and_reextract.py
   ```

### Manual Verification
- Verify that the resulting PDFs in `individual borehole logs` contain the correct number of sheets matching their header definitions.
