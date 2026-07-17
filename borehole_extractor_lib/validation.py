import os
import re
import json
import csv
import io
from collections import Counter
import google.generativeai as genai

from .config import (
    NUM_COLS,
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
)

# Soil/Rock Type values that are NOT in-situ rock and therefore carry no weathering grade.
# Includes transported/colluvial deposits (gravel, sand, clay, silt, cobbles, boulders) whose
# descriptions often mention "moderately decomposed granite" etc. to describe the source rock
# of individual clasts -- that wording does not mean the layer itself is a graded rock mass.
NON_ROCK_TYPES = {
    "", "fill", "no recovery", "wash boring", "alluvium",
    "marine deposit", "concrete", "boulder", "topsoil",
    "gravel", "sand", "clay", "silt", "cobbles", "boulders", "colluvium",
}

# Decomposition wording -> weathering grade (BS5930 / GEO six-grade scale).
_ADJ_GRADE = {
    "fresh": "I",
    "slightly": "II",
    "moderately": "III",
    "highly": "IV",
    "completely": "V",
}
_GRADE_RE = re.compile(
    r"\b(fresh|slightly|moderately|highly|completely)(?:\s+to\s+(fresh|slightly|moderately|highly|completely))?\s+decomposed\b",
    re.IGNORECASE,
)
_RESIDUAL_RE = re.compile(r"\bresidual\s+soil\b", re.IGNORECASE)


def check_depth_continuity(rows: list[list[str]]) -> list[str]:
    """
    Checks that:
    1. Every row has exactly NUM_COLS fields.
    2. Sheet No is a single integer number (preventing Excel date-parsing like '1-3').
    3. Start depth is strictly less than end depth for each layer.
    4. Depth ranges are of increasing depth and do not repeat or overlap.
    5. The ending depth of the Nth layer is the same as the starting depth of the N+1th layer (continuous).
    """
    errors = []
    parsed_rows = []

    for idx, r in enumerate(rows):
        if len(r) != NUM_COLS:
            errors.append(f"Row {idx+1}: Invalid column count ({len(r)} columns, expected {NUM_COLS} columns separated by semicolons). Row data: {r}")
            continue

        sheet_no_str = r[COL_SHEET].strip()
        if not sheet_no_str.isdigit():
            errors.append(f"Row {idx+1}: Sheet No '{sheet_no_str}' is not a valid integer. Ranges (like '1-3') or text are not allowed.")
            continue

        try:
            start = float(r[COL_START])
            end = float(r[COL_END])

            if start >= end:
                errors.append(f"Row {idx+1}: Invalid depth range ({start:.2f} m to {end:.2f} m). Start depth must be less than end depth.")

            parsed_rows.append((start, end, idx, r))
        except ValueError:
            errors.append(f"Row {idx+1}: Non-numeric depth range '{r[COL_START]}' to '{r[COL_END]}'")

    if errors:
        return errors

    # Sort by start depth
    parsed_rows.sort(key=lambda x: x[0])

    # Check for duplicates, overlaps, and continuity (gaps)
    for i in range(len(parsed_rows) - 1):
        curr_start = parsed_rows[i][0]
        curr_end = parsed_rows[i][1]
        next_start = parsed_rows[i+1][0]
        next_end = parsed_rows[i+1][1]

        # Check for duplicates
        if abs(curr_start - next_start) < 0.005 and abs(curr_end - next_end) < 0.005:
            errors.append(
                f"Duplicate depth range detected: Multiple rows define depth range {curr_start:.2f} m to {curr_end:.2f} m."
            )
            continue

        # Check for overlaps
        if next_start < curr_end - 0.005:
            errors.append(
                f"Depth overlap detected: Layer {i+1} ({curr_start:.2f} - {curr_end:.2f} m) "
                f"overlaps with Layer {i+2} ({next_start:.2f} - {next_end:.2f} m)."
            )
            continue

        # Check for gaps (continuity)
        if next_start > curr_end + 0.005:
            errors.append(
                f"Depth gap detected: Layer ends at {curr_end:.2f} m but the next layer starts at {next_start:.2f} m."
            )

    return errors


