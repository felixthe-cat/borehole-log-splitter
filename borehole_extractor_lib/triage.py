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
    smooth_borehole_sequence,
    expand_cover_list,
    align_sequences,
    parse_name_to_tuple,
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
    overwrite_splits: bool = True,
    short_report_name: str = None
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
        # Splits when sheet_x == 1, or when a new valid/expected borehole name starts
        page2_text = ""
        for p in pages_data:
            if p["page_num"] == 2:
                page2_text = p["raw_text"]
                break
        expected_boreholes = []
        if page2_text:
            expected_boreholes = expand_cover_list(page2_text)
        if not expected_boreholes and len(pages_data) >= 1:
            expected_boreholes = expand_cover_list(pages_data[0]["raw_text"])
            
        expected_set = {name.upper() for name in expected_boreholes}
        
        blocks = []
        current_block = []
        for pdata in pages_data:
            if pdata["is_log"] and not pdata["is_photo"]:
                should_split = False
                if current_block:
                    if pdata["sheet_x"] == 1 and current_block[-1]["sheet_x"] and current_block[-1]["sheet_x"] > 1:
                        should_split = True
                    elif pdata["detected_hole"] and pdata["detected_hole"] != "UNKNOWN":
                        votes = [p["detected_hole"] for p in current_block if p["detected_hole"] and p["detected_hole"] != "UNKNOWN"]
                        voted_name = Counter(votes).most_common(1)[0][0] if votes else None
                        if voted_name and pdata["detected_hole"] != voted_name:
                            # Check consecutive sheet exception
                            is_consecutive_sheet = False
                            if pdata["sheet_x"] and current_block[-1]["sheet_x"]:
                                if pdata["sheet_x"] == current_block[-1]["sheet_x"] + 1:
                                    is_consecutive_sheet = True
                                    
                            if not is_consecutive_sheet:
                                # Parse normalized representation
                                t_new = parse_name_to_tuple(pdata["detected_hole"])
                                t_old = parse_name_to_tuple(voted_name)
                                # Normalize expected list match
                                is_new_in_expected = False
                                if expected_set:
                                    # Direct or normalized tuple match
                                    for exp in expected_set:
                                        if exp == pdata["detected_hole"]:
                                            is_new_in_expected = True
                                            break
                                        t_exp = parse_name_to_tuple(exp)
                                        if t_exp and t_new and t_exp == t_new:
                                            is_new_in_expected = True
                                            break
                                            
                                if expected_set:
                                    if is_new_in_expected:
                                        should_split = True
                                else:
                                    if pdata["detected_hole"] != voted_name:
                                        should_split = True
                                    
                if should_split and current_block:
                    blocks.append(current_block)
                    current_block = []
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
        # We first build raw voted names for each block, identify the dominant prefix,
        # smooth the sequence to correct any errors, and then group.
        block_items = []
        for block in blocks:
            hole_votes = [p["detected_hole"] for p in block if p["detected_hole"]]
            voted_raw = Counter(hole_votes).most_common(1)[0][0] if hole_votes else None
            block_items.append({
                "block": block,
                "voted_raw": voted_raw,
                "corrected_name": voted_raw
            })
            
        # Determine dominant prefix from voted names
        dominant_prefix = "DH"
        prefixes = []
        for item in block_items:
            if item["voted_raw"]:
                match = re.match(r"^([a-zA-Z]{2})", item["voted_raw"])
                if match:
                    prefixes.append(match.group(1).upper())
        if prefixes:
            dominant_prefix = Counter(prefixes).most_common(1)[0][0]
            
        # Try to extract cover-page expected borehole list (page 2, page 1 fallback)
        page2_text = ""
        for p in pages_data:
            if p["page_num"] == 2:
                page2_text = p["raw_text"]
                break
                
        expected_boreholes = []
        if page2_text:
            expected_boreholes = expand_cover_list(page2_text)
        if not expected_boreholes and len(pages_data) >= 1:
            expected_boreholes = expand_cover_list(pages_data[0]["raw_text"])
            
        if expected_boreholes:
            # Sort expected list using first-letter prefix priority from raw blocks to match physical sequence
            block_prefixes = []
            for item in block_items:
                if item["voted_raw"]:
                    t = parse_name_to_tuple(item["voted_raw"])
                    if t and t[0]:
                        first_letter = t[0][0]
                        if first_letter not in block_prefixes:
                            block_prefixes.append(first_letter)
                            
            def get_expected_sort_key(name: str):
                t = parse_name_to_tuple(name)
                if not t:
                    return (999, "", 0, "")
                prefix, num, suffix = t
                first_letter = prefix[0] if prefix else ""
                try:
                    prefix_priority = block_prefixes.index(first_letter)
                except ValueError:
                    prefix_priority = 999
                return (prefix_priority, prefix, num, suffix)
                
            expected_boreholes.sort(key=get_expected_sort_key)
            print(f"\nSequence Verification: Found cover-page borehole list: {expected_boreholes}")
            
            raw_block_names = [item["voted_raw"] for item in block_items]
            aligned_names = align_sequences(raw_block_names, expected_boreholes)
            for idx, name in enumerate(aligned_names):
                block_items[idx]["corrected_name"] = name
                if block_items[idx]["voted_raw"] != name:
                    print(f"--> Cover page verified correction: '{block_items[idx]['voted_raw']}' -> '{name}'")
        else:
            print("\nSequence Verification: Cover-page borehole list not found. Falling back to sequence smoothing.")
            smooth_borehole_sequence(block_items, dominant_prefix)
        
        hole_to_pages = {}
        for item in block_items:
            block_hole = item["corrected_name"]
            if not block_hole:
                print(f"\n[Warning] Block of pages {[p['page_num'] for p in item['block']]} has no borehole name. Skipping.")
                continue
                
            for p in item["block"]:
                p["detected_hole"] = block_hole
                
            if block_hole not in hole_to_pages:
                hole_to_pages[block_hole] = []
            hole_to_pages[block_hole].extend(item["block"])
        
        # 5. Verify and split each borehole log
        for hole_no, bpages in hole_to_pages.items():
            bpages.sort(key=lambda p: p["page_num"])
            
            # Determine total sheet count Y
            sheet_y_values = [p["sheet_y"] for p in bpages if p["sheet_y"]]
            sheet_x_values = [p["sheet_x"] for p in bpages if p["sheet_x"]]
            block_y = None
            if sheet_y_values:
                most_common_y = Counter(sheet_y_values).most_common(1)[0][0]
                if most_common_y <= 20:
                    block_y = most_common_y
                else:
                    block_y = max(max(sheet_x_values) if sheet_x_values else 1, len(bpages))
            else:
                if sheet_x_values:
                    block_y = max(max(sheet_x_values), len(bpages))
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
            pdf_path_output = save_borehole_pdf(
                src_doc,
                page_indices,
                hole_no,
                splits_dir,
                overwrite=overwrite_splits,
                prefix=short_report_name
            )
            if pdf_path_output:
                prefixed_hole = f"{short_report_name}_{hole_no}" if short_report_name else hole_no
                created_splits.append((prefixed_hole, pdf_path_output))
                
    finally:
        src_doc.close()
        
    print("-" * 60)
    print(f"Phase 1 Complete. Split PDFs Created: {len(created_splits)}")
    print(f"Valid Pages Kept: {stats_valid}, Discarded: {stats_discarded}")
    
    return created_splits
