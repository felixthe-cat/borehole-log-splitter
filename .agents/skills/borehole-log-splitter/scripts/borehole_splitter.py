#!/usr/bin/env python3
"""
Borehole Log Splitter & Extractor
---------------------------------
Author: Antigravity (AI Coding Assistant)
Description:
    Processes flat, scanned multipage PDFs of Ground Investigation (GI) borehole logs.
    
    Phase 1: Converts pages to images, runs OCR (Tesseract) page-by-page, classifies them
    (keeps pages with valid borehole identifiers, discards cover pages, photo logs, etc.),
    groups valid contiguous pages, and splits them into separate output PDF files using PyMuPDF.
    
    Phase 2 & 3: Integrates with Google AI Studio (Gemini 1.5 Pro) using the google-generativeai SDK.
    Iterates through the split PDFs, converting them to PIL images and sending them directly
    to the Gemini API for multimodal extraction of geological stratigraphy. Captures the output
    and appends it to a single master CSV in the local project directory.
    
Memory Management:
    - Processes page-by-page during triage to avoid loading the entire document's images into memory.
    - Explicitly closes PIL Image objects after OCR and extraction.
    - Runs garbage collection (`gc.collect()`) after each page processing loop.
"""

import os
import sys
import re
import argparse
import gc
import time
import csv
import io
import fitz  # PyMuPDF
import pdf2image
import pytesseract
from dotenv import load_dotenv

# We import the generative AI modules inside a try-block to print clear instructions
# if requirements are not installed.
try:
    import google.generativeai as genai
    import google.api_core.exceptions