_NO_RECOVERY_RANGE_RE = re.compile(
    r"no\s+recovery\s*(?:at)?\s*(\d+\.?\d*)\s*m?\s*-\s*(\d+\.?\d*)\s*m",
    re.IGNORECASE,
)


def check_no_recovery_description_consistency(rows: list[list[str]]) -> list[str]:
    """
    Catches a specific model failure mode: a 'Wash boring. No recovery at Xm-Ym.'
    description states the correct full no-recovery span (verified against source
    logs), but the row's own numeric Start/End Depth columns are sometimes truncated
    short of that span -- silently letting the next layer's start depth encroach into
    what should still be no-recovery ground. When the two disagree, the description's
    stated range is the trustworthy one, so this is a blocking error (triggers the
    Gemini correction retry), not a soft warning.

    Only applies to rows whose own Type is 'No Recovery'/'Wash Boring' -- i.e. the row
    IS the no-recovery layer. A rock layer (e.g. Granite) can legitimately mention a
    brief no-recovery footnote absorbed into its description by
    absorb_short_no_recovery_annotations(); that sub-note describes a short gap inside
    the layer, not the row's own bounds, and must not be flagged here.
    """
    errors = []
    for idx, r in enumerate(rows):
        if len(r) <= COL_TYPE:
            continue
        if r[COL_TYPE].strip().lower() not in ("no recovery", "wash boring"):
            continue
        m = _NO_RECOVERY_RANGE_RE.search(r[COL_DESC])
        if not m:
            continue
        desc_start, desc_end = float(m.group(1)), float(m.group(2))
        try:
            col_start, col_end = float(r[COL_START]), float(r[COL_END])
        except (ValueError, IndexError):
            continue
        if abs(desc_start - col_start) > 0.1 or abs(desc_end - col_end) > 0.1:
            errors.append(
                f"Row {idx+1}: Description states 'no recovery at {desc_start:.2f}m-{desc_end:.2f}m' "
                f"but the row's own Start/End Depth columns say {col_start:.2f}m-{col_end:.2f}m. "
                f"The depth columns must match the no-recovery range stated in the description."
            )
    return errors


def check_termination_depth(term_depth: float, last_end_depth: float) -> list[str]:
    """
    Verifies if the total termination depth of the borehole matches the final soil/rock layer end depth.
    """
    errors = []
    if term_depth and term_depth > 0.01:
        if abs(term_depth - last_end_depth) > 0.01:
            errors.append(
                f"Termination depth mismatch: The log page indicates a termination depth of {term_depth:.2f} m, "
                f"but the final extracted geological layer ends at {last_end_depth:.2f} m."
            )
    return errors


def check_round_number_depths(rows: list[list[str]]) -> list[str]:
    """
    Soft heuristic (non-blocking): flags a depth that has only one significant decimal
    digit (e.g. '22.70') when the rest of the borehole's depths carry two decimal places.
    Real sample/layer depths in these logs are almost always irregular two-decimal values
    (e.g. 22.83, 19.30); a lone round value among them is a common signature of an OCR
    dropped-trailing-zero misread (e.g. '22.07' read as '22.7'). Callers should print these
    as warnings only -- do not add them to the blocking `errors` list or trigger a retry.
    """
    warnings = []
    depths = []
    for idx, r in enumerate(rows):
        if len(r) <= COL_END:
            continue
        for col, label in ((COL_START, "Start Depth"), (COL_END, "End Depth")):
            try:
                val = float(r[col])
            except (ValueError, IndexError):
                continue
            depths.append((idx, label, r[col], val))

    two_decimal_count = sum(1 for _, _, _, v in depths if round(v * 100) % 10 != 0)
    if len(depths) < 4 or two_decimal_count < 2:
        # Not enough two-decimal depths in this borehole to call a lone round value an outlier.
        return warnings

    for idx, label, raw, val in depths:
        if val > 0 and round(val * 100) % 10 == 0:
            warnings.append(
                f"Row {idx+1}: {label} '{raw}' has only one decimal digit while most other "
                f"depths in this borehole carry two -- possible OCR-dropped trailing zero "
                f"(e.g. '22.07' misread as '22.7'). Worth a manual check against the source sheet."
            )
    return warnings


