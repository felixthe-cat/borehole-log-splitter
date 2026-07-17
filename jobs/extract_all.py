import os
import sys
import csv
import re

# Add root folder to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from borehole_extractor_lib import (
    resolve_as_sheet_descriptions,
    merge_consecutive_identical_layers,
    normalize_degree_symbols,
    check_depth_continuity,
    append_rows_to_master_csv,
)

def load_raw_csv(filepath: str) -> list[list[str]]:
    """Loads and sanitizes raw CSV extractions, formatting Sheet No and depths cleanly."""
    rows = []
    if not os.path.exists(filepath):
        print(f"[Warning] File not found: {filepath}")
        return []
    with open(filepath, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            row_cleaned = [cell.strip() for cell in row]
            row_lower = [cell.lower() for cell in row_cleaned]
            # Skip headers
            if any(h in row_lower[0] for h in ["hole", "borehole"]) and any("depth" in cell for cell in row_lower):
                continue
                
            # If the CSV reader split a description containing unquoted commas,
            # reconstruct the description by joining all fields between index 4 and -2.
            if len(row_cleaned) > 7:
                desc = ", ".join(row_cleaned[4:-2])
                row_cleaned = row_cleaned[:4] + [desc] + row_cleaned[-2:]
            elif len(row_cleaned) < 7:
                row_cleaned = row_cleaned + [""] * (7 - len(row_cleaned))
                
            # Clean Hole No (remove Borehole_ prefix if present)
            row_cleaned[0] = row_cleaned[0].replace("Borehole_", "")
            
            # Clean Sheet No to avoid Excel date-parsing issues
            sheet_no = row_cleaned[1]
            if not sheet_no.isdigit():
                match = re.search(r"\d+", sheet_no)
                if match:
                    row_cleaned[1] = match.group(0)
                else:
                    row_cleaned[1] = "1"
                    
            # Clean depths to be clean floats
            for idx in [2, 3]:
                depth_val = row_cleaned[idx].lower().replace("m", "").replace(",", ".").strip()
                match = re.search(r"[-+]?\d*\.\d+|\d+", depth_val)
                if match:
                    try:
                        row_cleaned[idx] = f"{float(match.group(0)):.2f}"
                    except ValueError:
                        pass
                        
            rows.append(row_cleaned)
    return rows

def main():
    outputs_dir = "outputs"
    output_csv = "results/borehole_stratigraphy.csv"
    
    # Target original 7 boreholes as per original results/borehole_stratigraphy.csv
    target_holes = ["DH19", "DH34", "DH40", "DH42", "DH47", "DH55", "DH7"]
    
    # Check if output target is locked, delete/clear it to start fresh
    try:
        if os.path.exists(output_csv):
            os.remove(output_csv)
            print(f"Initialized clean master CSV: {output_csv}")
    except PermissionError:
        output_csv = "results/borehole_stratigraphy_v2.csv"
        print(f"[Warning] Target file results/borehole_stratigraphy.csv is locked (likely open in Excel).")
        print(f"Falling back to clean output file: {output_csv}")
        if os.path.exists(output_csv):
            try:
                os.remove(output_csv)
            except Exception:
                pass
                
    success_count = 0
    
    for hole in target_holes:
        print(f"\nProcessing {hole} offline...")
        raw_path = os.path.join(outputs_dir, f"raw_{hole}_extraction.csv")
        
        rows = load_raw_csv(raw_path)
        if not rows:
            print(f"[Error] No rows loaded for {hole}")
            continue
            
        # Run normalisation sequence
        rows = resolve_as_sheet_descriptions(rows)
        rows = merge_consecutive_identical_layers(rows)
        rows = absorb_short_no_recovery_annotations(rows)
        rows = force_fill_and_concrete_types(rows)
        rows = normalize_degree_symbols(rows)
        
        # Run validations
        errors = check_depth_continuity(rows)
        if errors:
            print(f"[Warning] Validation errors for {hole}: {errors}")
        else:
            print(f"Validation PASSED for {hole}")
            
        if rows:
            append_rows_to_master_csv(rows, output_csv)
            success_count += 1
            
    print("\n" + "=" * 60)
    print("Offline Extraction Summary")
    print(f"Successfully processed: {success_count} / {len(target_holes)}")
    print(f"Master CSV written to: {output_csv}")
    print("=" * 60)

if __name__ == "__main__":
    main()
