---
name: borehole-audit
description: Project-specific skill to audit the borehole splitting/extraction pipeline for missed boreholes. Cross-checks the "HOLE NOS." list declared on page 2 of each report in a project's "Borehole Reports/" folder against the split PDFs in its "individual borehole logs/" and the master CSV in its "results/" (each project lives under "Project - <Name>/"), and flags supplementary/re-investigation reports whose newer split is missing (so the CSV would silently keep stale older data). Use this whenever the user asks to audit, double-check, or verify that no boreholes were missed, dropped, or skipped by the splitter or extractor — including after adding new reports to a project's "Borehole Reports/" or after re-running the splitter/extractor.
---
# Borehole Pipeline Audit Skill

This project-specific skill answers one question: **did every borehole declared in the
source reports actually make it all the way through the pipeline into the master
stratigraphy CSV?** It checks two handoffs — report → split PDF, and split PDF →
CSV row — and writes a markdown audit report.

It is read-only. It never edits the splitter/extractor output itself; re-running the
splitter or extractor for anything the audit flags is a separate task (see the
`borehole-log-splitter` and `borehole-data-extractor` skills).

## Project Folders
The repo is organized per-project: each project lives in a folder named `Project - <Name>/`
containing its own `Borehole Reports/`, `individual borehole logs/`, `outputs/`, and
`results/` subfolders. All paths below must be scoped to the relevant project folder
(e.g. `"Project - for Jasmine/Borehole Reports"`), never bare `"Borehole Reports"`.

## Why page 2, and why brackets

Every report in `<project>/Borehole Reports/` is a scanned Bachy Soletanche site-investigation
cover document. Page 2 (the title page) states, in brackets, the authoritative list of
hole numbers that report covers, e.g.:

> (HOLE NOS. DH5-DH51, DH53-DH60, B5, B6 & C5)

This bracketed list is the ground truth for "what should exist" — more reliable than
trying to infer coverage from the log pages themselves, since a hole can be present in
the scan but get miscategorized or dropped during OCR-based splitting.

These reports have no text layer (scanned images), so the list can't be grepped —
it must be read visually.

## Workflow

### Step 1 — Render each report's page 2

```powershell
python ".claude/skills/borehole-audit/scripts/render_cover_pages.py" `
  --reports-dir "Project - for Jasmine/Borehole Reports" `
  --output-dir "scratch/page2_check"
```

This uses native PyMuPDF rendering (per this project's hard rules — never poppler/pdf2image)
and writes one PNG per report to `scratch/page2_check/`.

### Step 2 — Transcribe the bracketed hole list from each PNG

Read each rendered PNG (vision) and transcribe the exact bracketed text, e.g.
`"DH5-DH51, DH53-DH60, B5, B6 & C5"`. Do not expand ranges yourself here — pass the raw
comma-separated tokens through as-is; `audit_boreholes.py` handles expansion
(numeric ranges like `DH53-DH60`, and suffix-letter runs like `B2a-B2c`).

Also note the report's date (from the cover page, e.g. "AUGUST, 1996") — this determines
report ordering and is what distinguishes a **new** set of boreholes from a
**supplementary/re-investigation** report that revisits hole numbers a prior report
already declared (same hole number appearing in two reports = a later re-investigation,
not two different boreholes).

Assemble one JSON file, one entry per report, matching this schema:

```json
[
  {
    "report": "SI for D-Wall and Barrettes By Bachy dated Aug1996 1.pdf",
    "report_label": "Aug1996",
    "date": "1996-08",
    "raw_tokens": ["P1", "P2", "P3", "P4", "P61", "P62", "P63", "P64", "B6a", "B6b", "C6a"]
  }
]
```

- `report`: the PDF filename (for the audit report's citations).
- `report_label`: the short prefix used in split filenames in `<project>/individual borehole logs/`
  (they follow `{report_label}_Borehole_{HOLE}.pdf`, e.g. `Jun1996_Borehole_DH7.pdf`).
  Get this right — it's how the script matches a report to its split logs and detects
  missing supplementary re-splits.
- `date`: a lexicographically-sortable date string (`YYYY-MM`) so reports sort
  chronologically even if filenames don't.
- `raw_tokens`: the bracketed list, comma-split, un-expanded, exactly as printed
  (keep original casing/hyphens — the script normalizes and expands).

Save this as e.g. `scratch/declared_holes.json`.

### Step 3 — Run the diff engine

```powershell
python ".claude/skills/borehole-audit/scripts/audit_boreholes.py" `
  --reports-json "scratch/declared_holes.json" `
  --splits-dir "Project - for Jasmine/individual borehole logs" `
  --results-dir "Project - for Jasmine/results" `
  --output "borehole_audit.md"
```

By default it diffs against the **newest** `<results-dir>/borehole_stratigraphy*.csv` (highest
`_vN` suffix, tie-broken by mtime) — pass `--csv` to target a specific file explicitly.

The script:
1. Expands every report's raw tokens into individual hole numbers.
2. Diffs the declared set against filenames in `<project>/individual borehole logs/`, using
   OCR-tolerant matching (collapses commonly-confused characters like `0/O`, `1/I/L`,
   `5/S`, `8/B` before comparing) so it doesn't false-flag known OCR name-garbling
   (e.g. `A5A` split as `ASA`) as a missing hole.
3. For any hole declared by more than one report (a re-investigation), checks that a
   split PDF exists tagged with **each** declaring report's `report_label` — if the
   newest report's split is missing, flags it specifically, since that means the master
   CSV is still holding the older report's data without anyone having decided that's
   correct.
4. Diffs the split-log hole set against the master CSV's `Hole No` column.
5. Writes `borehole_audit.md` with per-report declared lists, the two gap sections, and
   a summary action-items table.

### Step 4 — Report back

Summarize the audit's findings in your response (missing holes, stale re-investigation
gaps, extraction losses) — don't just say "audit complete," since the whole point is
surfacing what's missing. If the audit is clean, say so explicitly.

## Notes for future reports

- The script does not hardcode any hole numbers or report filenames — it discovers
  reports from whatever JSON you feed it and whatever's in `<project>/individual borehole logs/`
  and `<project>/results/`. Adding a new report to `<project>/Borehole Reports/` just means re-running
  Steps 1–3.
- If a report's page 2 has no bracketed hole list (rare, but possible for a differently
  formatted report), check page 1 and page 3 as fallbacks before giving up — the
  bracket is usually on the title page but pagination can shift by one.
- Don't invent an OCR-alias table by hand each time; the fuzzy matching in
  `audit_boreholes.py` already tolerates the common digit/letter confusions. If it still
  false-flags a real OCR variant, extend `OCR_EQUIVALENTS` in the script rather than
  special-casing it in your head.