def check_title_block_consistency(title_blocks: list) -> list[str]:
    """
    Verifies that details in the title blocks match across all sheets of a single borehole.
    """
    errors = []
    if not title_blocks or len(title_blocks) <= 1:
        return errors

    first_page = title_blocks[0]
    # We strictly check 'hole_no', 'project_name', and 'project_number'
    fields_to_check = [
        ("hole_no", "Hole Number"),
        ("project_name", "Project Name"),
        ("project_number", "Project Number")
    ]
    for key, label in fields_to_check:
        val1 = str(first_page.get(key, '')).strip().lower()
        for idx, page_data in enumerate(title_blocks[1:], start=2):
            val2 = str(page_data.get(key, '')).strip().lower()
            # Skip check if one of the values is empty or unclear to prevent false positives
            if not val1 or not val2 or val1 in ["unknown", "n/a", "none"] or val2 in ["unknown", "n/a", "none"]:
                continue
            if val1 != val2:
                errors.append(
                    f"Title block mismatch: {label} differs between Page 1 ('{first_page.get(key)}') "
                    f"and Page {idx} ('{page_data.get(key)}')."
                )
    return errors


def _coord_present(value) -> bool:
    """A coordinate is 'present' only if it is a non-zero number."""
    try:
        return abs(float(value)) > 0.01
    except (TypeError, ValueError):
        return False


def check_coordinate_consistency(title_blocks: list) -> list[str]:
    """
    Verifies that the Easting and Northing read from every sheet's title block are
    identical across all sheets of a single borehole (the coordinates describe one
    physical hole, so they must agree). Only compares sheets where a coordinate was
    actually read (a blank/zero on one sheet is treated as 'not reported', not a
    contradiction). A disagreement triggers the self-correction retry loop.
    """
    errors = []
    if not title_blocks or len(title_blocks) <= 1:
        return errors

    for key, label in (("easting", "Easting"), ("northing", "Northing")):
        # Round to 2 dp so trivial OCR jitter on the same value does not misfire.
        distinct = {round(float(tb.get(key)), 2)
                    for tb in title_blocks if _coord_present(tb.get(key))}
        if len(distinct) > 1:
            errors.append(
                f"Coordinate mismatch: {label} differs across sheets ({sorted(distinct)}). "
                f"All sheets of one borehole must report the same {label}."
            )
    return errors


