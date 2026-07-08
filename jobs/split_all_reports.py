#!/usr/bin/env python3
"""
Batch Borehole Log Splitter
---------------------------
Author: Antigravity (AI Coding Assistant)
Description:
    Locates all PDF reports in 'Borehole Reports/', assigns unique short names,
    and runs the Phase 1 splitter using local OCR to save split logs in 'individual borehole logs/'.
"""

import os
import sys

# Add root folder to sys.path so we can import borehole_extractor_lib
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from borehole_extractor_lib import (
    configure_tesseract,
    triage_and_split_pdf,
    get_unique_report_short_names,
)
from borehole_extractor_lib.config import DEFAULT_TESSERACT_PATH

def main():
    reports_dir = "Borehole Reports"
    splits_dir = "individual borehole logs"
    dpi = 150
    
    # 1. Configure Tesseract
    configure_tesseract(DEFAULT_TESSERACT_PATH)
    
    # 2. Ensure splits directory exists
    os.makedirs(splits_dir, exist_ok=True)
    
    # 3. Get all reports and their unique short names
    if not os.path.exists(reports_dir):
        print(f"[Error] Reports directory '{reports_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    short_names_map = get_unique_report_short_names(reports_dir)
    pdf_files = [f for f in os.listdir(reports_dir) if f.lower().endswith(".pdf")]
    pdf_files.sort()
    
    if not pdf_files:
        print(f"No PDF reports found in '{reports_dir}'.")
        sys.exit(0)
        
    print("=" * 60)
    print(f"Batch Borehole Log Splitter — Found {len(pdf_files)} Report(s)")
    print("=" * 60)
    for filename in pdf_files:
        short_name = short_names_map.get(filename)
        print(f"  - {filename} -> Short Name: '{short_name}'")
    print("-" * 60)
    
    all_created_splits = []
    
    # 4. Split each report
    for idx, filename in enumerate(pdf_files, 1):
        input_pdf = os.path.join(reports_dir, filename)
        short_name = short_names_map.get(filename)
        
        print(f"\n[{idx}/{len(pdf_files)}] Splitting Report: {filename}")
        print(f"    Short Name Prefix: {short_name}")
        
        try:
            splits = triage_and_split_pdf(
                pdf_path=input_pdf,
                dpi=dpi,
                splits_dir=splits_dir,
                overwrite_splits=True,
                short_report_name=short_name
            )
            print(f"    Successfully generated {len(splits)} split(s).")
            all_created_splits.extend(splits)
        except Exception as e:
            print(f"    [Error] Failed to split report {filename}: {e}", file=sys.stderr)
            
    print("\n" + "=" * 60)
    print("Batch Splitting Execution Summary")
    print("=" * 60)
    print(f"Total Master Reports Processed: {len(pdf_files)}")
    print(f"Total Individual Split Logs:    {len(all_created_splits)}")
    print(f"Splits Directory:               {os.path.abspath(splits_dir)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
