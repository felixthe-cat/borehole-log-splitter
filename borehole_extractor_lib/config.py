import os
import re

# Regex patterns to locate the Borehole Number anchor.
# Matches common variants like "HOLE NO. BH-01", "BOREHOLE NO. RC-2", etc.
# Restricted whitespace matching [ \t]* to avoid matching across newlines.
HOLE_PATTERNS = [
    re.compile(r"\bHOLE\s+NO\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
    re.compile(r"\bBOREHOLE\s+NO\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
    re.compile(r"\bHOLE\s+N0\b\.?[ \t]*([A-Za-z0-9\-]+)", re.IGNORECASE),
]

# Sheet patterns to extract page sheet sequence X and Y (e.g. Sheet X of Y)
SHEET_PATTERNS = [
    re.compile(r"\bSHEET\s*NO\.?\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bPAGE\s*(\d+)\s*OF\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*NO\.?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bSHEET\s*(\d+)\b", re.IGNORECASE),
]

# Case-insensitive keywords that signify irrelevant administrative/visual pages
TRASH_KEYWORDS = [
    "CORE PHOTOGRAPH",
    "PHOTOGRAPHIC RECORD",
    "COVER",
    "PHOTO LOG",
    "PHOTOGRAPHS",
    "KEY TO SHEET",
]

# Default Tesseract installation path on Windows systems.
DEFAULT_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Keywords that detect borehole log sheets
LOG_SHEET_KEYWORDS = [
    "DRILLHOLE RECORD", 
    "BOREHOLE RECORD", 
    "BOREHOLE LOG", 
    "DRILLHOLE LOG",
    "FLUSHING MEDIUM",
    "GROUND-LEVEL",
    "PENETRATION TEST",
    "METHOD = ROTARY",
    "METHOD ROTARY",
    "ROTARY CO-ORDINATES",
    "PISTON SAMPLE",
    "AS SHEET "
]


def sanitize_filename(name: str) -> str:
    """
    Sanitizes a string to make it safe for use as a filename on Windows.
    Replaces characters like / \\ : * ? " < > | with underscores.
    """
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def is_log_sheet_text(text: str) -> bool:
    """
    Detects if the text contains clear borehole log header markers.
    """
    text_upper = text.upper()
    return any(k in text_upper for k in LOG_SHEET_KEYWORDS)


def normalize_hole_name(name: str) -> str:
    """
    Normalizes borehole identifiers to fix common OCR misreadings.
    """
    if not name:
        return ""
    name = name.upper().strip()
    name = re.sub(r"\bDH-?S{1,2}(55)?\b", "DH55", name)
    name = re.sub(r"\bDHS(5+)\b", r"DH\1", name)
    name = re.sub(r"\bDHA(\d+)\b", r"DH4\1", name)
    if name in ("OHI", "OH-I"):
        name = "DH19"
    return name


def classify_page(text: str) -> tuple[bool, str | None]:
    """
    Analyzes the OCR text of a page to determine if it should be kept or discarded.
    """
    if is_log_sheet_text(text):
        # Anchor Check: Look for the Borehole Number regex pattern
        for pattern in HOLE_PATTERNS:
            match = pattern.search(text)
            if match:
                hole_no = normalize_hole_name(match.group(1).strip())
                if hole_no:
                    return True, hole_no
        return True, "UNKNOWN"

    # Trash Filter: Check for explicit administrative or photo keywords using word boundaries
    for keyword in TRASH_KEYWORDS:
        pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
        if pattern.search(text):
            return False, f"Trash keyword detected: '{keyword}'"
            
    # Fallback check
    for pattern in HOLE_PATTERNS:
        match = pattern.search(text)
        if match:
            hole_no = normalize_hole_name(match.group(1).strip())
            if hole_no:
                return True, hole_no
                
    return False, "Borehole anchor ('HOLE NO.') not found"