def check_description_and_classification(rows: list[list[str]]) -> list[str]:
    """
    Verifies that:
    1. Descriptions do not contain unresolved 'As Sheet X' references.
    2. Wash boring / No recovery descriptions are classified correctly (not as geological rock/soil types).
    """
    errors = []
    as_sheet_pattern = re.compile(r"\b(?:as|refer\s+to|per)\s+sheet\s*\d+", re.IGNORECASE)

    for idx, r in enumerate(rows):
        if len(r) <= COL_TYPE:
            continue

        desc = r[COL_DESC].strip()
        material_type = r[COL_TYPE].strip().lower()

        # 1. Check for unresolved 'As Sheet X' references
        if as_sheet_pattern.search(desc):
            errors.append(
                f"Row {idx+1}: Unresolved description reference '{desc}'. "
                f"The description must state the actual geological material."
            )

        # 2. Check for Wash Boring / No Recovery classification consistency
        desc_lower = desc.lower()
        has_wash_boring = "wash boring" in desc_lower or "no recovery" in desc_lower or "core loss" in desc_lower or "core photo" in desc_lower
        # A brief in-run "no recovery at X-Ym." footnote on an otherwise-described rock
        # layer is allowed (absorbed elsewhere); only whole-interval no-recovery rows matter.
        whole_interval_no_recovery = desc_lower.startswith("wash boring") or desc_lower.startswith("no recovery")

        if has_wash_boring and whole_interval_no_recovery:
            # Check if it was misclassified as a geological soil/rock type
            geological_types = ["granite", "tuff", "sand", "clay", "silt", "gravel", "rock", "alluvium"]
            if any(gt in material_type for gt in geological_types) and "fill" not in material_type:
                errors.append(
                    f"Row {idx+1}: Classification mismatch. Description mentions '{desc}', but it is classified as '{r[COL_TYPE]}'. "
                    f"Intervals with no material recovery must be classified as 'No Recovery' or 'Wash Boring'."
                )
    return errors


def request_gemini_correction(
    model: genai.GenerativeModel,
    images: list,
    borehole_name: str,
    original_json_str: str,
    errors: list[str]
) -> dict:
    """
    Sends the validation errors and original response JSON back to Gemini to request a corrected extraction.
    """
    from .extractor import EXTRACTION_SCHEMA
    errors_str = "\n".join([f"- {err}" for err in errors])
    prompt = (
        f"We extracted the following borehole data JSON for borehole '{borehole_name}':\n\n"
        f"{original_json_str}\n\n"
        f"However, the following validation checks failed on this extraction:\n"
        f"{errors_str}\n\n"
        f"Please re-analyze the provided log images and correct the data extraction for borehole '{borehole_name}'. "
        f"Make sure to resolve all continuity, termination depth, coordinate, and title block issues. "
        f"Provide the output strictly as JSON matching the response schema."
    )
    contents = list(images) + [prompt]
    try:
        response = model.generate_content(
            contents,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": EXTRACTION_SCHEMA
            }
        )
        if not response or not response.text:
            print(f"    [Warning] Received empty response from Gemini during correction.")
            return {}
        return json.loads(response.text)
    except Exception as e:
        print(f"    [Error] Gemini correction request failed: {e}")
        return {}


def consensus_coordinates(title_blocks: list) -> tuple[str, str]:
    """
    Returns the agreed (Easting, Northing) for the borehole as formatted numeric
    strings, taken as the most common non-zero value across all title blocks.
    Returns ('', '') when no coordinate was read on any sheet.
    """
    def _consensus(key):
        vals = [round(float(tb.get(key)), 2) for tb in (title_blocks or []) if _coord_present(tb.get(key))]
        if not vals:
            return ""
        best = Counter(vals).most_common(1)[0][0]
        return f"{best:.2f}"
    return _consensus("easting"), _consensus("northing")


def inject_coordinates(rows: list[list[str]], easting: str, northing: str) -> list[list[str]]:
    """
    Inserts the borehole's Easting and Northing (columns 1 and 2) into every
    stratigraphy row emitted by the model, turning the model's per-layer rows into
    the full canonical schema. Idempotent: rows already at NUM_COLS are left as-is.
    """
    injected = []
    for r in rows:
        if len(r) >= NUM_COLS:
            injected.append(r)
            continue
        # Model row starts with Hole No at index 0; coordinates slot in right after it.
        new_row = [r[0], easting, northing] + list(r[1:])
        injected.append(new_row)
    return injected


