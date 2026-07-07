import os
import sys
import re
import fitz
import pytesseract
from PIL import Image
from collections import Counter

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Reconfigure stdout to UTF-8
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Regex constants
HOLE_PATTERNS = [
    re.compile(r"\bHOLE\s+NO\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
    re.compile(r"\bBOREHOLE\s+NO\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
    re.compile(r"\bHOLE\s+N0\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
]

SHEET_PATTERNS = [
    re.compile(r"\bSHEET\s*NO\.?\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bPAGE\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*NO\.?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*(\d+)\b", re.IGNORECASE),
]

def normalize_hole_name(name: str) -> str:
    if not name:
        return ""
    name = name.upper().strip()
    name = re.sub(r"\bDH-?S{1,2}(55)?\b", "DH55", name)
    name = re.sub(r"\bDHS(5+)\b", r"DH\1", name)
    name = re.sub(r"\bDHA(\d+)\b", r"DH4\1", name)
    if name in ("OHI", "OH-I"):
        name = "DH19"
    return name

def is_log_sheet_text(text: str) -> bool:
    text_upper = text.upper()
    keywords = ["DRILLHOLE RECORD", "BOREHOLE RECORD", "BOREHOLE LOG", "DRILLHOLE LOG"]
    return any(k in text_upper for k in keywords)

def get_page_metadata(doc, page_idx, dpi=150):
    page = doc[page_idx]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    text = pytesseract.image_to_string(img)
    img.close()
    
    # Extract hole
    hole_no = None
    for pattern in HOLE_PATTERNS:
        match = pattern.search(text)
        if match:
            hole_no = normalize_hole_name(match.group(1).strip())
            break
            
    # Extract sheet
    sheet_x = None
    sheet_y = None
    for pattern in SHEET_PATTERNS:
        match = pattern.search(text)
        if match:
            sheet_x = int(match.group(1))
            if len(match.groups()) > 1 and match.group(2) is not None:
                sheet_y = int(match.group(2))
            break
            
    is_log = is_log_sheet_text(text)
    
    is_photo = False
    for keyword in ["CORE PHOTOGRAPH", "PHOTOGRAPHIC RECORD", "PHOTO LOG", "PHOTOGRAPHS"]:
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
            is_photo = True
            break
    if re.search(r"\bBOX\s+\d+\s+OF\s+\d+\b", text, re.IGNORECASE):
        is_photo = True
        
    return {
        "hole": hole_no,
        "sheet_x": sheet_x,
        "sheet_y": sheet_y,
        "is_log": is_log,
        "is_photo": is_photo,
        "text": text
    }

def main():
    splits_dir = r"C:\Users\lawfe\VS Code Projects\Borehole Log Splitter\individual borehole logs"
    reports_dir = r"C:\Users\lawfe\VS Code Projects\Borehole Log Splitter\Borehole Reports"
    
    print("==================================================")
    # 1. Gather all split PDFs
    files = [f for f in os.listdir(splits_dir) if f.endswith(".pdf")]
    print(f"Auditing {len(files)} split logs in {splits_dir}...")
    
    # 2. Extract and compile list of all report pages to trace from
    print("Scanning available master reports for tracing...")
    reports = [os.path.join(reports_dir, f) for f in os.listdir(reports_dir) if f.endswith(".pdf")]
    report_pages_cache = []
    
    for rep in reports:
        print(f"  Reading report: {os.path.basename(rep)}...")
        doc = fitz.open(rep)
        for i in range(len(doc)):
            # We will do OCR dynamically when needed to save time, or cache page dimensions and basic info
            report_pages_cache.append({
                "report_path": rep,
                "page_idx": i,
                "metadata": None  # Will load lazily
            })
        doc.close()
    
    print(f"Cached {len(report_pages_cache)} total master report pages.")
    
    # Audit each file
    for filename in files:
        filepath = os.path.join(splits_dir, filename)
        doc = fitz.open(filepath)
        page_count = len(doc)
        print(f"\nAuditing Split File: {filename} ({page_count} pages)")
        
        # Run OCR on all pages of the split PDF
        pages_meta = []
        for i in range(page_count):
            meta = get_page_metadata(doc, i)
            pages_meta.append(meta)
        doc.close()
        
        # Determine borehole number by majority vote
        holes = [m["hole"] for m in pages_meta if m["hole"]]
        if not holes:
            # Check if filename indicates a borehole number
            fn_match = re.search(r"Borehole_([A-Za-z0-9\-]+)\.pdf", filename)
            if fn_match:
                block_hole = normalize_hole_name(fn_match.group(1))
            else:
                print(f"  [Warning] No borehole name could be identified for split file {filename}. Skipping.")
                continue
        else:
            block_hole = Counter(holes).most_common(1)[0][0]
            
        # If the filename or majority vote is CONTRACT or SOLETANCHE, check if it contains actual logs
        if block_hole in ("CONTRACT", "SOLETANCHE", "SHEET", "UNKNOWN"):
            # Check if there are any valid logs
            valid_logs = [m for m in pages_meta if m["is_log"] and not m["is_photo"]]
            if not valid_logs:
                print(f"  [Action] Deleting administrative/photo-only file: {filename}")
                os.remove(filepath)
                continue
            else:
                # Update block_hole using actual log data if possible
                log_holes = [m["hole"] for m in valid_logs if m["hole"] and m["hole"] not in ("CONTRACT", "SOLETANCHE", "SHEET", "UNKNOWN")]
                if log_holes:
                    block_hole = Counter(log_holes).most_common(1)[0][0]
                else:
                    print(f"  [Warning] Administrative name '{block_hole}' contains logs but cannot identify borehole number. Skipping.")
                    continue
        
        # Determine total sheet count Y
        sheet_y_vals = [m["sheet_y"] for m in pages_meta if m["sheet_y"]]
        block_y = None
        if sheet_y_vals:
            block_y = Counter(sheet_y_vals).most_common(1)[0][0]
        else:
            sheet_x_vals = [m["sheet_x"] for m in pages_meta if m["sheet_x"]]
            if sheet_x_vals:
                block_y = max(sheet_x_vals)
            else:
                block_y = page_count
                
        print(f"  Borehole: {block_hole}")
        print(f"  Pages: {page_count}, Expected Y: {block_y}")
        
        # Check sheet numbers
        present_sheets = set(m["sheet_x"] for m in pages_meta if m["sheet_x"] is not None)
        expected_sheets = set(range(1, block_y + 1))
        missing_sheets = expected_sheets - present_sheets
        
        # If page count matches block_y and no sheets are missing, it's perfect!
        if page_count == block_y and not missing_sheets:
            print(f"  [OK] Extraction is complete and verified!")
            # Rename file if it has a wrong name (e.g. Borehole_CONTRACT.pdf but it is actually Borehole_DH40.pdf)
            correct_filename = f"Borehole_{block_hole}.pdf"
            correct_filepath = os.path.join(splits_dir, correct_filename)
            if filename != correct_filename:
                print(f"  [Action] Renaming {filename} to {correct_filename}")
                if os.path.exists(correct_filepath):
                    # Merge pages
                    d1 = fitz.open(correct_filepath)
                    d2 = fitz.open(filepath)
                    d1.close()
                    d2.close()
                    os.remove(filepath)
                else:
                    os.rename(filepath, correct_filepath)
            continue
            
        print(f"  [Warning] Missing sheet numbers: {missing_sheets} or page count mismatch!")
        
        # We need to build/re-extract the complete set of pages for this borehole
        verified_pages_data = [None] * block_y
        
        # Keep existing verified pages
        for meta in pages_meta:
            if meta["sheet_x"] and 1 <= meta["sheet_x"] <= block_y:
                verified_pages_data[meta["sheet_x"] - 1] = {
                    "source": "split_pdf",
                    "meta": meta
                }
        
        # For any missing slot, search master reports
        for idx in range(block_y):
            sheet_no = idx + 1
            if verified_pages_data[idx] is not None:
                continue
                
            print(f"  Searching for Sheet {sheet_no} of {block_y} for Borehole {block_hole}...")
            found_page = None
            for pcache in report_pages_cache:
                if pcache["metadata"] is None:
                    rdoc = fitz.open(pcache["report_path"])
                    pcache["metadata"] = get_page_metadata(rdoc, pcache["page_idx"])
                    rdoc.close()
                    
                meta = pcache["metadata"]
                if meta["is_log"] and not meta["is_photo"]:
                    if meta["hole"] == block_hole and meta["sheet_x"] == sheet_no:
                        found_page = pcache
                        break
                    elif meta["sheet_x"] == sheet_no:
                        if meta["text"] and block_hole in meta["text"]:
                            found_page = pcache
                            break
            
            if found_page:
                print(f"    -> Found on report {os.path.basename(found_page['report_path'])} page {found_page['page_idx']+1}")
                verified_pages_data[idx] = {
                    "source": "report",
                    "report_path": found_page["report_path"],
                    "page_idx": found_page["page_idx"],
                    "meta": found_page["metadata"]
                }
            else:
                print(f"    -> [Error] Could not find Sheet {sheet_no} for Borehole {block_hole} in any report!")
                
        # If we successfully compiled the complete set of sheets
        if all(x is not None for x in verified_pages_data):
            print(f"  [Action] Recreating verified split PDF for {block_hole}...")
            out_doc = fitz.open()
            
            open_docs = {}
            for idx, pdata in enumerate(verified_pages_data):
                if pdata["source"] == "report":
                    rpath = pdata["report_path"]
                    if rpath not in open_docs:
                        open_docs[rpath] = fitz.open(rpath)
                    out_doc.insert_pdf(open_docs[rpath], from_page=pdata["page_idx"], to_page=pdata["page_idx"])
                else:
                    s_doc = fitz.open(filepath)
                    for orig_idx, meta in enumerate(pages_meta):
                        if meta["sheet_x"] == idx + 1:
                            out_doc.insert_pdf(s_doc, from_page=orig_idx, to_page=orig_idx)
                            break
                    s_doc.close()
            
            for d in open_docs.values():
                d.close()
                
            correct_filename = f"Borehole_{block_hole}.pdf"
            correct_filepath = os.path.join(splits_dir, correct_filename)
            
            temp_path = correct_filepath + ".tmp"
            out_doc.save(temp_path)
            out_doc.close()
            
            if os.path.exists(correct_filepath):
                os.remove(correct_filepath)
            os.rename(temp_path, correct_filepath)
            
            if filepath != correct_filepath and os.path.exists(filepath):
                os.remove(filepath)
                
            print(f"  [OK] Re-created split PDF: {correct_filepath}")
        else:
            print(f"  [Error] Re-extraction incomplete for {block_hole} because some sheets are missing.")

if __name__ == "__main__":
    main()
