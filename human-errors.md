# Human Errors

This file logs modeling errors, configuration oversights, logical mistakes, and detailing/layout checklist items.

## 1. Accidental `.env.txt` Extension (Windows Notepad Typo)
* **Error / Oversight:** Creating or saving a `.env` file via Windows Notepad by default appends a hidden `.txt` extension (resulting in `.env.txt`), unless "All Files (*.*)" is selected during save. The `python-dotenv` library fails to load configurations from `.env.txt` by default.
* **Impact:** `api_key = os.environ.get("GEMINI_API_KEY")` returns `None` and raises credentials errors.
* **Checklist / Fix:**
  - Verify directory listing with all file extensions enabled.
  - Rename the file using a shell: `mv .env.txt .env` or `Rename-Item .env.txt .env`

