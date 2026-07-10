---
name: new-project-setup
description: Project-specific skill to scaffold a new project folder for the borehole pipeline. Creates a "Project - <Name>" folder at the repo root with the standard four blank subfolders ("Borehole Reports", "individual borehole logs", "outputs", "results"). Use this whenever the user wants to start a new client/site project, or asks to set up/create a new project folder for boreholes.
---
# New Project Setup Skill (Project-Specific)

This repo is organized per-project: every distinct client/site engagement lives in its own
folder named `Project - <Name>/`, containing the same four subfolders used by the
splitting/extraction pipeline (`Borehole Reports/`, `individual borehole logs/`, `outputs/`,
`results/`). This skill scaffolds a new, empty project folder.

## Step 1 — Get the project name

If the user already gave a project name in their request, use it directly. Otherwise, ask
the user for the project name before doing anything else (do not guess or invent one).

The folder name must always be prefixed with `Project - ` — if the user gives a name that
already starts with that prefix, don't double it up.

## Step 2 — Run the scaffold script

```powershell
python ".claude/skills/new-project-setup/scripts/create_project.py" --name "<Project Name>"
```

This creates:
```
Project - <Name>/
  Borehole Reports/
  individual borehole logs/
  outputs/
  results/
```

Each blank subfolder gets a `.gitkeep` placeholder so git tracks the empty structure.

The script errors out (does not overwrite) if a project folder with that name already exists.

## Step 3 — Confirm to the user

Report the created folder path and its four subfolders. Remind the user that master PDF
reports for this project go in `Project - <Name>/Borehole Reports/`, and that running the
splitter/extractor jobs for this project means passing `--project "Project - <Name>"` (for
`jobs/split_all_reports.py` / `jobs/extract_all_gemini.py`) or explicit paths scoped into
this folder (for `jobs/run_pipeline.py` and the audit/extractor skill scripts).
