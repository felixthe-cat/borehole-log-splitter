#!/usr/bin/env python3
import os
import sys
import gc
import time
import json
import fitz  # PyMuPDF
from PIL import Image
from dotenv import load_dotenv

# Add root folder to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from borehole_extractor_lib import (
    initialize_gemini_client,
    extract_stratigraphy_with_retry,
    DailyQuotaExhaustedError,
    clean_and_parse_csv,
    append_rows_to_master_csv,
    check_depth_continuity,
    check_termination_depth,
    check_title_block_consistency,
    check_description_and_classification,
    request_gemini_correction,
    resolve_as_sheet_descriptions,
    merge_consecutive_identical_layers,
    normalize_degree_symbols,
    get_next_master_csv_path,
    get_next_borehole_version,
    get_standard_excel_name,
    verify_pdf_filename,
    verify_excel_filename,
)

def parse_split_pdf_filename(filename: str):
    basename = os.path.basename(filename)
    name, ext = os.path.splitext(basename)
    if "_Borehole_" in name:
        prefix, hole = name.split("_Borehole_", 1)
        return hole, prefix
    else:
        hole = name.replace("Borehole_", "")
        return hole, None

def main():
    # Fix console encoding on Windows to prevent UnicodeEncodeError
    if sys.platform.startswith('win'):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    splits_dir = "individual borehole logs"
    outputs_dir = "outputs"
    results_dir = "results"
    progress_file = os.path.join(outputs_dir, "extraction_progress.json")
    
    os.makedirs(outputs_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)
    
    # 1. Scan individual borehole logs/ for split PDFs
    if not os.path.exists(splits_dir):
        print(f"[Error] Split logs directory '{splits_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    pdf_files = [f for f in os.listdir(splits_dir) if f.lower().endswith(".pdf")]
    pdf_files.sort()
    
    if not pdf_files:
        print(f"No split PDF logs found in '{splits_dir}'.")
        sys.exit(0)
        
    # Load env API key
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[Error] GEMINI_API_KEY not found in environment or .env file.", file=sys.stderr)
        sys.exit(1)
        
    # 2. Check for existing progress file
    progress = {}
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                progress = json.load(f)
            print(f"Loaded existing progress from {progress_file}")
        except Exception as e:
            print(f"[Warning] Failed to load progress file: {e}. Starting fresh.")
            
    master_csv_path = progress.get("master_csv_path")
    if not master_csv_path:
        # Determine unique master CSV path (does not overwrite existing)
        master_csv_path = get_next_master_csv_path("results/borehole_stratigraphy.csv")
        progress["master_csv_path"] = master_csv_path
        progress["completed_files"] = {}
        
    completed_files = progress.setdefault("completed_files", {})
    
    print("=" * 60)
    print("Batch Borehole Log Gemini Extractor")
    print("=" * 60)
    print(f"Total PDFs found:     {len(pdf_files)}")
    print(f"Already completed:    {len(completed_files)}")
    print(f"Writing output to:    {master_csv_path}")
    print("=" * 60)
    
    fallback_chain = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-flash-lite"]
    dpi = 150
    
    success_count = 0
    failed_count = 0
    skipped_count = len(completed_files)
    
    for idx, filename in enumerate(pdf_files, 1):
        if filename in completed_files:
            continue
            
        pdf_path = os.path.join(splits_dir, filename)
        hole, prefix = parse_split_pdf_filename(filename)
        
        print(f"\n[{idx}/{len(pdf_files)}] Processing: {filename}")
        print(f"    Hole: {hole}, Prefix: {prefix}")
        
        # Verify split PDF name format
        if not verify_pdf_filename(filename):
            print(f"    [Warning] PDF filename does not match standardized format: {filename}")
            
        # Render split PDF pages to PIL images natively
        images = []
        doc = None
        try:
            doc = fitz.open(pdf_path)
            for page in doc:
                pix = page.get_pixmap(dpi=dpi)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
            doc.close()
            doc = None
        except Exception as e:
            if doc:
                try:
                    doc.close()
                except Exception:
                    pass
            print(f"    [Error] Failed to render images: {e}")
            failed_count += 1
            continue
            
        if not images:
            print("    [Error] No pages rendered from split PDF.")
            failed_count += 1
            continue
            
        # Attempt extraction using fallback chain
        current_model_idx = 0
        success = False
        
        while current_model_idx < len(fallback_chain):
            active_model_name = fallback_chain[current_model_idx]
            try:
                print(f"    Calling Gemini API ({active_model_name})...", end="", flush=True)
                model = initialize_gemini_client(api_key=api_key, model_name=active_model_name)
                
                # Extract
                extraction_data = extract_stratigraphy_with_retry(
                    model=model,
                    images=images,
                    borehole_name=hole,
                    max_retries=3,
                    initial_delay=4.0,
                    backoff_factor=2.0
                )
                print(" Done.")
                
                if not extraction_data:
                    print("    [Warning] Gemini response was empty.")
                    current_model_idx += 1
                    continue
                    
                csv_text = extraction_data.get("stratigraphy_csv", "")
                term_depth = float(extraction_data.get("termination_depth", 0.0))
                title_blocks = extraction_data.get("title_blocks", [])
                
                # Parse and normalise
                rows = clean_and_parse_csv(csv_text)
                rows = resolve_as_sheet_descriptions(rows)
                rows = merge_consecutive_identical_layers(rows)
                rows = normalize_degree_symbols(rows)
                
                # Validation retry loop
                validation_passed = False
                for v_attempt in range(1, 4):
                    if not rows:
                        break
                    print(f"    Running validations (Attempt {v_attempt}/3)...", end="", flush=True)
                    
                    errors = check_depth_continuity(rows)
                    
                    try:
                        sorted_rows = sorted(rows, key=lambda x: float(x[2]))
                        last_end_depth = float(sorted_rows[-1][3])
                        term_errors = check_termination_depth(term_depth, last_end_depth)
                        errors.extend(term_errors)
                    except Exception as te:
                        print(f"      [Warning] Termination depth comparison error: {te}")
                        
                    title_errors = check_title_block_consistency(title_blocks)
                    errors.extend(title_errors)
                    
                    desc_errors = check_description_and_classification(rows)
                    errors.extend(desc_errors)
                    
                    if not errors:
                        print(" PASSED.")
                        validation_passed = True
                        break
                    else:
                        print(f" FAILED with {len(errors)} issues:")
                        for err in errors:
                            print(f"      - {err}")
                        
                        if v_attempt < 3:
                            print("    Requesting correction from Gemini...", end="", flush=True)
                            original_json_str = json.dumps(extraction_data, indent=2)
                            extraction_data = request_gemini_correction(
                                model=model,
                                images=images,
                                borehole_name=hole,
                                original_json_str=original_json_str,
                                errors=errors
                            )
                            print(" Done.")
                            csv_text = extraction_data.get("stratigraphy_csv", "")
                            term_depth = float(extraction_data.get("termination_depth", 0.0))
                            title_blocks = extraction_data.get("title_blocks", [])
                            rows = clean_and_parse_csv(csv_text)
                            rows = resolve_as_sheet_descriptions(rows)
                            rows = merge_consecutive_identical_layers(rows)
                            rows = normalize_degree_symbols(rows)
                        else:
                            print("    [Warning] Max correction attempts reached. Saving best-effort result.")
                            
                if rows:
                    # Version the borehole name column values to prevent overwriting/colliding in master CSV
                    versioned_hole = get_next_borehole_version(hole, master_csv_path)
                    for r in rows:
                        r[0] = versioned_hole
                        
                    # Save raw CSV log in outputs/
                    raw_filename = get_standard_excel_name(versioned_hole, prefix)
                    
                    # Verify individual Excel filename matches standard naming convention
                    if not verify_excel_filename(raw_filename):
                        print(f"    [Warning] Output filename does not match standardized format: {raw_filename}")
                        
                    raw_csv_path = os.path.join(outputs_dir, raw_filename)
                    with open(raw_csv_path, "w", encoding="utf-8") as rf:
                        rf.write("sep=;\n")
                        rf.write("Hole No;Sheet No;Start Depth;End Depth;Soil/Rock Description;Soil/Rock Type;Confidence Level\n")
                        for r in rows:
                            rf.write(";".join(r) + "\n")
                    print(f"    Saved individual log to {raw_csv_path}")
                    
                    # Append to master CSV
                    append_rows_to_master_csv(rows, master_csv_path)
                    success = True
                    break
                else:
                    print("    [Warning] No parseable rows extracted.")
                    current_model_idx += 1
                    
            except DailyQuotaExhaustedError:
                print(f" Quota exhausted for model {active_model_name}.")
                current_model_idx += 1
                if current_model_idx < len(fallback_chain):
                    print(f"    Falling back to model: {fallback_chain[current_model_idx]}...")
            except Exception as e:
                print(f" Failed: {e}")
                current_model_idx += 1
                
        # Clean up images
        for img in images:
            try:
                img.close()
            except Exception:
                pass
        del images
        gc.collect()
        
        if success:
            success_count += 1
            completed_files[filename] = True
            # Write progress checkpoint
            try:
                with open(progress_file, "w", encoding="utf-8") as f:
                    json.dump(progress, f, indent=2)
            except Exception as pe:
                print(f"    [Warning] Failed to write progress file: {pe}")
        else:
            print(f"    [Error] Failed to process {filename} after trying all fallback models.")
            failed_count += 1
            # We exit cleanly on permanent connection errors or if all models failed,
            # letting the user know they can resume.
            print("\n" + "=" * 60)
            print("Batch run interrupted. Progress saved.")
            print("Please check your internet connection or API quota limits.")
            print("You can resume by running this script again.")
            print("=" * 60)
            sys.exit(1)
            
        # Comply with rate limits (15 RPM -> ~4 seconds delay)
        if idx < len(pdf_files):
            print("    Waiting 4 seconds...")
            time.sleep(4.0)
            
    print("\n" + "=" * 60)
    print("Batch Extraction Completed Successfully!")
    print("=" * 60)
    print(f"Total PDFs:       {len(pdf_files)}")
    print(f"Skipped (Done):   {skipped_count}")
    print(f"Newly Processed:  {success_count}")
    print(f"Failed:           {failed_count}")
    print(f"Master CSV:       {master_csv_path}")
    print("=" * 60)

if __name__ == "__main__":
    main()
