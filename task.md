# Tasks - Verification Checks & Data Extractor Skill

- [x] Fix the `borehole_splitter.py` redirection wrapper in the skill folder
- [x] Create the `borehole-data-extractor` skill directory and `SKILL.md`
- [x] Refactor `borehole_splitter.py` (orchestrated via jobs/run_pipeline.py) in the project root to add verification steps:
  - [x] Implement `check_depth_continuity`
  - [x] Implement `check_termination_depth` (using Gemini check)
  - [x] Implement `check_title_block_consistency` (using Gemini check)
  - [x] Implement the self-correction retry loop and summary report
- [x] Verify script compilation
- [x] Verify execution on `Borehole_DH7.pdf`
- [x] Create final walkthrough documentation
