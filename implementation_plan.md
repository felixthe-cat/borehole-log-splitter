# Implementation Plan - Geological Verification & Extraction Skill

This plan details how we will incorporate 3 verification steps into the data extraction workflow, implement a self-correction loop with Gemini to resolve verification failures, and package this workflow as a project-specific skill.

## User Review Required

> [!IMPORTANT]
> **API Verification and Token Usage**
> The verification steps (termination depth extraction and title block consistency check) require making additional queries to the Gemini API. We will use the cost-effective `gemini-3.5-flash` model by default to keep token usage low while maintaining high extraction accuracy.

## Proposed Changes

### 1. Verification & Correction Logic

#### [MODIFY] [borehole_splitter.py](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/borehole_splitter.py)
We will introduce a robust verification and self-correction block in the extraction loop:
1. **Verification Helpers:**
   - `check_depth_continuity(rows)`: Sorts rows by start depth and ensures `End Depth[i] == Start Depth[i+1]` for all rows, flagging any gaps or overlaps.
   - `check_termination_depth(model, images, last_end_depth)`: Queries Gemini to find the termination depth (bottom left corner of log sheet) and compares it to the final layer's end depth.
   - `check_title_block_consistency(model, images)`: Queries Gemini to extract title block details ('Hole No', 'Project Name', 'Project Number', 'Date') for each page and ensures they match across all pages of a borehole log.
2. **Self-Correction Retry Loop:**
   - If any validation check fails, the script will bundle the validation errors and the current CSV, send them back to Gemini, and request a corrected extraction.
   - The correction loop will run up to 3 times per borehole. If issues persist after 3 attempts, it logs the failures in a final verification summary.

---

### 2. Customizations & Skills

#### [NEW] [SKILL.md (borehole-data-extractor)](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/.agents/skills/borehole-data-extractor/SKILL.md)
We will define a new dedicated skill for the extraction workflow:
- **YAML Frontmatter**: Exposes name (`borehole-data-extractor`) and description.
- **Workflow Instructions**: Documents the direct extraction command, parameters, and the details of the three verification steps.

#### [MODIFY] [borehole_splitter.py (Wrapper)](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/.agents/skills/borehole-log-splitter/scripts/borehole_splitter.py)
- Fix the wrapper import to point to the actual `borehole_splitter.py` in the project root instead of the non-existent `jobs.run_pipeline`.

---

## Verification Plan

### Automated Checks
Ensure code compiles successfully:
```powershell
python -m py_compile borehole_splitter.py
```

### Manual Verification
1. Run the direct extraction on `individual borehole logs/Borehole_DH7.pdf`.
2. Inspect the terminal log output to verify that:
   - Verification checks are run for depth continuity, termination depth, and title blocks.
   - The validation outcomes (PASSED/FAILED) are printed.
   - The self-correction loop is triggered if errors are encountered.