def normalize_rows(rows: list[list[str]], title_blocks: list) -> list[list[str]]:
    """
    Runs the full normalization chain in the required order on freshly-parsed model
    rows: inject coordinates (turning 8-col model rows into the 10-col schema), then
    resolve references, merge, absorb short no-recovery notes, force fill/concrete
    types, backfill grades from description, and standardise grade/confidence/degrees.
    Single source of truth so every job call site stays in sync.
    """
    east, north = consensus_coordinates(title_blocks)
    rows = inject_coordinates(rows, east, north)
    rows = resolve_as_sheet_descriptions(rows)
    rows = merge_consecutive_identical_layers(rows)
    rows = absorb_short_no_recovery_annotations(rows)
    rows = force_fill_and_concrete_types(rows)
    rows = fill_grade_from_description(rows)
    rows = normalize_grade(rows)
    rows = normalize_confidence(rows)
    rows = normalize_degree_symbols(rows)
    return rows


def resolve_as_sheet_descriptions(rows: list[list[str]]) -> list[list[str]]:
    """
    Resolves descriptions like 'As Sheet X of Y' or 'As Sheet X' by copying the
    description, grade, and soil/rock type of the last layer of Sheet X.
    """
    try:
        sorted_rows = sorted(rows, key=lambda x: float(x[COL_START]))
    except (ValueError, IndexError):
        return rows

    sheet_last_layers = {}
    for r in sorted_rows:
        if len(r) <= COL_TYPE:
            continue
        sheet_no = r[COL_SHEET].strip()
        sheet_last_layers[sheet_no] = r

    as_sheet_pattern = re.compile(r"(?:as|refer\s+to|per)\s+sheet\s*(\d+)", re.IGNORECASE)

    resolved_rows = []
    for r in sorted_rows:
        if len(r) <= COL_TYPE:
            resolved_rows.append(r)
            continue

        desc = r[COL_DESC].strip()
        match = as_sheet_pattern.search(desc)
        if match:
            target_sheet = match.group(1).strip()
            if target_sheet in sheet_last_layers:
                target_layer = sheet_last_layers[target_sheet]

                print(f"      [Resolve] Resolving '{desc}' using Sheet {target_sheet} bottom-most layer: '{target_layer[COL_DESC]}'")

                new_row = list(r)
                new_row[COL_DESC] = target_layer[COL_DESC]
                new_row[COL_TYPE] = target_layer[COL_TYPE]
                new_row[COL_GRADE] = target_layer[COL_GRADE]
                resolved_rows.append(new_row)
                continue

        resolved_rows.append(r)

    return resolved_rows


def merge_consecutive_identical_layers(rows: list[list[str]]) -> list[list[str]]:
    """
    Merges consecutive layers with the same description (case-insensitive) into a single layer.
    """
    if len(rows) < 2:
        return rows

    try:
        sorted_rows = sorted(rows, key=lambda x: float(x[COL_START]))
    except (ValueError, IndexError):
        return rows

    merged_rows = [sorted_rows[0]]

    for next_row in sorted_rows[1:]:
        curr_row = merged_rows[-1]

        try:
            curr_end = float(curr_row[COL_END])
            next_start = float(next_row[COL_START])
        except (ValueError, IndexError):
            merged_rows.append(next_row)
            continue

        desc1 = curr_row[COL_DESC].strip().lower() if len(curr_row) > COL_DESC else ""
        desc2 = next_row[COL_DESC].strip().lower() if len(next_row) > COL_DESC else ""

        if desc1 == desc2 and abs(curr_end - next_start) <= 0.005:
            print(f"      [Merge] Merging consecutive identical layers: {curr_row[COL_START]}-{curr_row[COL_END]} m and {next_row[COL_START]}-{next_row[COL_END]} m")
            curr_row[COL_END] = next_row[COL_END]
        else:
            merged_rows.append(next_row)

    return merged_rows


