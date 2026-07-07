import gc
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from .config import DEFAULT_TESSERACT_PATH, classify_page

def configure_tesseract(tesseract_path: str = DEFAULT_TESSERACT_PATH) -> None:
    """
    Configures pytesseract's tesseract_cmd path if it exists.
    """
    import os
    if tesseract_path and os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    else:
        # We don't crash, pytesseract will try to use the system PATH
        pass


def process_page_ocr(
    pdf_path: str,
    page_num: int,
    dpi: int
) -> tuple[bool, str | None, str]:
    """
    Converts a single page of a PDF to an image natively using PyMuPDF (without Poppler)
    and performs Tesseract OCR.
    
    Args:
        pdf_path: Path to the input PDF file.
        page_num: 1-indexed page number to process.
        dpi: Dots Per Inch resolution for PDF conversion.
        
    Returns:
        tuple[bool, str|None, str]: (is_valid, hole_no_or_reason, raw_text)
    """
    img = None
    doc = None
    try:
        # Open PDF and render the specific page to a pixmap using PyMuPDF
        doc = fitz.open(pdf_path)
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        
        # Convert pixmap to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        doc = None
        
        # Run Tesseract OCR on the image
        raw_text = pytesseract.image_to_string(img)
        
        # Close the image immediately to free memory resources
        img.close()
        img = None
        
        # Classify based on the extracted text
        is_valid, detail = classify_page(raw_text)
        return is_valid, detail, raw_text
        
    except Exception as e:
        return False, f"OCR/Rendering error: {str(e)}", ""
        
    finally:
        # Explicitly clean up resources and trigger GC to avoid memory leaks
        if doc:
            try:
                doc.close()
            except Exception:
                pass
        if img:
            try:
                img.close()
            except Exception:
                pass
        gc.collect()
