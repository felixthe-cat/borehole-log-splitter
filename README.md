# Borehole Log Splitter & Multimodal Extractor

An automated Python document processing pipeline to process flat, scanned multipage PDFs of Ground Investigation (GI) borehole logs, triage and split them by borehole number, and extract geological stratigraphy into a structured master CSV file using the Google AI Studio (Gemini 1.5 Pro) API.

---

## Windows Prerequisites & Installation Guide

This utility requires two external system binaries to handle PDF rendering and OCR processing. Follow these steps to set them up:

### 1. Tesseract OCR Engine Setup
Tesseract is an open-source OCR engine. To install it on Windows:
1. **Download the Installer**: Visit the [UB Mannheim Tesseract Wiki](https://github.com/UB-Mannheim/tesseract/wiki) and download the latest 64-bit installer (e.g., `tesseract-ocr-w64-setup-...exe`).
2. **Run the Installer**:
   - Double-click the downloaded `.exe` file.
   - Follow the prompts. By default, it will install to: `C:\Program Files\Tesseract-OCR`
3. **Add to System PATH (Optional but Recommended)**:
   - Press the Windows Key and search for **Edit the system environment variables**.
   - Click the **Environment Variables...** button.
   - Under **System variables**, select the **Path** variable and click **Edit...**.
   - Click **New** and add the installation folder path: `C:\Program Files\Tesseract-OCR`
   - Click **OK** to save all dialogs.
   - *Note: If you do not add it to PATH, you can pass the path directly to the script using the `--tesseract-path` parameter.*

### 2. Poppler Setup (Required for PDF-to-Image conversion)
`pdf2image` relies on Poppler (specifically `pdftoppm`) to extract images from PDF files.
1. **Download Poppler**: Download a compiled Windows binary release from [poppler-windows on GitHub](https://github.com/oschwartz10612/poppler-windows/releases/) (download the latest `.zip` file).
2. **Extract Files**: Extract the folder inside the `.zip` file to a permanent location on your drive, for example: `C:\poppler`
3. **Add `bin` folder to System PATH (Optional but Recommended)**:
   - Following the environment variables steps above, edit your **Path** variable.
   - Add the path to the `bin` directory inside your extracted Poppler folder (e.g., `C:\poppler\Library\bin` or `C:\poppler\bin`).
   - Click **OK** to save.
   - *Note: If you do not add it to PATH, you can pass the path directly to the script using the `--poppler-path` parameter.*

---

## Installation & Setup

1. **Clone or copy this project folder** to your computer.
2. **Install Python dependencies**:
   Open a terminal (PowerShell or Command Prompt) in this directory and run:
   ```powershell
   pip install -r requirements.txt
   ```
3. **Set Up Authentication**:
   - Copy the `.env.example` file in the root folder and rename it to `.env`:
     ```powershell
     copy .env.example .env
     ```
   - Open `.env` and replace `your_api_key_here` with your actual Gemini API key from [Google AI Studio](https://aistudio.google.com/):
     ```env
     GEMINI_API_KEY=AIzaSy...
     ```

---

## How the Pipeline Works

The pipeline is split into three phases run sequentially within the script:

1. **Phase 1: Local OCR & Page Triage (The Splitter)**
   - Converts each PDF page to a high-resolution image in memory.
   - Runs Tesseract OCR to scan for the borehole number (e.g., `HOLE NO. BH-01`).
   - Discards invalid/administrative pages containing keywords like `INDEX`, `COVER`, `CORE PHOTOGRAPHS`.
   - Slices valid page groups and saves them as separate PDFs (e.g., `Borehole_BH-01.pdf`).
2. **Phase 2: Multimodal Extraction (Gemini 1.5 Pro)**
   - Ingests the split borehole PDFs.
   - Renders them to images and feeds them directly to the Gemini API (`gemini-1.5-pro`).
   - Implements exponential backoff to handle rate limits, connection errors, and API timeouts.
3. **Phase 3: Output Formatting**
   - Parses the CSV output from Gemini using Python's standard `csv` library (preventing issues with description commas).
   - Appends all records to a single master CSV file (default: `borehole_stratigraphy.csv`).

---

## Usage

Run the script from your terminal:

```powershell
python borehole_splitter.py --input "path/to/your/GI_report.pdf" [options]
```

### Command Line Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--input`, `-i` | **Required**. Path to the scanned multipage input PDF file. | None |
| `--output-csv`, `-o` | Path to save the master stratigraphy CSV file. | `borehole_stratigraphy.csv` |
| `--splits-dir` | Directory to temporarily save the split PDF files. | `temp_splits` |
| `--keep-splits` | If set, preserves the split PDFs instead of deleting them. | `False` (Deletes splits) |
| `--tesseract-path` | Path to `tesseract.exe`. | `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| `--poppler-path` | Path to the Poppler `bin` directory. | None (Relies on System PATH) |
| `--dpi` | DPI resolution for image rendering. Higher is slower but more accurate. | `200` |
| `--gemini-key` | Google AI Studio API Key (overrides `.env` value). | None |

### Example Command with Custom Executable Paths and Preserving Splits
```powershell
python borehole_splitter.py `
  --input "C:\Geotech\Master_Logs.pdf" `
  --output-csv "C:\Geotech\output_stratigraphy.csv" `
  --keep-splits `
  --splits-dir "C:\Geotech\Split_Logs" `
  --tesseract-path "C:\Program Files\Tesseract-OCR\tesseract.exe" `
  --poppler-path "C:\poppler\Library\bin"
```
