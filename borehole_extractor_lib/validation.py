import re
import json
import csv
import io
import google.generativeai as genai

def check_depth_continuity(rows: list[list[str]]) -> list[str]:
    """
    Checks that:
    1. Every row has exactly 7 fields (corresponding to the 7 headers).
    2. Sheet No is a single integer number (preventing Excel date-parsing like '1-3').
    3. Start depth is strictly less than end depth for each layer.
    4. Depth ranges are of increasing depth and do not repeat or overlap.
    5. The ending depth of the Nth layer is the same as the starting depth of the N+1th layer (continuous).
    """
    errors = []
    parsed_rows = []
    
    for idx, r in enumerate(rows):
        if len(r) != 7:
            errors.append(f"Row {idx+1}: Invalid column count ({len(r)} columns, expected 7 columns separated by semicolons). Row data: {r}")
            continue
            
        sheet_no_str = r[1].strip()
        if not sheet_no_str.isdigit():
            errors.append(f"Row {idx+1}: Sheet No '{sheet_no_str}' is not a valid integer. Ranges (like '1-3') or text are not allowed.")
            continue
            
        try:
            start = float(r[2])
            end = float(r[3])
            
            if start >= end:
                errors.append(f"Row {idx+1}: Invalid depth range ({start:.2f} m to {end:.2f} m). Start depth must be less than end depth.")
                
            parsed_rows.append((start, end, idx, r))
        except ValueError:
            errors.append(f"Row {idx+1}: Non-numeric depth range '{r[2]}' to '{r[3]}'")
            
    if errors:
        return errors
        
    # Sort by start depth
    parsed_rows.sort(key=lambda x: x[0])
    
    # Check for duplicates, overlaps, and continuity (gaps)
    for i in range(len(parsed_rows) - 1):
        curr_start = parsed_rows[i][0]
        curr_end = parsed_rows[i][1]
        next_start = parsed_rows[i+1][0]
        next_end = parsed_rows[i+1][1]
        
        # Check for duplicates
        if abs(curr_start - next_start) < 0.005 and abs(curr_end - next_end) < 0.005:
            errors.append(
                f"Duplicate depth range detected: Multiple rows define depth range {curr_start:.2f} m to {curr_end:.2f} m."
            )
            continue
            
        # Check for overlaps
        if next_start < curr_end - 0.005:
            errors.append(
                f"Depth overlap detected: Layer {i+1} ({curr_start:.2f} - {curr_end:.2f} m) "
                f"overlaps with Layer {i+2} ({next_start:.2f} - {next_end:.2f} m)."
            )
            continue
            
        # Check for gaps (continuity)
        if next_start > curr_end + 0.005:
            errors.append(
                f"Depth gap detected: Layer ends at {curr_end:.2f} m but the next layer starts at {next_start:.2f} m."
            )
            
    return errors


def check_termination_depth(term_depth: float, last_end_depth: float) -> list[str]:
    """
    Verifies if the total termination depth of the borehole matches the final soil/rock layer end depth.
    """
    errors = []
    if term_depth and term_depth > 0.01:
        if abs(term_depth - last_end_depth) > 0.01:
            errors.append(
                f"Termination depth mismatch: The log page indicates a termination depth of {term_depth:.2f} m, "
                f"but the final extracted geological layer ends at {last_end_depth:.2f} m."
            )
    return errors


def check_title_block_consistency(title_blocks: list) -> list[str]:
    """
    Verifies that details in the title blocks match across all sheets of a single borehole.
    """
    errors = []
    if not title_blocks or len(title_blocks) <= 1:
        return errors
        
    first_page = title_blocks[0]
    # We strictly check 'hole_no', 'project_name', and 'project_number'
    fields_to_check = [
        ("hole_no", "Hole Number"),
        ("project_name", "Project Name"),
        ("project_number", "Project Number")
    ]
    for key, label in fields_to_check:
        val1 = str(first_page.get(key, '')).strip().lower()
        for idx, page_data in enumerate(title_blocks[1:], start=2):
            val2 = str(page_data.get(key, '')).strip().lower()
            # Skip check if one of the values is empty or unclear to prevent false positives
            if not val1 or not val2 or val1 in ["unknown", "n/a", "none"] or val2 in ["unknown", "n/a", "none"]:
                continue
            if val1 != val2:
                errors.append(
                    f"Title block mismatch: {label} differs between Page 1 ('{first_page.get(key)}') "
                    f"and Page {idx} ('{page_data.get(key)}')."
                )
    return errors