def absorb_short_no_recovery_annotations(rows: list[list[str]]) -> list[list[str]]:
    """
    Absorbs brief 'No recovery' core-loss notes (<=2 m span) back into the
    preceding described rock/soil layer instead of leaving them as a standalone
    'No Recovery' layer. A short core-loss gap inside an otherwise-cored,
    described drilling run is a recovery-percentage footnote, not a distinct
    geological unit — the manual GI convention keeps the surrounding grade for
    that sub-interval. Only absorbs when the gap is short; a long uncored span
    (wash boring proper) is left as its own 'No Recovery'/'Wash Boring' layer.
    """
    if len(rows) < 3:
        return rows
    try:
        sorted_rows = sorted(rows, key=lambda x: float(x[COL_START]))
    except (ValueError, IndexError):
        return rows

    result = [sorted_rows[0]]
    for i in range(1, len(sorted_rows)):
        row = sorted_rows[i]
        if len(row) <= COL_TYPE:
            result.append(row)
            continue
        rtype = row[COL_TYPE].strip().lower()
        desc = row[COL_DESC].strip().lower()
        is_short_note = (
            rtype in ("no recovery", "wash boring")
            and "no recovery" in desc
            and "wash boring" not in desc
            and len(desc) < 40
        )
        prev = result[-1]
        if is_short_note and len(prev) > COL_TYPE:
            try:
                gap = float(row[COL_END]) - float(row[COL_START])
                contiguous = abs(float(row[COL_START]) - float(prev[COL_END])) < 1e-6
            except (ValueError, IndexError):
                gap, contiguous = None, False
            prev_type = prev[COL_TYPE].strip().lower()
            if (
                contiguous and gap is not None and gap <= 2.0
                and prev_type not in ("no recovery", "wash boring", "")
            ):
                prev[COL_END] = row[COL_END]
                prev[COL_DESC] = prev[COL_DESC].rstrip() + f" No recovery {row[COL_START]}-{row[COL_END]}m."
                continue
        result.append(row)
    return result


def force_fill_and_concrete_types(rows: list[list[str]]) -> list[list[str]]:
    """
    Forces the Soil/Rock Type column to a consistent classification for two
    recurring cases the model classifies inconsistently across runs:
      - Any description ending in '(FILL)' must have Type == 'Fill', regardless
        of which specific grain-size material name (e.g. 'Sand') was extracted.
      - A standalone 'Concrete Slab' description (not itself fill) must have
        Type == 'Concrete', not 'Fill'.
    """
    fill_suffix = re.compile(r'\(fill\)\s*$', re.IGNORECASE)
    concrete_slab = re.compile(r'^\s*concrete\s+slab\b', re.IGNORECASE)
    for r in rows:
        if len(r) <= COL_TYPE:
            continue
        desc = r[COL_DESC]
        cur_type = r[COL_TYPE].strip().lower()
        if fill_suffix.search(desc.strip()) and cur_type not in ("fill", "no recovery", "wash boring"):
            r[COL_TYPE] = "Fill"
        elif concrete_slab.match(desc) and not fill_suffix.search(desc.strip()) and cur_type != "concrete":
            r[COL_TYPE] = "Concrete"
    return rows


def _derive_grade_from_text(desc: str) -> str:
    """Infers a weathering grade (e.g. 'III' or 'III/IV') from decomposition wording."""
    found = []
    for m in _GRADE_RE.finditer(desc):
        found.append((m.start(), _ADJ_GRADE[m.group(1).lower()]))
        if m.group(2):
            found.append((m.start(), _ADJ_GRADE[m.group(2).lower()]))
    for m in _RESIDUAL_RE.finditer(desc):
        found.append((m.start(), "VI"))
    found.sort(key=lambda x: x[0])
    seq = []
    for _, g in found:
        if not seq or seq[-1] != g:
            seq.append(g)
    uniq = []
    for g in seq:
        if g not in uniq:
            uniq.append(g)
    return "/".join(uniq[:2])


