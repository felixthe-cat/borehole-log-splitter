import os
import sys
import csv
import io
import re
import fitz  # PyMuPDF
from .config import sanitize_filename, CSV_HEADERS


def get_next_master_csv_path(base_path: str = "results/borehole_stratigraphy.csv") -> str:
    """
    Checks if the base master CSV path already exists. If it does,
    finds the next available versioned filename: base_path_v[N].csv.
    """
    if not os.path.exists(base_path):
        return base_path
        
    dirname = os.path.dirname(base_path)
    basename = os.path.basename(base_path)
    name, ext = os.path.splitext(basename)
    
    match = re.search(r"_v\d+$", name)
    if match:
        name = name[:match.start()]
        
    version = 1
    while True:
        candidate = os.path.join(dirname, f"{name}_v{version}{ext}")
        if not os.path.exists(candidate):
            return candidate
        version += 1


def get_next_borehole_version(hole_name: str, master_csv_path: str) -> str:
    """
    Scans the master CSV file's 'Hole No' column.
    Extracts the base name from hole_name (e.g. DH7 from DH7 or DH7_v1).
    If no records exist for that borehole in the master CSV, returns hole_name_v1.
    If records exist, returns hole_name_v[max_version + 1].
    """
    base_name = re.sub(r"_v\d+$", "", hole_name).strip()
    
    if not os.path.exists(master_csv_path) or os.path.getsize(master_csv_path) == 0:
        return f"{base_name}_v1"
        
    versions = []
    try:
        with open(master_csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter=';')
            for row in reader:
                if not row or row[0].lower().startswith("sep=") or row[0].lower() == "hole no":
                    continue
                row_hole = row[0].strip()
                if row_hole == base_name:
                    versions.append(0)
                elif row_hole.startswith(f"{base_name}_v"):
                    suffix = row_hole[len(base_name) + 2:]
                    if suffix.isdigit():
                        versions.append(int(suffix))
    except Exception as e:
        print(f"[Warning] Failed to scan master CSV for borehole versioning: {e}", file=sys.stderr)
        
    if not versions:
        return f"{base_name}_v1"
        
    next_version = max(versions) + 1
    return f"{base_name}_v{next_version}"


def get_standard_pdf_name(hole_no: str, prefix: str = None) -> str:
    """
    Generates a standardised PDF filename: [Prefix]_Borehole_[Hole_No].pdf or Borehole_[Hole_No].pdf
    """
    sanitized = sanitize_filename(hole_no)
    if prefix:
        sanitized_prefix = sanitize_filename(prefix)
        return f"{sanitized_prefix}_Borehole_{sanitized}.pdf"
    return f"Borehole_{sanitized}.pdf"


def get_standard_excel_name(hole_name: str, prefix: str = None) -> str:
    """
    Generates a standardised Excel/CSV filename: [Prefix]_Borehole_[Hole_No]_stratigraphy.csv or Borehole_[Hole_No]_stratigraphy.csv
    """
    sanitized = sanitize_filename(hole_name)
    if prefix:
        sanitized_prefix = sanitize_filename(prefix)
        return f"{sanitized_prefix}_Borehole_{sanitized}_stratigraphy.csv"
    return f"Borehole_{sanitized}_stratigraphy.csv"



def save_borehole_pdf(
    src_doc: fitz.Document,
    page_indices: list[int],
    hole_no: str,
    output_dir: str,
    overwrite: bool = True,
    prefix: str = None
) -> str | None:
    """
    Extracts the specified page indices from the source PDF and writes them
    to a separate PDF file. Overwrites the file if overwrite is True, otherwise appends.
    """
    if not page_indices:
        return None
        
    filename = get_standard_pdf_name(hole_no, prefix)
    
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
    and parses it using the standard csv.reader to handle semicolons in descriptions safely.
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
    reader = csv.reader(f_in, delimiter=';')
    
    rows = []
    for row in reader:
        if not row:
            continue
        row_cleaned = [cell.strip() for cell in row]
        
        # Skip sep=; instruction line if present
        if row_cleaned and row_cleaned[0].lower().startswith("sep="):
            continue
            
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
    headers_expected = list(CSV_HEADERS)
    
    try:
        with open(master_csv_path, mode="a", encoding="utf-8", newline="") as f_out:
            writer = csv.writer(f_out, delimiter=';')
            if not file_exists:
                f_out.write("sep=;\n")
                writer.writerow(headers_expected)
            writer.writerows(rows)
        print(f"    Added {len(rows)} record(s) to: {os.path.basename(master_csv_path)}")
    except Exception as e:
        print(f"[Error] Failed to append rows to master CSV {master_csv_path}: {e}", file=sys.stderr)