except ImportError:
    print("[Error] Missing required packages: 'google-generativeai'. "
          "Please run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

# ==========================================
# Configuration and Heuristics
# ==========================================

# Regex patterns to locate the Borehole Number anchor.
# Matches common variants like "HOLE NO. BH-01", "BOREHOLE NO. RC-2", etc.
# Restricted whitespace matching [ \t]* to avoid matching across newlines.
HOLE_PATTERNS = [
    re.compile(r"\bHOLE\s+NO\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
    re.compile(r"\bBOREHOLE\s+NO\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
    re.compile(r"\bHOLE\s+N0\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
]

# Sheet patterns to extract page sheet sequence X and Y (e.g. Sheet X of Y)
SHEET_PATTERNS = [
    re.compile(r"\bSHEET\s*NO\.?\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bPAGE\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*NO\.?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*(\d+)\b", re.IGNORECASE),
]

# Case-insensitive keywords that signify irrelevant administrative/visual pages
TRASH_KEYWORDS = [
    "CORE PHOTOGRAPH",
    "PHOTOGRAPHIC RECORD",
    "COVER",
    "PHOTO LOG",
    "PHOTOGRAPHS",
    "KEY TO SHEET",
]

# Default Tesseract installation path on Windows systems.
# If Tesseract is installed to a non-standard path, configure it via the --tesseract-path CLI option.
DEFAULT_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def sanitize_filename(name: str) -> str:
    """
    Sanitizes a string to make it safe for use as a filename on Windows.
    Replaces characters like / \\ : * ? " < > | with underscores.
    """
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def is_log_sheet_text(text: str) -> bool:
    """
    Detects if the text contains clear borehole log header markers.
    """
    text_upper = text.upper()
    keywords = ["DRILLHOLE RECORD", "BOREHOLE RECORD", "BOREHOLE LOG", "DRILLHOLE LOG"]
    return any(k in text_upper for k in keywords)


def normalize_hole_name(name: str) -> str:
    """
    Normalizes borehole identifiers to fix common OCR misreadings.
    """
    if not name:
        return ""
    name = name.upper().strip()
    name = re.sub(r"\bDH-?S{1,2}(55)?\b", "DH55", name)
    name = re.sub(r"\bDHS(5+)\b", r"DH\1", name)
    name = re.sub(r"\bDHA(\d+)\b", r"DH4\1", name)
    if name in ("OHI", "OH-I"):
        name = "DH19"
    return name


def classify_page(text: str) -> tuple[bool, str | None]:
    """
    Analyzes the OCR text of a page to determine if it should be kept or discarded.
    """
    if is_log_sheet_text(text):
        # Anchor Check: Look for the Borehole Number regex pattern
        for pattern in HOLE_PATTERNS:
            match = pattern.search(text)
            if match:
                hole_no = normalize_hole_name(match.group(1).strip())
                if hole_no:
                    return True, hole_no
        return True, "UNKNOWN"

    # Trash Filter: Check for explicit administrative or photo keywords using word boundaries
    for keyword in TRASH_KEYWORDS:
        pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
        if pattern.search(text):
            return False, f"Trash keyword detected: '{keyword}'"
            
    # Fallback check
    for pattern in HOLE_PATTERNS:
        match = pattern.search(text)
        if match:
            hole_no = normalize_hole_name(match.group(1).strip())
            if hole_no:
                return True, hole_no
                
    return False, "Borehole anchor ('HOLE NO.') not found"


def process_page_ocr(
    pdf_path: str,
    page_num: int,
    dpi: int,
    poppler_path: str | None = None
) -> tuple[bool, str | None, str]:
    """
    Converts a single page of a PDF to an image natively using PyMuPDF (without Poppler)
    and performs Tesseract OCR.
    
    Args:
        pdf_path: Path to the input PDF file.
        page_num: 1-indexed page number to process.
        dpi: Dots Per Inch resolution for PDF conversion.
        poppler_path: Directory path containing Poppler binaries (ignored, kept for compatibility).
        
    Returns:
        tuple[bool, str|None, str]: (is_valid, hole_no_or_reason, raw_text)
    """
    img = None
    doc = None
    try:
        # Open PDF and render the specific page to a pixmap using PyMuPDF (no Poppler needed)
        doc = fitz.open(pdf_path)
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        
        # Convert pixmap to PIL Image
        from PIL import Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        doc = None
        
        # Run Tesseract OCR on the image
        raw_text = pytesseract.image_to_string(img)
        
        # Close the image immediately to free memory resources
        img.close()
        img = None
        
        # Classify based on the extracted text
        is_valid, detail = classify_page(raw_text)
        return is_valid, detail, raw_text
        
    except Exception as e:
        return False, f"OCR/Rendering error: {str(e)}", ""
        
    finally:
        # Explicitly clean up resources and trigger GC to avoid memory leaks
        if doc:
            try:
                doc.close()
            except Exception:
                pass
        if img:
            try:
                img.close()
            except Exception:
                pass
        gc.collect()


def save_borehole_pdf(
    src_doc: fitz.Document,
    page_indices: list[int],
    hole_no: str,
    output_dir: str,
    overwrite: bool = True
) -> str | None:
    """
    Extracts the specified page indices from the source PDF and writes them
    to a separate PDF file. Overwrites the file if overwrite is True, otherwise appends.
    """
    if not page_indices:
        return None
        
    sanitized = sanitize_filename(hole_no)
    filename = f"Borehole_{sanitized}.pdf"
    output_path = os.path.abspath(os.path.join(output_dir, filename))
    
    try:
        if os.path.exists(output_path) and not overwrite:
            print(f"--> File {filename} already exists. Appending {len(page_indices)} page(s)...")
            out_doc = fitz.open(output_path)
            for p in page_indices:
                out_doc.insert_pdf(src_doc, from_page=p, to_page=p)
            
            temp_path = output_path + ".tmp"
            out_doc.save(temp_path)
            out_doc.close()
            
            os.remove(output_path)
            os.rename(temp_path, output_path)
        else:
            if os.path.exists(output_path):
                print(f"--> Overwriting existing file {filename} with {len(page_indices)} page(s)...")
            else:
                print(f"--> Creating {filename} with {len(page_indices)} page(s)...")
            out_doc = fitz.open()
            for p in page_indices:
                out_doc.insert_pdf(src_doc, from_page=p, to_page=p)
            out_doc.save(output_path)
            out_doc.close()
            
        print(f"    Saved split PDF: {output_path}")
        return output_path
    except Exception as e:
        print(f"[Error] Failed to save PDF for borehole {hole_no}: {e}", file=sys.stderr)
        return None


# ==========================================
# Phase 2 & 3: Gemini Multimodal Extraction
# ==========================================

def extract_stratigraphy_with_retry(
    model: genai.GenerativeModel,
    images: list,
    borehole_name: str,
    max_retries: int = 5,
    initial_delay: float = 4.0,
    backoff_factor: float = 2.0
) -> str:
    """
    Calls the Gemini API to extract stratigraphy from a list of PIL images.
    Implements exponential backoff to handle rate limits (429), server errors (5xx), and timeouts.
    """
    contents = list(images)
    contents.append(
        f"Please extract the stratigraphy table for borehole '{borehole_name}' from the provided log images. "
        "Provide the output strictly as raw CSV text matching the headers and formatting specified in the system instructions. "
        "Do not wrap the CSV in markdown code blocks."
    )
    
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            response = model.generate_content(contents)
            
            if not response.text:
                print(f" [Warning] Received empty response from Gemini for borehole {borehole_name}.")
                return ""
            return response.text
            
        except (google.api_core.exceptions.GoogleAPICallError, Exception) as e:
            err_msg = str(e).lower()
            
            # Identify transient errors that can be retried (rate limits, timeouts, server overloads)
            is_transient = any(term in err_msg for term in [
                "429", "resource_exhausted", "rate limit", "quota", 
                "503", "service_unavailable", "500", "internal server error",
                "timeout", "deadline exceeded", "connection", "remote end closed"
            ])
            
            if is_transient and attempt < max_retries:
                print(f"\n    [Transient API Error] {e.__class__.__name__}: {e}. "
                      f"Retrying in {delay:.1f}s (Attempt {attempt}/{max_retries})...", end="", flush=True)
                time.sleep(delay)
                delay *= backoff_factor
            else:
                print(f"\n    [Error] API call failed: {e}")
                raise e
                
    raise Exception(f"Failed to extract stratigraphy for borehole {borehole_name} after {max_retries} attempts.")


def clean_and_parse_csv(csv_text: str) -> list[list[str]]:
    """
    Cleans up the raw Gemini API CSV text response (removing markdown block syntax if present)
    and parses it using the standard csv.reader to handle commas in descriptions safely.
    """
    csv_text = csv_text.strip()
    
    # Remove markdown code block fences if present (e.g. ```csv ... ``` or ``` ... ```)
    if csv_text.startswith("```"):
        lines = csv_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        csv_text = "\n".join(lines).strip()
        
    if not csv_text:
        return []
        
    f_in = io.StringIO(csv_text)
    reader = csv.reader(f_in)
    
    rows = []
    for row in reader:
        if not row:
            continue
        row_cleaned = [cell.strip() for cell in row]
        
        # Skip header rows if generated in response
        row_lower = [cell.lower() for cell in row_cleaned]
        if any(h in row_lower[0] for h in ["hole", "borehole"]) and any("depth" in cell for cell in row_lower):
            continue
            
        rows.append(row_cleaned)
        
    return rows


def append_rows_to_master_csv(rows: list[list[str]], master_csv_path: str):
    """
    Appends parsed CSV rows to the master CSV file.
    Creates the file and writes the standard header if the file does not exist or is empty.
    """
    if not rows:
        return
        
    file_exists = os.path.exists(master_csv_path) and os.path.getsize(master_csv_path) > 0
    headers_expected = ["Hole No", "Sheet No", "Start Depth", "End Depth", "Soil/Rock Description", "Soil/Rock Type", "Confidence Level"]
    
    try:
        with open(master_csv_path, mode="a", encoding="utf-8", newline="") as f_out:
            writer = csv.writer(f_out)
            if not file_exists:
                writer.writerow(headers_expected)
            writer.writerows(rows)
        print(f"    Added {len(rows)} record(s) to: {os.path.basename(master_csv_path)}")
    except Exception as e:
        print(f"[Error] Failed to append rows to master CSV {master_csv_path}: {e}", file=sys.stderr)


# ==========================================
# Main Orchestration Loop
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract and split Ground Investigation (GI) borehole logs from a scanned multipage PDF and extract geological stratigraphy using Gemini 1.5 Pro."
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to the input scanned master PDF file"
    )
    parser.add_argument(
        "--output-csv", "-o",
        default="borehole_stratigraphy.csv",
        help="Path to the output master CSV file (default: borehole_stratigraphy.csv)"
    )
    parser.add_argument(
        "--splits-dir",
        default="temp_splits",
        help="Directory to temporarily save split PDFs (default: temp_splits)"
    )
    parser.add_argument(
        "--keep-splits",
        action="store_true",
        help="If set, preserve the split PDF files in splits-dir instead of deleting them after processing."
    )
    parser.add_argument(
        "--tesseract-path",
        default=DEFAULT_TESSERACT_PATH,
        help=f"Path to the tesseract.exe binary (default: {DEFAULT_TESSERACT_PATH})"
    )
    parser.add_argument(
        "--poppler-path",
        help="Path to the Poppler 'bin' directory (optional if in System PATH)"
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="DPI resolution for page rendering (default: 200)"
    )
    parser.add_argument(
        "--gemini-key",
        help="Google AI Studio API Key (optional, falls back to GEMINI_API_KEY env var)"
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="If set, skip Phase 1 (splitting/triage) and extract stratigraphy directly from the input PDF"
    )
    parser.add_argument(
        "--hole-name",
        help="Hole name to use for direct extraction (defaults to filename without extension if using --extract-only)"
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-pro",
        help="Gemini model name to use (default: gemini-2.5-pro)"
    )
    
    args = parser.parse_args()
    
    # 1. Validate Input File
    if not os.path.exists(args.input):
        print(f"[Error] Input PDF file does not exist: {args.input}", file=sys.stderr)
        sys.exit(1)
        
    created_splits = []
    if args.extract_only:
        hole_name = args.hole_name or os.path.splitext(os.path.basename(args.input))[0]
        if hole_name.lower().startswith("borehole_"):
            hole_name = hole_name[len("borehole_"):]
        created_splits = [(hole_name, os.path.abspath(args.input))]
        print("=" * 60)
        print("Borehole Log Direct Stratigraphy Extractor")
        print("=" * 60)
        print(f"Input PDF (Single Log): {args.input}")
        print(f"Borehole Name:          {hole_name}")
        print(f"Master CSV:             {args.output_csv}")
        print(f"DPI Resolution:          {args.dpi}")
        print(f"Poppler Path:            {args.poppler_path or 'System PATH'}")
        print("-" * 60)
    else:
        # 2. Configure Tesseract Path
        if os.path.exists(args.tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = args.tesseract_path
        else:
            print(f"[Warning] Tesseract executable not found at: {args.tesseract_path}")
            print("Will attempt to use system PATH environment variable for 'tesseract'.")
            
        # Ensure splits directory exists
        os.makedirs(args.splits_dir, exist_ok=True)
        
        print("=" * 60)
        print("Borehole Log Splitter & Stratigraphy Extractor Pipeline")
        print("=" * 60)
        print(f"Input PDF:        {args.input}")
        print(f"Master CSV:       {args.output_csv}")
        print(f"Splits Directory: {args.splits_dir}")
        print(f"Keep Splits:      {args.keep_splits}")
        print(f"DPI Resolution:    {args.dpi}")
        print(f"Poppler Path:      {args.poppler_path or 'System PATH'}")
        print("-" * 60)
        
        # 3. Open PDF Document for Phase 1 (Splitting)
        try:
            src_doc = fitz.open(args.input)
            total_pages = len(src_doc)
            print(f"Loaded master PDF: {total_pages} total pages found.")
        except Exception as e:
            print(f"[Error] Could not open PDF file with PyMuPDF: {e}", file=sys.stderr)
            sys.exit(1)
            
        # Phase 1: Local OCR & Triage
        print("\nStarting Phase 1: Local OCR & Page Triage (The Splitter)")
        print("-" * 60)
        
        pages_data = []
        stats_valid = 0
        stats_discarded = 0
        
        try:
            # 1. OCR all pages first to gather metadata
            for page_num in range(1, total_pages + 1):
                fitz_idx = page_num - 1
                print(f"Processing Page {page_num}/{total_pages}...", end="", flush=True)
                
                is_valid, detail, raw_text = process_page_ocr(
                    pdf_path=args.input,
                    page_num=page_num,
                    dpi=args.dpi,
                    poppler_path=args.poppler_path
                )
                
                sheet_x = None
                sheet_y = None
                for pattern in SHEET_PATTERNS:
                    match = pattern.search(raw_text)
                    if match:
                        sheet_x = int(match.group(1))
                        if len(match.groups()) > 1 and match.group(2) is not None:
                            sheet_y = int(match.group(2))
                        break
                
                is_log = is_log_sheet_text(raw_text)
                
                is_photo = False
                for keyword in ["CORE PHOTOGRAPH", "PHOTOGRAPHIC RECORD", "PHOTO LOG", "PHOTOGRAPHS"]:
                    pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
                    if pattern.search(raw_text):
                        is_photo = True
                        break
                if re.search(r"\bBOX\s+\d+\s+OF\s+\d+\b", raw_text, re.IGNORECASE):
                    is_photo = True
                
                detected_hole = None
                for pattern in HOLE_PATTERNS:
                    match = pattern.search(raw_text)
                    if match:
                        detected_hole = normalize_hole_name(match.group(1).strip())
                        break
                
                pages_data.append({
                    "page_num": page_num,
                    "fitz_idx": fitz_idx,
                    "is_log": is_log,
                    "is_photo": is_photo,
                    "detected_hole": detected_hole,
                    "sheet_x": sheet_x,
                    "sheet_y": sheet_y,
                    "raw_text": raw_text
                })
                
                if is_log and not is_photo:
                    print(f" LOG SHEET [Hole: {detected_hole or 'UNKNOWN'}, Sheet: {sheet_x} of {sheet_y}]")
                    stats_valid += 1
                else:
                    reason = "Photo page" if is_photo else "Non-log page"
                    print(f" DISCARD ({reason})")
                    stats_discarded += 1
            
            # 2. Forward and backward fill hole names for consecutive log pages
            for i in range(len(pages_data)):
                pdata = pages_data[i]
                if pdata["is_log"] and not pdata["is_photo"] and pdata["detected_hole"] is None:
                    prev_hole = None
                    for j in range(i - 1, -1, -1):
                        if pages_data[j]["is_log"] and not pages_data[j]["is_photo"]:
                            if pages_data[j]["detected_hole"]:
                                prev_hole = pages_data[j]["detected_hole"]
                                break
                    next_hole = None
                    for j in range(i + 1, len(pages_data)):
                        if pages_data[j]["is_log"] and not pages_data[j]["is_photo"]:
                            if pages_data[j]["detected_hole"]:
                                next_hole = pages_data[j]["detected_hole"]
                                break
                    
                    if prev_hole and next_hole and prev_hole == next_hole:
                        pdata["detected_hole"] = prev_hole
                    elif prev_hole and not next_hole:
                        pdata["detected_hole"] = prev_hole
                    elif next_hole and not prev_hole:
                        pdata["detected_hole"] = next_hole
                    elif prev_hole and next_hole:
                        pdata["detected_hole"] = prev_hole
            
            # 3. Group log pages by their final normalized borehole name
            hole_to_pages = {}
            for pdata in pages_data:
                if pdata["is_log"] and not pdata["is_photo"] and pdata["detected_hole"]:
                    hole = pdata["detected_hole"]
                    if hole not in hole_to_pages:
                        hole_to_pages[hole] = []
                    hole_to_pages[hole].append(pdata)
            
            # 4. Verify and split each borehole log
            for hole_no, bpages in hole_to_pages.items():
                # Sort pages by page_num to ensure sequence order
                bpages.sort(key=lambda p: p["page_num"])
                
                from collections import Counter
                # Determine total sheet count Y
                sheet_y_values = [p["sheet_y"] for p in bpages if p["sheet_y"]]
                block_y = None
                if sheet_y_values:
                    block_y = Counter(sheet_y_values).most_common(1)[0][0]
                else:
                    sheet_x_values = [p["sheet_x"] for p in bpages if p["sheet_x"]]
                    if sheet_x_values:
                        block_y = max(sheet_x_values)
                    else:
                        block_y = len(bpages)
                
                print(f"\nVerifying Borehole {hole_no}:")
                print(f"  Current pages: {[p['page_num'] for p in bpages]}")
                print(f"  Expected total sheets Y: {block_y}")
                
                verified_pages = list(bpages)
                
                # Sequence Verification Check
                if len(verified_pages) == block_y:
                    print(f"  Verification satisfied! Found exactly {block_y} sheets.")
                else:
                    print(f"  [Warning] Verification mismatch: page count is {len(verified_pages)}, expected {block_y}.")
                    present_sheets = set(p["sheet_x"] for p in verified_pages if p["sheet_x"] is not None)
                    expected_sheets = set(range(1, block_y + 1))
                    missing_sheets = expected_sheets - present_sheets
                    print(f"  Missing sheet numbers: {missing_sheets}")
                    
                    traced_pages = []
                    for missing_x in missing_sheets:
                        print(f"  Tracing Sheet {missing_x} of {block_y} for Borehole {hole_no}...")
                        found_page = None
                        for pdata in pages_data:
                            # Skip if already included
                            if pdata in verified_pages:
                                continue
                            # Search matches
                            if pdata["detected_hole"] == hole_no and pdata["sheet_x"] == missing_x:
                                found_page = pdata
                                break
                            elif pdata["sheet_x"] == missing_x and pdata["is_log"] and not pdata["is_photo"]:
                                if pdata["raw_text"] and hole_no in pdata["raw_text"]:
                                    found_page = pdata
                                    break
                        if found_page:
                            print(f"    -> Traced and found Sheet {missing_x} on PDF Page {found_page['page_num']}.")
                            traced_pages.append(found_page)
                        else:
                            print(f"    -> [Error] Could not find Sheet {missing_x} for Borehole {hole_no}.")
                    
                    if traced_pages:
                        verified_pages.extend(traced_pages)
                        verified_pages.sort(key=lambda p: p["page_num"])
                    
                    # Re-verify
                    if len(verified_pages) == block_y:
                        print(f"  Verification satisfied after tracing! Found exactly {block_y} sheets.")
                    else:
                        print(f"  [Error] Verification failed for Borehole {hole_no} (got {len(verified_pages)} of {block_y} sheets). PDF will NOT be saved.")
                        continue
                
                # Save split PDF
                page_indices = [p["fitz_idx"] for p in verified_pages]
                pdf_path = save_borehole_pdf(src_doc, page_indices, hole_no, args.splits_dir, overwrite=True)
                if pdf_path:
                    created_splits.append((hole_no, pdf_path))
                    
        finally:
            src_doc.close()
            
        print("-" * 60)
        print(f"Phase 1 Complete. Split PDFs Created: {len(created_splits)}")
        print(f"Valid Pages Kept: {stats_valid}, Discarded: {stats_discarded}")
        print("=" * 60)
    
    # 4. Phase 2 & 3: Multimodal Extraction & Output Formatting
    if not created_splits:
        print("No valid borehole logs were extracted. Exiting pipeline.")
        return
        
    # Load API Key securely
    load_dotenv()
    api_key = args.gemini_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n[Error] Google AI Studio GEMINI_API_KEY not found in environment or .env.", file=sys.stderr)
        print("To proceed with Phase 2 (Gemini extraction):")
        print("  1. Create a '.env' file in the project root folder.")
        print("  2. Add: GEMINI_API_KEY=your_actual_key")
        print(f"Note: Split PDFs have been preserved in: {os.path.abspath(args.splits_dir)}")
        sys.exit(1)
        
    # Initialize Google AI Studio SDK
    try:
        genai.configure(api_key=api_key)
        system_instruction = (
            "Act as an expert geotechnical engineer analyzing raw borehole log images. "
            "Disregard peripheral data (flushing mediums, shift times, coordinates). "
            "Focus entirely on Depth and Soil/Rock Description. "
            "Ensure depth ranges are strictly continuous; if there is a gap, bridge it logically. "
            "Classify a concise 'Soil/Rock Type'. "
            "Provide the output strictly as raw CSV text with the headers: "
            "Hole No,Sheet No,Start Depth,End Depth,Soil/Rock Description,Soil/Rock Type,Confidence Level"
        )
        model = genai.GenerativeModel(
            model_name=args.model,
            system_instruction=system_instruction
        )
    except Exception as e:
        print(f"[Error] Failed to initialize Gemini API client: {e}", file=sys.stderr)
        sys.exit(1)
        
    print("\nStarting Phase 2 & 3: Gemini Multimodal Extraction & CSV Appending")
    print("-" * 60)
    
    stats_extracted = 0
    stats_failed = 0
    
    for idx, (hole_no, pdf_path) in enumerate(created_splits, start=1):
        print(f"\n[{idx}/{len(created_splits)}] Extracting Borehole: {hole_no}")
        print(f"    Source PDF: {pdf_path}")
        
        # A. Convert split PDF pages to PIL images using PyMuPDF (natively, without Poppler)
        images = []
        doc = None
        try:
            doc = fitz.open(pdf_path)
            from PIL import Image
            for page in doc:
                pix = page.get_pixmap(dpi=args.dpi)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
            doc.close()
            doc = None
            print(f"    Rendered {len(images)} page image(s) for extraction.")
        except Exception as e:
            if doc:
                try:
                    doc.close()
                except Exception:
                    pass
            print(f"    [Error] Failed to render images from split PDF: {e}")
            stats_failed += 1
            continue
            
        if not images:
            print("    [Error] No pages rendered from split PDF.")
            stats_failed += 1
            continue
            
        # B. Call Gemini Multimodal model
        try:
            print("    Calling Gemini API (gemini-1.5-pro)...", end="", flush=True)
            csv_response = extract_stratigraphy_with_retry(
                model=model,
                images=images,
                borehole_name=hole_no,
                max_retries=5,
                initial_delay=4.0,
                backoff_factor=2.0
            )
            print(" Done.")
            
            # C. Clean and append response
            if csv_response:
                rows = clean_and_parse_csv(csv_response)
                if rows:
                    append_rows_to_master_csv(rows, args.output_csv)
                    stats_extracted += 1
                else:
                    print("    [Warning] Gemini response did not contain parseable CSV rows.")
                    stats_failed += 1
            else:
                print("    [Warning] Empty response received from Gemini.")
                stats_failed += 1
                
        except Exception as e:
            print(f"\n    [Error] Failed to extract data for borehole {hole_no}: {e}")
            stats_failed += 1
            
        finally:
            # Clean up PIL image resources
            for img in images:
                try:
                    img.close()
                except Exception:
                    pass
            del images
            gc.collect()
            
        # D. Clean up split PDF if temporary mode and not direct extraction
        if not args.extract_only and not args.keep_splits:
            try:
                os.remove(pdf_path)
                print(f"    Removed temporary split PDF: {pdf_path}")
            except Exception as e:
                print(f"    [Warning] Failed to delete temporary split PDF {pdf_path}: {e}")
                
        # E. Sleep delay between calls to respect rate limit (15 RPM)
        if idx < len(created_splits):
            print("    Waiting 4 seconds to comply with rate limits...")
            time.sleep(4.0)
            
    # Clean up empty temp splits directory
    if not args.extract_only and not args.keep_splits:
        try:
            if os.path.exists(args.splits_dir) and not os.listdir(args.splits_dir):
                os.rmdir(args.splits_dir)
                print(f"Cleaned up empty temporary directory: {args.splits_dir}")
        except Exception:
            pass
            
    print("=" * 60)
    print("Pipeline Execution Completed")
    print("=" * 60)
    print(f"Total Boreholes Found:  {len(created_splits)}")
    print(f"Successfully Extracted: {stats_extracted}")
    print(f"Extraction Failed:     {stats_failed}")
    print(f"Master CSV Location:    {os.path.abspath(args.output_csv)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
