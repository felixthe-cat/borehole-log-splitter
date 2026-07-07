import os
import sys
import csv
import io
import fitz  # PyMuPDF
from .config import sanitize_filename


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
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
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
        
    # Ensure parent directory of master_csv_path exists
    parent_dir = os.path.dirname(master_csv_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
        
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
