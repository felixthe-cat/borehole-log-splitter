import os
import sys
import gc
import time
import argparse
import fitz  # PyMuPDF
from PIL import Image

# Add root folder to sys.path so we can import borehole_extractor_lib if run directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from borehole_extractor_lib import (
    configure_tesseract,
    triage_and_split_pdf,
    initialize_gemini_client,
    extract_stratigraphy_with_retry,
    clean_and_parse_csv,
    append_rows_to_master_csv,
    check_depth_continuity,
    check_termination_depth,
    check_title_block_consistency,
    request_gemini_correction,
    resolve_as_sheet_descriptions,
    merge_consecutive_identical_layers,
)


def run_pipeline(
    input_pdf: str,
    output_csv: str,
    splits_dir: str = "temp_splits",
    keep_splits: bool = False,
    tesseract_path: str = None,
    dpi: int = 150,
    gemini_key: str = None,
    extract_only: bool = False,
    hole_name: str = None,
    model_name: str = "gemini-3.5-flash"
) -> bool:
    """
    Orchestrates the entire borehole splitting, classification, and extraction pipeline.
    """
    all_validation_issues = []
    
    # 1. Validate Input File
    if not os.path.exists(input_pdf):
        print(f"[Error] Input PDF file does not exist: {input_pdf}", file=sys.stderr)
        return False
        
    # 2. Configure Tesseract Path
    if tesseract_path:
        configure_tesseract(tesseract_path)
    else:
        # Defaults configuration inside configure_tesseract
        configure_tesseract()
        
    # Ensure directories exist
    os.makedirs(splits_dir, exist_ok=True)
    
    # Setup list of splits to extract
    created_splits = []
    
    if extract_only:
        # Skip splitting phase, treat input PDF as a single pre-split log
        name = hole_name or os.path.splitext(os.path.basename(input_pdf))[0].replace("Borehole_", "")
        created_splits = [(name, os.path.abspath(input_pdf))]
        print("=" * 60)
        print("Borehole Log Direct Stratigraphy Extractor")
        print("=" * 60)
        print(f"Input PDF (Single Log): {input_pdf}")
        print(f"Borehole Name:          {name}")
        print(f"Master CSV:             {output_csv}")
        print(f"DPI Resolution:          {dpi}")
        print("-" * 60)
    else:
        # Phase 1: Local OCR & Triage
        print("=" * 60)
        print("Borehole Log Splitter & Stratigraphy Extractor Pipeline")
        print("=" * 60)
        print(f"Input PDF:        {input_pdf}")
        print(f"Master CSV:       {output_csv}")
        print(f"Splits Directory: {splits_dir}")
        print(f"Keep Splits:      {keep_splits}")
        print(f"DPI Resolution:    {dpi}")
        print("-" * 60)
        
        print("\nStarting Phase 1: Local OCR & Page Triage (The Splitter)")
        print("-" * 60)
        
        try:
            created_splits = triage_and_split_pdf(
                pdf_path=input_pdf,
                dpi=dpi,
                splits_dir=splits_dir,
                overwrite_splits=True
            )
        except Exception as e:
            print(f"[Error] Phase 1 page triage and split failed: {e}", file=sys.stderr)
            return False
            
        print("=" * 60)
        
    # Phase 2 & 3: Gemini Multimodal Extraction & CSV Parsing
    if not created_splits:
        print("No valid borehole logs were extracted. Exiting pipeline.")
        return False
        
    # Load API Key
    from dotenv import load_dotenv
    load_dotenv()
    api_key = gemini_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n[Error] Google AI Studio GEMINI_API_KEY not found in environment or .env.", file=sys.stderr)
        print("To proceed with Phase 2 (Gemini extraction):")
        print("  1. Create a '.env' file in the project root folder.")
        print("  2. Add: GEMINI_API_KEY=your_actual_key")
        print(f"Note: Split PDFs have been preserved in: {os.path.abspath(splits_dir)}")
        return False
        
    # Initialize Gemini API Client
    try:
        model = initialize_gemini_client(api_key=api_key, model_name=model_name)
    except Exception as e:
        print(f"[Error] Failed to initialize Gemini model '{model_name}': {e}", file=sys.stderr)
        return False
        
    print("\nStarting Phase 2 & 3: Gemini Multimodal Extraction & CSV Appending")
    print("-" * 60)
    
    stats_extracted = 0
    stats_failed = 0
    
    for idx, (hole, pdf_path) in enumerate(created_splits, start=1):
        print(f"\n[{idx}/{len(created_splits)}] Extracting Borehole: {hole}")
        print(f"    Source PDF: {pdf_path}")
        
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
            
        # Call Gemini model
        try:
            print(f"    Calling Gemini API ({model_name})...", end="", flush=True)
            csv_response = extract_stratigraphy_with_retry(
                model=model,
                images=images,
                borehole_name=hole,
                max_retries=5,
                initial_delay=4.0,
                backoff_factor=2.0
            )
            print(" Done.")
            
            # Clean and run geological verifications
            if csv_response:
                rows = clean_and_parse_csv(csv_response)
                rows = resolve_as_sheet_descriptions(rows)
                rows = merge_consecutive_identical_layers(rows)
                
                # Validation retry loop (up to 3 attempts)
                validation_errors = []
                validation_passed = False
                
                for v_attempt in range(1, 4):
                    if not rows:
                        break
                    print(f"    Running validation checks (Attempt {v_attempt}/3)...", end="", flush=True)
                    
                    # 1. Depth continuity check
                    errors = check_depth_continuity(rows)
                    
                    # 2. Termination depth comparison
                    try:
                        sorted_rows = sorted(rows, key=lambda x: float(x[2]))
                        last_end_depth = float(sorted_rows[-1][3])
                        term_errors = check_termination_depth(model, images, last_end_depth)
                        errors.extend(term_errors)
                    except Exception:
                        pass
                        
                    # 3. Title block details match check
                    title_errors = check_title_block_consistency(model, images)
                    errors.extend(title_errors)
                    
                    if not errors:
                        print(" PASSED.")
                        validation_passed = True
                        break
                    else:
                        print(f" FAILED with {len(errors)} issue(s):")
                        for err in errors:
                            print(f"      [Validation Error] {err}")
                        validation_errors = errors
                        
                        if v_attempt < 3:
                            print(f"    Requesting Gemini correction for borehole {hole}...", end="", flush=True)
                            import csv as csv_module
                            io_out = io.StringIO()
                            writer = csv_module.writer(io_out)
                            writer.writerows(rows)
                            current_csv_text = io_out.getvalue()
                            
                            csv_response = request_gemini_correction(
                                model=model,
                                images=images,
                                borehole_name=hole,
                                original_csv=current_csv_text,
                                errors=errors
                            )
                            print(" Done.")
                            rows = clean_and_parse_csv(csv_response)
                            rows = resolve_as_sheet_descriptions(rows)
                            rows = merge_consecutive_identical_layers(rows)
                        else:
                            print(f"    [Warning] Max correction attempts reached. Proceeding with best-effort results.")
                            
                if validation_errors and not validation_passed:
                    all_validation_issues.append((hole, validation_errors))
                    
                if rows:
                    append_rows_to_master_csv(rows, output_csv)
                    # Copy raw CSV outputs to outputs/ in the project root for raw tracing
                    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                    raw_out_dir = os.path.join(project_root, "outputs")
                    os.makedirs(raw_out_dir, exist_ok=True)
                    raw_csv_path = os.path.join(raw_out_dir, f"raw_{hole}_extraction.csv")
                    with open(raw_csv_path, "w", encoding="utf-8") as rf:
                        rf.write(csv_response if csv_response else "")
                    
                    stats_extracted += 1
                else:
                    print("    [Warning] Gemini response did not contain parseable CSV rows.")
                    stats_failed += 1
            else:
                print("    [Warning] Empty response received from Gemini.")
                stats_failed += 1
                
        except Exception as e:
            print(f"\n    [Error] Failed to extract data for borehole {hole}: {e}")
            stats_failed += 1
            
        finally:
            # Clean up PIL images
            for img in images:
                try:
                    img.close()
                except Exception:
                    pass
            del images
            gc.collect()
            
        # Clean up split PDF if temporary mode and not direct extraction
        if not extract_only and not keep_splits:
            try:
                os.remove(pdf_path)
                print(f"    Removed temporary split PDF: {pdf_path}")
            except Exception as e:
                print(f"    [Warning] Failed to delete temporary split PDF {pdf_path}: {e}")
                
        # Sleep delay to comply with API rate limit (15 RPM)
        if idx < len(created_splits):
            print("    Waiting 4 seconds to comply with rate limits...")
            time.sleep(4.0)
            
    # Clean up empty temp splits directory
    if not extract_only and not keep_splits:
        try:
            if os.path.exists(splits_dir) and not os.listdir(splits_dir):
                os.rmdir(splits_dir)
                print(f"Cleaned up empty temporary directory: {splits_dir}")
        except Exception:
            pass
            
    if all_validation_issues:
        print("\n" + "=" * 60)
        print("Geological Validation Issues Summary")
        print("=" * 60)
        for hole, issues in all_validation_issues:
            print(f"Borehole {hole}:")
            for iss in issues:
                print(f"  - {iss}")
        print("=" * 60)
        
    print("=" * 60)
    print("Pipeline Execution Completed")
    print("=" * 60)
    print(f"Total Boreholes Found:  {len(created_splits)}")
    print(f"Successfully Extracted: {stats_extracted}")
    print(f"Extraction Failed:     {stats_failed}")
    print(f"Master CSV Location:    {os.path.abspath(output_csv)}")
    print("=" * 60)
    
    return stats_failed == 0


def main():
    from borehole_extractor_lib.config import DEFAULT_TESSERACT_PATH
    
    parser = argparse.ArgumentParser(
        description="Extract and split Ground Investigation (GI) borehole logs from a scanned multipage PDF and extract geological stratigraphy using Gemini."
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to the input scanned master PDF file"
    )
    parser.add_argument(
        "--output-csv", "-o",
        default="results/borehole_stratigraphy.csv",
        help="Path to the output master CSV file (default: results/borehole_stratigraphy.csv)"
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
        help="Path to the Poppler 'bin' directory (ignored, kept for backward compatibility)"
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="DPI resolution for page rendering (default: 150)"
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
        default="gemini-3.5-flash",
        help="Gemini model name to use (default: gemini-3.5-flash)"
    )
    
    args = parser.parse_args()
    
    success = run_pipeline(
        input_pdf=args.input,
        output_csv=args.output_csv,
        splits_dir=args.splits_dir,
        keep_splits=args.keep_splits,
        tesseract_path=args.tesseract_path,
        dpi=args.dpi,
        gemini_key=args.gemini_key,
        extract_only=args.extract_only,
        hole_name=args.hole_name,
        model_name=args.model
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
