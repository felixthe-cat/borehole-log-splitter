# SOUL.md — Borehole Log Splitter Agent

> **All standing instructions now live in [`AGENTS.md`](AGENTS.md) — the single, agent-neutral
> source of truth.** This file is kept as the Antigravity entry point and simply points there.
> Read `AGENTS.md` before any task.

**Before starting any task:**
1. Read [`AGENTS.md`](AGENTS.md) — role, read/write protocol, architecture rules, hard rules, canonical paths.
2. Read [`cheatsheet.md`](cheatsheet.md) — correct OCR patterns, regexes, and Gemini API schemas.
3. Do **not** read `learnings.md` at task start (conceptual archive; load only on request).

**Where things live:**
| File / Directory | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Role, read/write protocols, hard rules, architecture guidelines. |
| [`cheatsheet.md`](cheatsheet.md) | Regex patterns, OCR gotchas, Gemini API models and extraction schemas. |
| [`borehole_extractor_lib/`](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/borehole_extractor_lib/) | Modular library package (OCR, triage, extraction, writing). |
| [`jobs/`](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/jobs/) | Run orchestration scripts. |
| [`outputs/`](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/outputs/) | Raw extraction output files. |
| [`results/`](file:///c:/Users/lawfe/VS%20Code%20Projects/Borehole%20Log%20Splitter/results/) | Master merged CSV outputs and reports. |
| `learnings.md` | Conceptual geotechnical and software engineering Q&A notes. |
| `error-book.md` | Specific past bugs and fixes. |
| `human-errors.md` | Checklist of configuration and logical mistakes. |