def check_description_and_classification(rows: list[list[str]]) -> list[str]:
    """
    Verifies that:
    1. Descriptions do not contain unresolved 'As Sheet X' references.
    2. Wash boring / No recovery descriptions are classified correctly (not as geological rock/soil types).
    """
    errors = []
    as_sheet_pattern = re.compile(r"\b(?:as|refer\s+to|per)\s+sheet\s*\d+", re.IGNORECASE)
    
    for idx, r in enumerate(rows):
        if len(r) < 6:
            continue
            
        desc = r[4].strip()
        material_type = r[5].strip().lower()
        
        # 1. Check for unresolved 'As Sheet X' references
        if as_sheet_pattern.search(desc):
            errors.append(
                f"Row {idx+1}: Unresolved description reference '{desc}'. "
                f"The description must state the actual geological material."
            )
            
        # 2. Check for Wash Boring / No Recovery classification consistency
        desc_lower = desc.lower()
        has_wash_boring = "wash boring" in desc_lower or "no recovery" in desc_lower or "core loss" in desc_lower or "core photo" in desc_lower
        
        if has_wash_boring:
            # Check if it was misclassified as a geological soil/rock type
            geological_types = ["granite", "tuff", "sand", "clay", "silt", "gravel", "rock", "alluvium"]
            if any(gt in material_type for gt in geological_types) and "fill" not in material_type:
                errors.append(
                    f"Row {idx+1}: Classification mismatch. Description mentions '{desc}', but it is classified as '{r[5]}'. "
                    f"Intervals with no material recovery must be classified as 'No Recovery' or 'Wash Boring'."
                )
    return errors


def request_gemini_correction(
    model: genai.GenerativeModel,
    images: list,
    borehole_name: str,
    original_json_str: str,
    errors: list[str]
) -> dict:
    """
    Sends the validation errors and original response JSON back to Gemini to request a corrected extraction.
    """
    from .extractor import EXTRACTION_SCHEMA
    errors_str = "\n".join([f"- {err}" for err in errors])
    prompt = (
        f"We extracted the following borehole data JSON for borehole '{borehole_name}':\n\n"
        f"{original_json_str}\n\n"
        f"However, the following validation checks failed on this extraction:\n"
        f"{errors_str}\n\n"
        f"Please re-analyze the provided log images and correct the data extraction for borehole '{borehole_name}'. "
        f"Make sure to resolve all continuity, termination depth, and title block issues. "
        f"Provide the output strictly as JSON matching the response schema."
    )
    contents = list(images) + [prompt]
    try:
        response = model.generate_content(
            contents,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": EXTRACTION_SCHEMA
            }
        )
        if not response or not response.text:
            print(f"    [Warning] Received empty response from Gemini during correction.")
            return {}
        return json.loads(response.text)
    except Exception as e:
        print(f"    [Error] Gemini correction request failed: {e}")
        return {}


def resolve_as_sheet_descriptions(rows: list[list[str]]) -> list[list[str]]:
    """
    Resolves descriptions like 'As Sheet X of Y' or 'As Sheet X' by copying the
    description and soil/rock type of the last layer of Sheet X.
    """
    try:
        sorted_rows = sorted(rows, key=lambda x: float(x[2]))
    except (ValueError, IndexError):
        return rows
        
    sheet_last_layers = {}
    for r in sorted_rows:
        if len(r) < 6:
            continue
        sheet_no = r[1].strip()
        sheet_last_layers[sheet_no] = r
        
    as_sheet_pattern = re.compile(r"(?:as|refer\s+to|per)\s+sheet\s*(\d+)", re.IGNORECASE)
    
    resolved_rows = []
    for r in sorted_rows:
        if len(r) < 6:
            resolved_rows.append(r)
            continue
            
        desc = r[4].strip()
        match = as_sheet_pattern.search(desc)
        if match:
            target_sheet = match.group(1).strip()
            if target_sheet in sheet_last_layers:
                target_layer = sheet_last_layers[target_sheet]
                target_desc = target_layer[4]
                target_type = target_layer[5]
                
                print(f"      [Resolve] Resolving '{desc}' using Sheet {target_sheet} bottom-most layer: '{target_desc}'")
                
                new_row = list(r)
                new_row[4] = target_desc
                new_row[5] = target_type
                resolved_rows.append(new_row)
                continue
                
        resolved_rows.append(r)
        
    return resolved_rows


def merge_consecutive_identical_layers(rows: list[list[str]]) -> list[list[str]]:
    """
    Merges consecutive layers with the same description (case-insensitive) into a single layer.
    """
    if len(rows) < 2:
        return rows
        
    try:
        sorted_rows = sorted(rows, key=lambda x: float(x[2]))
    except (ValueError, IndexError):
        return rows
        
    merged_rows = [sorted_rows[0]]
    
    for next_row in sorted_rows[1:]:
        curr_row = merged_rows[-1]
        
        try:
            curr_end = float(curr_row[3])
            next_start = float(next_row[2])
        except (ValueError, IndexError):
            merged_rows.append(next_row)
            continue
            
        desc1 = curr_row[4].strip().lower() if len(curr_row) > 4 else ""
        desc2 = next_row[4].strip().lower() if len(next_row) > 4 else ""
        
        if desc1 == desc2 and abs(curr_end - next_start) <= 0.005:
            print(f"      [Merge] Merging consecutive identical layers: {curr_row[2]}-{curr_row[3]} m and {next_row[2]}-{next_row[3]} m")
            curr_row[3] = next_row[3]
        else:
            merged_rows.append(next_row)
            
    return merged_rows


def normalize_degree_symbols(rows: list[list[str]]) -> list[list[str]]:
    """
    Replaces degree symbols (°) in descriptions with the word 'degrees'.
    """
    for r in rows:
        if len(r) >= 5:
            r[4] = r[4].replace("°", " degrees").replace("º", " degrees")
    return rows
