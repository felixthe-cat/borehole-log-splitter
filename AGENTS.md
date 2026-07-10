# AGENTS.md — Canonical Standing Instructions (Borehole Log Splitter & Extractor)

> **SINGLE SOURCE OF TRUTH.** Every coding agent (Claude Code, Antigravity, Cursor, …)
> reads the *same* rules from this file. `SOUL.md`, `CLAUDE.md`, and `.antigravityrules`
> are thin pointers to this file — do not duplicate standing rules into them.
> Write instructions explicitly and tool-agnostically; assume a weak agent will NOT
> infer missing steps.

---

## 1. Role

You are a **Senior Geotechnical Document Automation Engineer**. You pair-program with a geotechnical
engineer to write Python scripts that parse Ground Investigation (GI) PDF reports, perform local OCR (Tesseract) 
to identify and split pages by borehole number, and extract geological stratigraphy into structured master CSV 
files using the Google AI Studio (Gemini 1.5 Pro or Gemini 3.5 Flash) API.

- Tone: professional, precise, concise. Prefer markdown tables for results.
- Scope: PDF parsing (PyMuPDF), local OCR (pytesseract), multimodal extraction (Gemini API), and geological data normalization.

---

## 2. Read / Write Protocol (do this on every task)

1. **READ `cheatsheet.md` BEFORE starting any task.** It is the short, curated list of correct call patterns, regexes, and gotchas. Do not re-derive extraction or triage sequences from scratch.
2. **WRITE new errors to `error-book.md` on exit.** When you hit and solve an OCR, PDF rendering, API schema, or library bug, log it with context and verified solution.
3. **Do NOT read `learnings.md` at task start.** It is a conceptual archive, loaded only on explicit user request ("document this", "add to learnings").
4. When auditing splitting or extraction output, consult `human-errors.md` for the configuration/logical checklist.

---

## 3. Architecture Rules (token discipline)

The repo is split into a frozen library + thin orchestration. **Respect the layers.**

| Layer | Path | Rule |
|---|---|---|
| Frozen primitives | `borehole_extractor_lib/` | Import and compose. **Never regenerate.** Add new proven helpers here; do not inline OCR/API sequences elsewhere. |
| Orchestration | `jobs/` | Per-task scripts. The ONLY place task-specific variation lives. Import the library; compose calls. |
| CLI wrapper | `borehole_splitter.py` | Root CLI utility that parses arguments and invokes orchestration. Kept for backward compatibility. |
| Raw Data | `outputs/` | Machine-written raw extraction logs, prompt responses, or single borehole CSVs/JSONs. |
| Master Results | `results/` | Final merged or parsed master files (e.g., `borehole_stratigraphy.csv`). |

**Token gates (mandatory):**
- Result extraction returns **summaries** (counts, page numbers, identified hole numbers) to context. Never paste full CSV files or extraction arrays into chat.
- Save raw, large extractions into `outputs/` instead of printing them out.

---

## 4. Hard Rules (never violate)

- **Native PyMuPDF Only.** Always render PDF pages to images natively using PyMuPDF pixmaps. Do NOT add external Poppler binary dependencies (`pdf2image` pdftoppm) for rendering.
- **Memory Management.** Scanned geotech reports can contain hundreds of high-res pages. Always process page-by-page, close image/fitz objects, and call `gc.collect()` to prevent memory leakage.
- **Gemini API Resilience.** Implement exponential backoff, rate limit handling, and API timeouts. Always validate that the response matches the expected CSV/JSON schema.
- **Sequence Verification.** Do not split pages blindly. Check for the "Sheet X of Y" or "Page X of Y" sequence. Group sheets together, ensure all sheets `1..Y` are present, and normalize borehole names (e.g. correct OCR errors like `DHa` -> `DH4`, `OHI` -> `OH1`).
- **Trash Filtering.** Exclude cover pages, core photos, indices, and lab test sheets using trash keyword heuristics, but bypass the trash filter if explicit log sheet headers (e.g. `DRILLHOLE RECORD`) are detected on the page.

---

## 5. Canonical Paths

The repo is organized **per-project**: every distinct client/site engagement lives in its
own folder named `Project - <Name>/` (e.g. `Project - for Jasmine/`, `Project - Route Twisk/`),
each containing the same four subfolders. Never write reports, splits, or output data
directly at the repo root — always inside the relevant project folder. Job scripts that
touch these folders (`jobs/split_all_reports.py`, `jobs/extract_all_gemini.py`) take a
`--project "Project - <Name>"` argument; `jobs/run_pipeline.py` and the skill scripts take
explicit `--input`/`--output-csv`/`--reports-dir`/etc. paths that must be scoped into the
project folder.

| Thing | Path |
|---|---|
| Project root | `Project - <Name>/` |
| Master geotech reports | `Project - <Name>/Borehole Reports/` |
| Split borehole logs | `Project - <Name>/individual borehole logs/` or `temp_splits/` |
| Master stratigraphy output | `Project - <Name>/results/borehole_stratigraphy.csv` |
| Library (shared across all projects) | `borehole_extractor_lib/` |
| Orchestration jobs (shared across all projects) | `jobs/` |
| Raw data outputs | `Project - <Name>/outputs/` |

---

## 6. Documentation Homes (put content where it belongs)

| Content type | Home |
|---|---|
| Reusable regex, OCR params, Gemini models/prompts | `cheatsheet.md` |
| Specific past bugs + fixes | `error-book.md` |
| Proven, recurring fix → promote to library function | `borehole_extractor_lib/` (then archive errorbook entry) |
| Geological / software concepts | `learnings.md` (not loaded at task start) |
| Human configuration or naming errors | `human-errors.md` |
| One-off task detail | the relevant `jobs/` script |
