# Tasks

- [ ] **REMINDER (multi-device sync):** Before pushing to GitHub, copy/include the Claude
      Code chat session file(s) for this project into the repo directory (e.g. a
      `claude-sessions/` folder) so that when this repo is pulled on another computer,
      that device's Claude can see the full session history from every other device.
      Do this on every push, not just once.

- [x] Implement versioning and standard naming helpers in `borehole_extractor_lib/writer.py`
- [x] Implement filename validation checks in `borehole_extractor_lib/validation.py`
- [x] Export new functions in `borehole_extractor_lib/__init__.py`
- [x] Create the batch extraction orchestration script `jobs/extract_all_gemini.py`
- [x] Compile and verify syntax of modified files
- [x] Run a test execution to verify progress checkpointing and output versioning
- [x] Run the complete batch extraction on all individual borehole logs
