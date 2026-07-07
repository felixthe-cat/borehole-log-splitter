import re
import json
import csv
import io
import google.generativeai as genai

def check_depth_continuity(rows: list[list[str]]) -> list[str]:
    """
    Checks that:
    1. Start depth is strictly less than end depth for each layer.
    2. Depth ranges are of increasing depth and do not repeat or overlap.
    3. The ending depth of the Nth layer is the same as the starting depth of the N+1th layer (continuous).
    """
    errors = []
    parsed_rows = []
    
    for idx, r in enumerate(rows):
        if len(r) < 4:
            errors.append(f"Row {idx+1}: Incomplete data row (fewer than 4 fields)")
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


def check_termination_depth(model: genai.GenerativeModel, images: list, last_end_depth: float) -> list[str]:
    """
    Extracts the termination depth of the borehole from the log sheet (typically at bottom-left)
    and verifies if it matches the final soil/rock layer end depth.
    """
    errors = []
    prompt = (
        "Identify the total termination depth of the borehole log shown in these images. "
        "The termination depth is usually explicitly written at the bottom-left corner of the page, "
        "or in the bottom title block section, or as a final remark (e.g., 'Termination Depth: 10.50m', "
        "'End of Hole at 15.0m', or 'EOB 12.0m'). "
        "Return ONLY the numeric value in meters (e.g., 10.50) or 'None' if it is not explicitly written. "
        "Do not include units, explanation, or extra characters."
    )
    try:
        response = model.generate_content(images + [prompt])
        text = response.text.strip() if response and response.text else ""
        # Search for a float pattern
        match = re.search(r"(\d+\.\d+|\d+)", text)
        if match:
            term_depth = float(match.group(1))
            if abs(term_depth - last_end_depth) > 0.01:
                errors.append(
                    f"Termination depth mismatch: The log page indicates a termination depth of {term_depth:.2f} m, "
                    f"but the final extracted geological layer ends at {last_end_depth:.2f} m."
                )
        else:
            # If the model explicitly returned 'None' or no numeric value, we don't raise an error
            pass
    except Exception as e:
        print(f"    [Warning] Failed to query termination depth for validation: {e}")
        
    return errors


def check_title_block_consistency(model: genai.GenerativeModel, images: list) -> list[str]:
    """
    Verifies that details in the title blocks match across all sheets of a single borehole.
    """
    errors = []
    prompt = (
        "Extract the following title block information from each page in these images: "
        "Hole No, Project Name, Project Number, and Date. "
        "Return the result strictly as a raw JSON list of objects, one for each page, with the exact keys: "
        "\"page_number\", \"hole_no\", \"project_name\", \"project_number\", \"date\". "
        "Do not wrap the JSON in markdown code blocks. Provide raw JSON text only."
    )
    try:
        response = model.generate_content(images + [prompt])
        text = response.text.strip() if response and response.text else ""
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
            
        data = json.loads(text)
        if len(data) > 1:
            first_page = data[0]
            # We strictly check 'hole_no', 'project_name', and 'project_number'
            fields_to_check = [
                ("hole_no", "Hole Number"),
                ("project_name", "Project Name"),
                ("project_number", "Project Number")
            ]
            for key, label in fields_to_check:
                val1 = str(first_page.get(key, '')).strip().lower()
                for idx, page_data in enumerate(data[1:], start=2):
                    val2 = str(page_data.get(key, '')).strip().lower()
                    # Skip check if one of the values is empty or unclear to prevent false positives
                    if not val1 or not val2 or val1 in ["unknown", "n/a", "none"] or val2 in ["unknown", "n/a", "none"]:
                        continue
                    if val1 != val2:
                        errors.append(
                            f"Title block mismatch: {label} differs between Page 1 ('{first_page.get(key)}') "
                            f"and Page {idx} ('{page_data.get(key)}')."
                        )
    except Exception as e:
        print(f"    [Warning] Failed to verify title block consistency: {e}")
        
    return errors


def request_gemini_correction(
    model: genai.GenerativeModel,
    images: list,
    borehole_name: str,
    original_csv: str,
    errors: list[str]
) -> str:
    """
    Sends the validation errors and original CSV back to Gemini to request a corrected extraction.
    """
    errors_str = "\n".join([f"- {err}" for err in errors])
    prompt = (
        f"We extracted the following stratigraphy CSV for borehole '{borehole_name}':\n\n"
        f"{original_csv}\n\n"
        f"However, the following validation checks failed on this extraction:\n"
        f"{errors_str}\n\n"
        f"Please re-analyze the provided log images and correct the data extraction for borehole '{borehole_name}'. "
        f"Make sure to resolve all continuity, termination depth, and title block issues. "
        f"Provide the output strictly as raw CSV text matching the headers: "
        f"Hole No,Sheet No,Start Depth,End Depth,Soil/Rock Description,Soil/Rock Type,Confidence Level\n"
        f"Do not wrap the CSV in markdown code blocks."
    )
    contents = list(images) + [prompt]
    try:
        response = model.generate_content(contents)
        return response.text if response and response.text else ""
    except Exception as e:
        print(f"    [Error] Gemini correction request failed: {e}")
        return ""


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
