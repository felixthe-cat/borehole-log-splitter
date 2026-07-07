# Canonical Validation & Normalisation Rules
## Borehole Log Stratigraphy Extractor

> This document consolidates all data quality rules derived from real issues observed in this session.
> It is the single source of truth for what the pipeline must enforce on every extraction run.
> Rules are split into two categories: **Normalisation (N)** pre-passes that silently fix known data
> patterns, and **Validation (V)** checks that trigger Gemini self-correction retries on failure.

---

## Normalisation Pre-passes (Applied Before Validation)

These run first on the raw parsed output of every Gemini extraction. They are deterministic transforms — no API calls needed.

| ID | Rule | Root Cause | Implementation |
| :-- | :--- | :--- | :--- |
| **N1** | Resolve `"As Sheet X"` descriptions | Scanned logs use cross-reference shorthand for thick strata spanning multiple sheets | `resolve_as_sheet_descriptions()` — regex matches `As Sheet X`, `Per Sheet X`, `Refer to Sheet X`; copies the bottom-most layer description from Sheet X |
| **N2** | Merge consecutive identical layers | Thick strata spanning multiple log sheets produce duplicate extracted rows with matching descriptions | `merge_consecutive_identical_layers()` — sorts by start depth; merges adjacent rows whose descriptions match (case-insensitive) and whose depth boundary is continuous |

---

## Validation Checks (Trigger Self-Correction on Failure)

These run after normalisation. Failures are sent back to Gemini with a structured error message to request a corrected extraction (up to 3 retries).

### Group A — Depth Integrity

| ID | Rule | Error Type | Detection |
| :-- | :--- | :--- | :--- |
| **V1** | `Start Depth < End Depth` for every layer | Invalid layer | Programmatic: reject rows where `start >= end` |
| **V2** | No overlapping depth ranges between consecutive layers | Overlap | Programmatic: sort by start depth; check `start[i+1] >= end[i]` |
| **V3** | No duplicate depth ranges | Duplicate | Programmatic: flag when `abs(start[i] - start[i+1]) < 0.005 AND abs(end[i] - end[i+1]) < 0.005` |
| **V4** | No depth gaps between consecutive layers | Gap | Programmatic: flag when `abs(start[i+1] - end[i]) > 0.005` |
| **V5** | Final layer `End Depth` equals stated borehole termination depth | Depth mismatch | Gemini query: locate termination depth at bottom-left/bottom block of last log sheet |

### Group B — Administrative Integrity

| ID | Rule | Error Type | Detection |
| :-- | :--- | :--- | :--- |
| **V6** | `Hole No` is identical across all sheets of the borehole | Title block mismatch | Gemini query: extract title block of each page and compare |
| **V7** | `Project Name` is identical across all sheets | Title block mismatch | Gemini query |
| **V8** | `Project Number` is identical across all sheets | Title block mismatch | Gemini query |

---

## Rules Baked Into the Gemini System Prompt

To reduce reliance on post-hoc correction, the following rules are enforced directly in the Gemini `SYSTEM_INSTRUCTION` so the model self-enforces them on the first attempt:

| Instruction # | Corresponds To |
| :-- | :--- |
| Rule 3: Strictly continuous depths | V4 (gap prevention) |
| Rule 4: Start < End | V1 |
| Rule 5: Strictly increasing order | V2 |
| Rule 6: No duplicate rows | V3 |
| Rule 7: Merge cross-sheet identical strata | N2 |
| Rule 8: Resolve "As Sheet X" descriptions | N1 |
| Rule 9: Final depth = termination depth | V5 |

---

## Self-Correction Loop Summary

```
Raw Gemini CSV
    │
    ├── N1: Resolve "As Sheet X" references
    ├── N2: Merge consecutive identical layers
    │
    ├── V1–V4: Depth integrity checks       ──┐
    ├── V5:    Termination depth check        │ FAILED → bundle errors + CSV
    ├── V6–V8: Title block consistency        │ → send to Gemini for correction
    │                                          │ → re-apply N1 + N2 on corrected output
    │                                          │ → re-run V1–V8
    │                                          │ (max 3 retries)
    │                                          │
    └── ALL PASSED ─────────────────────────┘
            │
            └── Append to master CSV
```

---

## Known Gotchas (from this session)

| Issue | Root Cause | Fix Applied |
| :--- | :--- | :--- |
| CSV rows were being appended on every re-run, creating duplicates *across* runs | Output CSV was not deleted between test runs | User process fix: delete or use a unique filename per run |
| `google.generativeai` FutureWarning on import | Google deprecated the old SDK; new SDK is `google.genai` | Known/accepted for now; tracked for future migration |
| First-attempt extraction returned duplicate depth range rows | Gemini extracted each log sheet independently, repeating thick strata | Fixed by: richer system prompt (Rule 6, 7) + N2 normalisation |
| `"As Sheet X of Y"` descriptions passed through unchanged | Not detected by Gemini or original prompt | Fixed by: system prompt Rule 8 + N1 normalisation |
| `Borehole_DH7.pdf` rendered 4 page images but Sheets 1–4 only covered 0.00–30.37 m | Sheet 2 was entirely wash boring (no recovery); continuity was preserved | Confirmed correct — no fix needed |
