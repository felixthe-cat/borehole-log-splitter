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


# ---------------------------------------------------------------------------
# Canonical output CSV schema (single source of truth).
#
# The Gemini model emits the MODEL_CSV_HEADERS subset (the per-layer data it can
# read off a sheet). Easting/Northing are NOT emitted per row by the model — they
# are injected post-parse from the validated title blocks, because the coordinates
# live in the sheet header and must be identical on every sheet of one borehole.
# ---------------------------------------------------------------------------
CSV_HEADERS = [
    "Hole No",
    "Easting",
    "Northing",
    "Sheet No",
    "Start Depth",
    "End Depth",
    "Grade",
    "Soil/Rock Description",
    "Soil/Rock Type",
    "Confidence Level",
]
NUM_COLS = len(CSV_HEADERS)  # 10

# Column indices into a full output row (use these instead of magic numbers).
(
    COL_HOLE,
    COL_EASTING,
    COL_NORTHING,
    COL_SHEET,
    COL_START,
    COL_END,
    COL_GRADE,
    COL_DESC,
    COL_TYPE,
    COL_CONF,
) = range(NUM_COLS)

# The columns the model is asked to emit directly (coordinates excluded — injected).
MODEL_CSV_HEADERS = [
    "Hole No",
    "Sheet No",
    "Start Depth",
    "End Depth",
    "Grade",
    "Soil/Rock Description",
    "Soil/Rock Type",
    "Confidence Level",
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
    # Replace DHS55 with DH55, but keep DHS as is (will be corrected by sequence checks)
    name = re.sub(r"\bDH-?S55\b", "DH55", name)
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


def get_unique_report_short_names(directory: str) -> dict[str, str]:
    """
    Scans the directory for PDF files and returns a dictionary mapping
    each filename to a unique short name.
    """
    if not directory or not os.path.exists(directory):
        return {}
        
    pdf_files = [f for f in os.listdir(directory) if f.lower().endswith(".pdf")]
    
    # 1. Generate tentative short names
    mapping = {}
    for filename in pdf_files:
        # Match MonthYear patterns like Jun1996 or Jun96
        match = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\d{2,4}\b", filename, re.IGNORECASE)
        if match:
            # Normalize to Title Case (e.g. Jun1996)
            raw_match = match.group(0)
            month = match.group(1).title()
            year = re.search(r"\d{2,4}", raw_match).group(0)
            candidate = f"{month}{year}"
        else:
            # Match any 4 digit year
            match_year = re.search(r"\b(19\d{2}|20\d{2})\b", filename)
            if match_year:
                candidate = match_year.group(0)
            else:
                # Fallback to sanitized first few words/chars
                base = os.path.splitext(filename)[0]
                sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_")
                candidate = sanitized[:15]
        mapping[filename] = candidate
        
    # 2. Check for duplicates and disambiguate
    from collections import Counter
    counts = Counter(mapping.values())
    
    # For any duplicate candidates, append a number
    seen = {}
    final_mapping = {}
    for filename in pdf_files:
        candidate = mapping[filename]
        if counts[candidate] > 1:
            if candidate not in seen:
                seen[candidate] = 1
                final_mapping[filename] = candidate
            else:
                seen[candidate] += 1
                final_mapping[filename] = f"{candidate}_{seen[candidate]}"
        else:
            final_mapping[filename] = candidate
            
    return final_mapping


def parse_name_to_tuple(name: str) -> tuple[str, int, str] | None:
    """
    Parses a borehole name (e.g. B2A, DH51, a1a, CS) into a tuple of (prefix, numeric_value, suffix).
    """
    if not name:
        return None
    name = name.upper().strip()
    clean = name.replace(" ", "").replace("-", "")
    if not clean:
        return None
        
    OCR_MAP = {
        'S': '5', 'I': '1', 'L': '1', 'E': '5', 'O': '0', 'B': '8', 'G': '6', 'A': '4', 'Z': '2', 'T': '7'
    }
    def is_numeric_char(c):
        return c.isdigit() or c in OCR_MAP
        
    prefix = ""
    suffix = ""
    
    # 1. Parse prefix
    if len(clean) >= 3 and clean[0].isalpha() and clean[1].isalpha() and clean[1] not in OCR_MAP and is_numeric_char(clean[2]):
        prefix = clean[:2]
        rest = clean[2:]
    elif len(clean) >= 2 and clean[0].isalpha() and is_numeric_char(clean[1]):
        prefix = clean[0]
        rest = clean[1:]
    else:
        prefix = ""
        rest = clean
        
    # 2. Parse suffix
    if len(rest) >= 2 and rest[-1].isalpha() and is_numeric_char(rest[-2]):
        suffix = rest[-1]
        rest = rest[:-1]
    elif len(rest) == 1 and rest.isalpha():
        suffix = rest
        rest = ""
    else:
        suffix = ""
        
    # 3. Parse core_str
    digits = []
    for char in rest:
        if char.isdigit():
            digits.append(char)
        elif char in OCR_MAP:
            digits.append(OCR_MAP[char])
        else:
            return None
            
    num_val = int("".join(digits)) if digits else 0
    return (prefix, num_val, suffix)


def longest_increasing_subsequence(arr: list[int | None]) -> list[int]:
    """
    Returns the indices of elements forming the longest increasing subsequence.
    Treats None as invalid/skipped elements.
    """
    n = len(arr)
    if n == 0:
        return []
        
    dp = [0] * n
    parent = [-1] * n
    
    for i in range(n):
        if arr[i] is None:
            continue
        dp[i] = 1
        for j in range(i):
            if arr[j] is not None and arr[j] < arr[i]:
                if dp[j] + 1 > dp[i]:
                    dp[i] = dp[j] + 1
                    parent[i] = j
                    
    max_len = 0
    best_idx = -1
    for i in range(n):
        if dp[i] > max_len:
            max_len = dp[i]
            best_idx = i
            
    lis_indices = []
    curr = best_idx
    while curr != -1:
        lis_indices.append(curr)
        curr = parent[curr]
        
    lis_indices.reverse()
    return lis_indices


def group_blocks_by_prefix(blocks: list[dict]) -> list[tuple[str, list[int]]]:
    """
    Groups contiguous blocks sharing the same prefix (with forward and backward fill for None).
    """
    n = len(blocks)
    prefixes = [None] * n
    for i, b in enumerate(blocks):
        if b["voted_raw"]:
            t = parse_name_to_tuple(b["voted_raw"])
            if t:
                prefixes[i] = t[0]
                
    for i in range(n):
        if prefixes[i] is None:
            left_p = None
            for j in range(i - 1, -1, -1):
                if prefixes[j] is not None:
                    left_p = prefixes[j]
                    break
            right_p = None
            for j in range(i + 1, n):
                if prefixes[j] is not None:
                    right_p = prefixes[j]
                    break
            if left_p == right_p and left_p is not None:
                prefixes[i] = left_p
            elif left_p is not None:
                prefixes[i] = left_p
            elif right_p is not None:
                prefixes[i] = right_p
            else:
                prefixes[i] = ""
                
    groups = []
    if n == 0:
        return groups
        
    current_prefix = prefixes[0]
    current_indices = [0]
    for i in range(1, n):
        if prefixes[i] == current_prefix:
            current_indices.append(i)
        else:
            groups.append((current_prefix, current_indices))
            current_prefix = prefixes[i]
            current_indices = [i]
    groups.append((current_prefix, current_indices))
    return groups


def smooth_borehole_sequence(blocks: list[dict], dominant_prefix: str) -> None:
    """
    Enforces strictly increasing borehole number sequence across blocks.
    Supports prefixes, letter-based suffixes (e.g. a1a, B2A), and groups by prefix.
    """
    groups = group_blocks_by_prefix(blocks)
    
    for prefix, indices in groups:
        if len(indices) <= 1:
            for idx in indices:
                blocks[idx]["corrected_name"] = blocks[idx]["voted_raw"]
            continue
            
        arr = []
        for idx in indices:
            b = blocks[idx]
            t = parse_name_to_tuple(b["voted_raw"]) if b["voted_raw"] else None
            if t and t[0] == prefix:
                suffix_val = ord(t[2]) - ord('A') + 1 if t[2] else 0
                rank = t[1] * 100 + suffix_val
                arr.append(rank)
            else:
                arr.append(None)
                
        lis_sub_indices = longest_increasing_subsequence(arr)
        lis_global_indices = [indices[i] for i in lis_sub_indices]
        lis_set = set(lis_global_indices)
        
        for i_seq, idx in enumerate(indices):
            if idx in lis_set:
                val = arr[i_seq]
                num_val = val // 100
                suffix_val = val % 100
                suffix_char = chr(suffix_val + ord('A') - 1) if suffix_val > 0 else ""
                blocks[idx]["corrected_name"] = f"{prefix}{num_val}{suffix_char}"
                continue
                
            left_seq_idx = -1
            for j in range(i_seq - 1, -1, -1):
                if indices[j] in lis_set:
                    left_seq_idx = j
                    break
                    
            right_seq_idx = -1
            for j in range(i_seq + 1, len(indices)):
                if indices[j] in lis_set:
                    right_seq_idx = j
                    break
                    
            corrected_rank = None
            step_size = None
            if left_seq_idx != -1 and right_seq_idx != -1:
                steps = right_seq_idx - left_seq_idx
                val_diff = arr[right_seq_idx] - arr[left_seq_idx]
                if val_diff == steps:
                    step_size = 1
                elif val_diff == steps * 100:
                    step_size = 100
                elif val_diff > 0 and val_diff % steps == 0:
                    step_size = val_diff // steps
                    
                if step_size is not None:
                    corrected_rank = arr[left_seq_idx] + (i_seq - left_seq_idx) * step_size
            elif left_seq_idx != -1:
                step_size = 1 if arr[left_seq_idx] % 100 != 0 else 100
                corrected_rank = arr[left_seq_idx] + (i_seq - left_seq_idx) * step_size
            elif right_seq_idx != -1:
                step_size = 1 if arr[right_seq_idx] % 100 != 0 else 100
                corrected_rank = arr[right_seq_idx] - (right_seq_idx - i_seq) * step_size
                
            if corrected_rank is not None and corrected_rank > 0:
                num_val = corrected_rank // 100
                suffix_val = corrected_rank % 100
                suffix_char = chr(suffix_val + ord('A') - 1) if suffix_val > 0 else ""
                blocks[idx]["corrected_name"] = f"{prefix}{num_val}{suffix_char}"
                print(f"--> Corrected sequence name: '{blocks[idx]['voted_raw']}' -> '{blocks[idx]['corrected_name']}'")
            else:
                raw_t = parse_name_to_tuple(blocks[idx]["voted_raw"]) if blocks[idx]["voted_raw"] else None
                if raw_t:
                    suffix_char = raw_t[2]
                    blocks[idx]["corrected_name"] = f"{prefix}{raw_t[1]}{suffix_char}"
                else:
                    blocks[idx]["corrected_name"] = blocks[idx]["voted_raw"]


def clean_ocr_name(name: str) -> str:
    """
    Cleans OCR-read cover list names to resolve specific character reading errors.
    """
    name = name.strip().upper()
    name = re.sub(r"[^A-Z0-9\-]", "", name)
    if name == "BOB":
        return "B6B"
    if name == "C6A":
        return "C6A"
        
    # If name contains "DH" followed by digits, extract it (handles noise like Poe DH42)
    dh_match = re.search(r"DH\d+", name)
    if dh_match:
        return dh_match.group(0)
        
    if name == "DHS5":
        return "DH5"
    if name == "DHS1":
        return "DH51"
    name = re.sub(r"^DHS([0-9])", r"DH5\1", name)
    if name == "DHS":
        return "DH5"
    return name


def expand_cover_list(text: str) -> list[str]:
    """
    Extracts and expands parenthesized list of expected boreholes from cover text.
    """
    match = re.search(r"\((HOLE\s+NOS\..*?)\)", text, re.DOTALL | re.IGNORECASE)
    if not match:
        match = re.search(r"\((.*?HOLE.*?)\)", text, re.DOTALL | re.IGNORECASE)
        if not match:
            return []
            
    content = match.group(1)
    content = re.sub(r"^.*?HOLE\s+NOS\.\s*", "", content, flags=re.IGNORECASE).strip()
    content = re.sub(r"^.*?HOLE\s+NO\s*", "", content, flags=re.IGNORECASE).strip()
    
    parts = re.split(r",\s*,|,\s*|&\s*|\band\b", content, flags=re.IGNORECASE)
    
    results = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        
        p_clean = p.replace(" ", "")
        if "-" in p_clean:
            range_match = re.match(r"^([A-Z0-9]+)\-([A-Z0-9]+)$", p_clean, re.IGNORECASE)
            if range_match:
                start = clean_ocr_name(range_match.group(1))
                end = clean_ocr_name(range_match.group(2))
                
                # 1. Expand letters (e.g. B2a-B2c)
                letter_range = re.match(r"^([A-Z]+\d+)([A-Z])\-([A-Z]+\d+)([A-Z])$", p_clean, re.IGNORECASE)
                if letter_range:
                    base_start = letter_range.group(1).upper()
                    char_start = letter_range.group(2).upper()
                    char_end = letter_range.group(4).upper()
                    for c in range(ord(char_start), ord(char_end) + 1):
                        results.append(f"{base_start}{chr(c)}")
                    continue
                    
                # 2. Expand numbers (e.g. DH53-DH60)
                num_start_match = re.search(r"\d+", start)
                num_end_match = re.search(r"\d+", end)
                if num_start_match and num_end_match:
                    num_start = int(num_start_match.group(0))
                    num_end = int(num_end_match.group(0))
                    prefix = start[:num_start_match.start()]
                    for n in range(num_start, num_end + 1):
                        results.append(f"{prefix}{n}")
                    continue
            
        cleaned = clean_ocr_name(p)
        if cleaned:
            results.append(cleaned)
            
    return results


def name_similarity(a: str, b: str) -> float:
    """
    Computes heuristic similarity score between two borehole names.
    """
    if not a or a == "UNKNOWN" or not b:
        return 0.1
    t_a = parse_name_to_tuple(a)
    t_b = parse_name_to_tuple(b)
    if not t_a or not t_b:
        return 0.1
    p_a, n_a, s_a = t_a
    p_b, n_b, s_b = t_b
    
    score = 0.0
    p_a_first = p_a[0] if p_a else ""
    p_b_first = p_b[0] if p_b else ""
    if p_a_first == p_b_first and p_a_first != "":
        score += 2.0
    if p_a == p_b and p_a != "":
        score += 2.0
    if n_a == n_b and n_a != 0:
        score += 5.0
    elif n_a != 0 and n_b != 0 and (str(n_a) in str(n_b) or str(n_b) in str(n_a)):
        score += 1.0
    if s_a == s_b and s_a != "":
        score += 1.0
    return score


def align_sequences(A: list[str | None], B: list[str]) -> list[str]:
    """
    Aligns sequence of blocks A with expected list B using Dynamic Programming.
    Allows blocks to match expected elements or be skipped (match nothing).
    """
    m = len(A)
    n = len(B)
    if m == 0 or n == 0:
        return [x or "" for x in A]
        
    dp = [[-1.0] * n for _ in range(m)]
    parent = [[(-1, -1)] * n for _ in range(m)]
    
    for j in range(n):
        dp[0][j] = name_similarity(A[0], B[j])
        
    for i in range(1, m):
        for j in range(n):
            best_prev = -1.0
            best_k = -1
            for k in range(j):
                if dp[i-1][k] > best_prev:
                    best_prev = dp[i-1][k]
                    best_k = k
            
            score_match = -1.0
            if best_prev >= 0.0:
                score_match = name_similarity(A[i], B[j]) + best_prev
            elif j == 0 or best_k == -1:
                score_match = name_similarity(A[i], B[j])
                
            score_skip = dp[i-1][j]
            
            if score_match >= score_skip:
                dp[i][j] = score_match
                parent[i][j] = (i - 1, best_k)
            else:
                dp[i][j] = score_skip
                parent[i][j] = (i - 1, j)
                
    best_score = -1.0
    best_j = -1
    for j in range(n):
        if dp[m-1][j] > best_score:
            best_score = dp[m-1][j]
            best_j = j
            
    if best_j == -1:
        return [x or "" for x in A]
        
    corrected = [None] * m
    curr_i = m - 1
    curr_j = best_j
    while curr_i >= 0:
        prev_i, prev_j = parent[curr_i][curr_j]
        if prev_j == curr_j:
            corrected[curr_i] = ""
        else:
            corrected[curr_i] = B[curr_j]
        curr_i, curr_j = prev_i, prev_j
        
    return [c if c is not None else (raw or "") for c, raw in zip(corrected, A)]


