"""
Render page 2 (0-indexed page 1) of every report PDF in a directory to PNG,
using native PyMuPDF rendering (no poppler), per this project's hard rules.

The agent then reads each PNG with a vision-capable Read to transcribe the
bracketed "HOLE NOS." list — this script only handles the rendering.
"""
import argparse
import glob
import os

import fitz  # PyMuPDF


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports-dir", default="Borehole Reports")
    ap.add_argument("--page-index", type=int, default=1, help="0-indexed page number to render (default: 1 = page 2)")
    ap.add_argument("--dpi", type=int, default=250)
    ap.add_argument("--output-dir", default="scratch/page2_check")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    rendered = []
    for pdf_path in sorted(glob.glob(os.path.join(args.reports_dir, "*.pdf"))):
        doc = fitz.open(pdf_path)
        try:
            if len(doc) <= args.page_index:
                print(f"SKIP (only {len(doc)} pages): {pdf_path}")
                continue
            page = doc[args.page_index]
            pix = page.get_pixmap(dpi=args.dpi)
            name = os.path.splitext(os.path.basename(pdf_path))[0].replace(" ", "_")
            out_path = os.path.join(args.output_dir, f"{name}.png")
            pix.save(out_path)
            rendered.append(out_path)
            print(out_path)
        finally:
            doc.close()

    return rendered


if __name__ == "__main__":
    main()
