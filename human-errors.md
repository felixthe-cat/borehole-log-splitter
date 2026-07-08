# Human Errors

This file logs modeling errors, configuration oversights, logical mistakes, and detailing/layout checklist items.

## 1. Accidental `.env.txt` Extension (Windows Notepad Typo)
* **Error / Oversight:** Creating or saving a `.env` file via Windows Notepad by default appends a hidden `.txt` extension (resulting in `.env.txt`), unless "All Files (*.*)" is selected during save. The `python-dotenv` library fails to load configurations from `.env.txt` by default.
* **Impact:** `api_key = os.environ.get("GEMINI_API_KEY")` returns `None` and raises credentials errors.
* **Checklist / Fix:**
  - Verify directory listing with all file extensions enabled.
  - Rename the file using a shell: `mv .env.txt .env` or `Rename-Item .env.txt .env`

## 2. API Quota Exhaustion under Free Tier Bulk Processing
* **Error / Oversight:** Running bulk extraction jobs with a single default model (e.g. `gemini-3.5-flash`) on the Google AI Studio free tier. The free tier enforces a strict daily limit of 20 requests per model.
* **Impact:** Pipeline runs fail halfway through with 429 quota exhaustion errors.
* **Checklist / Fix:**
  - Before running bulk extractions, check the list of available models using `genai.list_models()`.
  - Configure a fallback chain of alternative models (e.g. `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`) in scripts to run when the primary model exhausts its daily request quota.


