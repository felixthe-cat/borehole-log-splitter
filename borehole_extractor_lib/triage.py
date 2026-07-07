import os
import re
import gc
from collections import Counter
import fitz  # PyMuPDF

from .config import (
    HOLE_PATTERNS,
    SHEET_PATTERNS,
    is_log_sheet_text,
    normalize_hole_name,
)
from .ocr import process_page_ocr
from .writer import save_borehole_pdf


def parse_sheet_numbers(text: str) -> tuple[int | None, int | None]:
    """
    Parses Sheet X of Y or Page X of Y from OCR text.
    """
    sheet_x = None
    sheet_y = None
    for pattern in SHEET_PATTERNS:
        match = pattern.search(text)
        if match:
            sheet_x = int(match.group(1))
            if len(match.groups()) > 1 and match.group(2) is not None:
                sheet_y = int(match.group(2))
            break
    return sheet_x, sheet_y


def triage_and_split_pdf(
    pdf_path: str,
    dpi: int,
    splits_dir: str,
    overwrite_splits: bool = True
) -> list[tuple[str, str]]:
    """
    Performs Phase 1: Local OCR and page triage.
    Identifies borehole sections, filters trash, groups pages, 
    verifies sequence continuity, traces missing pages, and saves split PDFs.
    
    Returns:
        list[tuple[str, str]]: List of (borehole_name, split_pdf_path)
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Input PDF not found: {pdf_path}")
        
    src_doc = fitz.open(pdf_path)
    total_pages = len(src_doc)
    
    pages_data = []
    stats_valid = 0
    stats_discarded = 0
    created_splits = []
    
    try:
        # 1. OCR all pages first to gather metadata
        for page_num in range(1, total_pages + 1):
            fitz_idx = page_num - 1
            print(f"Processing Page {page_num}/{total_pages}...", end="", flush=True)
            
            is_valid, detail, raw_text = process_page_ocr(
                pdf_path=pdf_path,
                page_num=page_num,
                dpi=dpi
            )
            
            sheet_x, sheet_y = parse_sheet_numbers(raw_text)
            is_log = is_log_sheet_text(raw_text)
            
            # Check for core photo page
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
        
        # 2. Group consecutive log pages into blocks
        blocks = []
        current_block = []
        for pdata in pages_data:
            if pdata["is_log"] and not pdata["is_photo"]:
                current_block.append(pdata)
            else:
                if current_block:
                    blocks.append(current_block)
                    current_block = []
        if current_block:
            blocks.append(current_block)
        
        # 3. For each block, forward/backward fill hole names
        for block in blocks:
            for i in range(len(block)):
                if block[i]["detected_hole"] is None:
                    prev_hole = None
                    for j in range(i - 1, -1, -1):
                        if block[j]["detected_hole"]:
                            prev_hole = block[j]["detected_hole"]
                            break
                    next_hole = None
                    for j in range(i + 1, len(block)):
                        if block[j]["detected_hole"]:
                            next_hole = block[j]["detected_hole"]
                            break
                    
                    if prev_hole and next_hole and prev_hole == next_hole:
                        block[i]["detected_hole"] = prev_hole
                    elif prev_hole and not next_hole:
                        block[i]["detected_hole"] = prev_hole
                    elif next_hole and not prev_hole:
                        block[i]["detected_hole"] = next_hole
                    elif prev_hole and next_hole:
                        block[i]["detected_hole"] = prev_hole
        
        # 4. Group log pages by their final voted normalized borehole name
        hole_to_pages = {}
        for block in blocks:
            hole_votes = [p["detected_hole"] for p in block if p["detected_hole"]]
            if not hole_votes:
                print(f"\n[Warning] Block of pages {[p['page_num'] for p in block]} has no borehole name. Skipping.")
                continue
            block_hole = Counter(hole_votes).most_common(1)[0][0]
            
            for p in block:
                p["detected_hole"] = block_hole
                
            if block_hole not in hole_to_pages:
                hole_to_pages[block_hole] = []
            hole_to_pages[block_hole].extend(block)
        
        # 5. Verify and split each borehole log
        for hole_no, bpages in hole_to_pages.items():
            bpages.sort(key=lambda p: p["page_num"])
            
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
                        if pdata in verified_pages:
                            continue
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
            pdf_path_output = save_borehole_pdf(src_doc, page_indices, hole_no, splits_dir, overwrite=overwrite_splits)
            if pdf_path_output:
                created_splits.append((hole_no, pdf_path_output))
                
    finally:
        src_doc.close()
        
    print("-" * 60)
    print(f"Phase 1 Complete. Split PDFs Created: {len(created_splits)}")
    print(f"Valid Pages Kept: {stats_valid}, Discarded: {stats_discarded}")
    
    return created_splits