def fill_grade_from_description(rows: list[list[str]]) -> list[list[str]]:
    """
    Backstop for the model's Grade column: when an in-situ rock layer has an empty
    Grade but its description carries decomposition wording ('moderately decomposed',
    'highly to moderately decomposed', ...), infer the grade from that wording. Only
    fills rock layers; non-rock types (Fill, No Recovery, Alluvium, ...) stay blank.
    """
    for r in rows:
        if len(r) <= COL_TYPE:
            continue
        if r[COL_GRADE].strip():
            continue
        if r[COL_TYPE].strip().lower() in NON_ROCK_TYPES:
            continue
        derived = _derive_grade_from_text(r[COL_DESC])
        if derived:
            r[COL_GRADE] = derived
    return rows


def normalize_grade(rows: list[list[str]]) -> list[list[str]]:
    """
    Standardises the Grade column formatting: uppercase roman numerals, and a single
    forward slash between two grades (collapsing 'IV / III', 'IV-III', 'IV\\III' -> 'IV/III').
    """
    for r in rows:
        if len(r) <= COL_GRADE:
            continue
        g = r[COL_GRADE].strip().upper()
        if not g:
            continue
        g = re.sub(r'\s*[/\\]\s*', '/', g)
        g = re.sub(r'(?<=[IVX])\s*-\s*(?=[IVX])', '/', g)
        g = re.sub(r'\s+', ' ', g).strip()
        r[COL_GRADE] = g
    return rows


def _to_confidence(value) -> float:
    """Coerces any confidence representation (High/Medium/Low, %, decimal) to [0, 1]."""
    s = str(value).strip().lower()
    if not s:
        return 0.80
    words = {
        "very high": 0.95, "high": 0.90, "medium": 0.75, "moderate": 0.75,
        "low": 0.50, "very low": 0.30,
    }
    if s in words:
        return words[s]
    is_pct = s.endswith("%")
    if is_pct:
        s = s[:-1].strip()
    try:
        x = float(s)
    except ValueError:
        return 0.80
    if is_pct or x > 1.0:
        x = x / 100.0
    return max(0.0, min(1.0, round(x, 3)))


def normalize_confidence(rows: list[list[str]]) -> list[list[str]]:
    """Coerces the Confidence Level column to a decimal in [0.00, 1.00]."""
    for r in rows:
        if len(r) <= COL_CONF:
            continue
        r[COL_CONF] = f"{_to_confidence(r[COL_CONF]):.2f}"
    return rows


def normalize_degree_symbols(rows: list[list[str]]) -> list[list[str]]:
    """
    Replaces degree symbols (°) in descriptions with the word 'degrees'.
    """
    for r in rows:
        if len(r) > COL_DESC:
            r[COL_DESC] = r[COL_DESC].replace("°", " degrees").replace("º", " degrees")
    return rows


def verify_pdf_filename(filename: str) -> bool:
    """
    Verifies if the split PDF filename matches [Prefix]_Borehole_[Hole_No].pdf or Borehole_[Hole_No].pdf.
    [Prefix] and [Hole_No] can contain letters, digits, and hyphens.
    """
    basename = os.path.basename(filename)
    pattern1 = r"^([a-zA-Z0-9\-]+)_Borehole_([a-zA-Z0-9\-\_]+)\.pdf$"
    pattern2 = r"^Borehole_([a-zA-Z0-9\-\_]+)\.pdf$"
    return bool(re.match(pattern1, basename) or re.match(pattern2, basename))


def verify_excel_filename(filename: str) -> bool:
    """
    Verifies if the CSV log filename matches [Prefix]_Borehole_[Hole_No]_stratigraphy.csv or Borehole_[Hole_No]_stratigraphy.csv.
    """
    basename = os.path.basename(filename)
    pattern1 = r"^([a-zA-Z0-9\-]+)_Borehole_([a-zA-Z0-9\-\_]+)_stratigraphy\.csv$"
    pattern2 = r"^Borehole_([a-zA-Z0-9\-\_]+)_stratigraphy\.csv$"
    return bool(re.match(pattern1, basename) or re.match(pattern2, basename))
