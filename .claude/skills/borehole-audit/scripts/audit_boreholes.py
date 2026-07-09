"""
Borehole pipeline audit — diff engine.

Consumes a JSON description of what each source report declares (raw hole-number
tokens transcribed from the report's page-2 cover sheet, e.g. "DH5-DH51",
"B2a-B2c", "P61"), expands it against the two downstream pipeline artifacts —
the split PDFs in `individual borehole logs/` and the master stratigraphy CSV in
`results/` — and writes a markdown audit report.

This script only does the mechanical set algebra (range expansion, OCR-tolerant
name matching, diffing, report writing). It does NOT read PDFs or images —
transcribing the bracketed "HOLE NOS." list from each report's page-2 cover
sheet requires vision/OCR, which the calling agent does before invoking this
script (see render_cover_pages.py + SKILL.md for that step).
"""
import argparse
import csv
import glob
import json
import os
import re
from collections import defaultdict

HOLE_TOKEN_RE = re.compile(r"^([A-Za-z]+)(\d+)([A-Za-z]*)$")
FILENAME_RE = re.compile(r"^(?P<report>\w+)_Borehole_(?P<hole>.+)\.pdf$", re.IGNORECASE)

# Digits/letters OCR commonly confuses on these scanned reports. Used only for
# fuzzy matching split-log filenames back to declared hole numbers — never for
# deciding what a hole's "real" name is (that judgment call stays with the agent).
# Every character in a confusable group collapses to the SAME canonical symbol
# (not a 1:1 swap) so both spellings hash identically regardless of which one
# OCR actually produced.
OCR_EQUIVALENTS = {}
for _group in (("0", "O"), ("1", "I", "L"), ("5", "S"), ("8", "B")):
    _canonical = _group[0]
    for _ch in _group:
        OCR_EQUIVALENTS[_ch] = _canonical


def normalize(hole: str) -> str:
    return hole.strip().upper().replace(" ", "").replace("-", "")


def ocr_fuzzy_key(hole: str) -> str:
    """Collapse OCR-confusable characters so e.g. A5A / ASA hash the same."""
    return "".join(OCR_EQUIVALENTS.get(c, c) for c in normalize(hole))


def expand_token(token: str):
    """Expand a single raw cover-page token into one or more hole numbers.

    Handles:
      - plain holes:        "P61"          -> ["P61"]
      - numeric ranges:     "DH5-DH51"     -> ["DH5", "DH6", ..., "DH51"]
      - suffix-letter runs: "B2a-B2c"      -> ["B2A", "B2B", "B2C"]
    """
    token = token.strip()
    if "-" not in token:
        return [normalize(token)]

    left, right = [t.strip() for t in token.split("-", 1)]
    lm, rm = HOLE_TOKEN_RE.match(left), HOLE_TOKEN_RE.match(right)

    # Numeric range: same alpha prefix, no suffix letters, e.g. "DH5-DH51".
    if lm and lm.group(3) == "":
        if right.isdigit():
            prefix, start, end = lm.group(1), int(lm.group(2)), int(right)
            return [f"{prefix.upper()}{n}" for n in range(start, end + 1)]
        if rm and rm.group(3) == "" and rm.group(1).upper() == lm.group(1).upper():
            prefix, start, end = lm.group(1), int(lm.group(2)), int(rm.group(2))
            return [f"{prefix.upper()}{n}" for n in range(start, end + 1)]

    # Suffix-letter run: same alpha+numeric prefix, single trailing letter differs.
    if lm and rm and lm.group(1).upper() == rm.group(1).upper() and lm.group(2) == rm.group(2):
        prefix_num = f"{lm.group(1).upper()}{lm.group(2)}"
        start_letter, end_letter = lm.group(3).upper(), rm.group(3).upper()
        if len(start_letter) == 1 and len(end_letter) == 1:
            return [f"{prefix_num}{chr(c)}" for c in range(ord(start_letter), ord(end_letter) + 1)]

    # Fall back: couldn't parse as a range, treat both ends as literal holes.
    return [normalize(left), normalize(right)]


def expand_tokens(tokens):
    holes = []
    for tok in tokens:
        holes.extend(expand_token(tok))
    # de-dup, keep order
    seen = set()
    out = []
    for h in holes:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def load_declared(reports_json_path):
    """reports_json_path: JSON list of {report, date, raw_tokens: [...]}
    `date` should sort chronologically as a string (e.g. "1996-08") so
    supplementary/re-investigation reports can be ordered correctly.
    """
    with open(reports_json_path, encoding="utf-8") as f:
        reports = json.load(f)
    for r in reports:
        r["holes"] = expand_tokens(r["raw_tokens"])
    reports.sort(key=lambda r: r["date"])
    return reports


def scan_split_logs(splits_dir):
    """Returns dict: hole -> list of (report_label, filename), in filename order."""
    by_hole = defaultdict(list)
    for fname in sorted(os.listdir(splits_dir)):
        m = FILENAME_RE.match(fname)
        if not m:
            continue
        by_hole[normalize(m.group("hole"))].append((m.group("report"), fname))
    return by_hole


def scan_csv_holes(csv_path):
    holes = set()
    with open(csv_path, encoding="utf-8") as f:
        first = f.readline()
        if not first.lower().startswith("sep="):
            f.seek(0)
        reader = csv.DictReader(f, delimiter=";")
        hole_col = "Hole No" if "Hole No" in (reader.fieldnames or []) else reader.fieldnames[0]
        for row in reader:
            v = row.get(hole_col)
            if v:
                holes.add(normalize(v))
    return holes


def find_latest_csv(results_dir):
    candidates = glob.glob(os.path.join(results_dir, "borehole_stratigraphy*.csv"))
    if not candidates:
        return None
    # Prefer highest _vN suffix, then most recently modified.
    def version_key(path):
        m = re.search(r"_v(\d+)", os.path.basename(path))
        return (int(m.group(1)) if m else 0, os.path.getmtime(path))
    return max(candidates, key=version_key)


def build_report(reports, split_by_hole, csv_holes, splits_dir, csv_path):
    lines = ["# Borehole Extraction Pipeline Audit", ""]
    lines.append(
        "Source: page 2 (cover page) bracketed \"HOLE NOS.\" lists from each report in "
        "`Borehole Reports/`, cross-checked against "
        f"`{os.path.basename(os.path.normpath(splits_dir))}/` and `{os.path.relpath(csv_path)}`."
    )
    lines.append("")
    lines.append("## 1. Borehole lists declared per report (page 2)")
    lines.append("")

    all_declared = set()
    hole_first_report = {}
    for r in reports:
        lines.append(f"### {r['date']} — `{r['report']}`")
        lines.append(f"> HOLE NOS. {', '.join(r['raw_tokens'])}")
        lines.append("")
        lines.append(f"{len(r['holes'])} holes: {', '.join(r['holes'])}")
        lines.append("")
        for h in r["holes"]:
            all_declared.add(h)
            hole_first_report.setdefault(h, r["date"])

    lines.append(f"**Total unique boreholes declared across all reports: {len(all_declared)}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- Section 2: report vs split logs ---
    lines.append(f"## 2. Reports vs. split logs (`{os.path.basename(os.path.normpath(splits_dir))}/`)")
    lines.append("")

    split_fuzzy = defaultdict(list)
    for hole, occurrences in split_by_hole.items():
        split_fuzzy[ocr_fuzzy_key(hole)].append(hole)

    never_split = []
    for h in sorted(all_declared):
        if h in split_by_hole:
            continue
        if ocr_fuzzy_key(h) in split_fuzzy:
            continue  # present under an OCR-garbled filename
        never_split.append(h)

    if never_split:
        lines.append(f"**Missing entirely — declared but no split PDF found in `{splits_dir}` "
                      f"under this name or an OCR-equivalent name:**")
        lines.append("")
        for h in never_split:
            lines.append(f"- **{h}** (declared in {hole_first_report[h]})")
    else:
        lines.append("No declared holes are missing a split PDF (including OCR-tolerant matching).")
    lines.append("")

    # Supplementary / re-investigation gap check: a hole declared in >1 report
    # should have a split log filename tagged with each report's month/year.
    stale = []
    for h in sorted(all_declared):
        declaring_reports = [r for r in reports if h in r["holes"]]
        if len(declaring_reports) < 2:
            continue
        have_labels = {label for label, _ in split_by_hole.get(h, [])}
        missing_labels = [r["report_label"] for r in declaring_reports if r["report_label"] not in have_labels]
        if missing_labels:
            newest = declaring_reports[-1]["report_label"]
            stale.append((h, missing_labels, newest, sorted(have_labels)))

    if stale:
        lines.append("**Supplementary / re-investigation gaps** — hole numbers declared by more than "
                      "one report (a later report re-investigating an earlier hole), where a split "
                      "PDF is missing for one of the declaring reports. If the newest report's split "
                      "is the one missing, any master-CSV row for that hole is silently stuck on "
                      "stale, older data:")
        lines.append("")
        lines.append("| Hole | Missing split for | Have splits for |")
        lines.append("|---|---|---|")
        for h, missing_labels, newest, have in stale:
            flag = " ⚠ newest missing" if newest in missing_labels else ""
            lines.append(f"| {h} | {', '.join(missing_labels)}{flag} | {', '.join(have) or '—'} |")
        lines.append("")

    lines.append("---")
    lines.append("")

    # --- Section 3: split logs vs CSV ---
    lines.append(f"## 3. Split logs vs. master CSV (`{os.path.relpath(csv_path)}`)")
    lines.append("")
    split_holes = set(split_by_hole.keys())
    csv_fuzzy = {ocr_fuzzy_key(h): h for h in csv_holes}

    missing_from_csv = sorted(h for h in split_holes if h not in csv_holes and ocr_fuzzy_key(h) not in csv_fuzzy)
    missing_from_splits = sorted(h for h in csv_holes if h not in split_holes and ocr_fuzzy_key(h) not in {ocr_fuzzy_key(s) for s in split_holes})

    lines.append(f"- Unique hole numbers in split logs: **{len(split_holes)}**")
    lines.append(f"- Unique hole numbers in master CSV: **{len(csv_holes)}**")
    lines.append("")
    if missing_from_csv:
        lines.append(f"**Split but never extracted (missing from CSV):** {', '.join(missing_from_csv)}")
    else:
        lines.append("Every split log has a corresponding CSV entry — no extraction-stage losses.")
    lines.append("")
    if missing_from_splits:
        lines.append(f"**In CSV but no matching split filename found:** {', '.join(missing_from_splits)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- Section 4: summary ---
    lines.append("## 4. Summary")
    lines.append("")
    lines.append("| Check | Result |")
    lines.append("|---|---|")
    lines.append(f"| Report → Split logs | {'Clean' if not never_split else f'{len(never_split)} holes missing: ' + ', '.join(never_split)} |")
    lines.append(f"| Supplementary re-investigation coverage | {'Clean' if not stale else f'{len(stale)} hole(s) with a stale/missing split'} |")
    lines.append(f"| Split logs → Master CSV | {'Clean, ' + str(len(split_holes)) + '/' + str(len(csv_holes)) + ' match' if not missing_from_csv and not missing_from_splits else 'Gaps found — see Section 3'} |")
    lines.append("")

    if never_split or stale or missing_from_csv:
        lines.append("**Action items:**")
        idx = 1
        if never_split:
            lines.append(f"{idx}. Locate {', '.join(never_split)} in the source report PDF(s) and run them through the splitter/extractor.")
            idx += 1
        if stale:
            stale_holes = ", ".join(h for h, *_ in stale)
            lines.append(f"{idx}. Re-split/re-extract the newer report pages for: {stale_holes}, then decide whether the master CSV should be updated to the newer version.")
            idx += 1
        if missing_from_csv:
            lines.append(f"{idx}. Run extraction for split logs missing from the CSV: {', '.join(missing_from_csv)}.")

    return "\n".join(lines) + "\n", {
        "never_split": never_split,
        "stale": stale,
        "missing_from_csv": missing_from_csv,
        "missing_from_splits": missing_from_splits,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports-json", required=True, help="JSON file with declared hole tokens per report")
    ap.add_argument("--splits-dir", default="individual borehole logs")
    ap.add_argument("--csv", default=None, help="Master stratigraphy CSV (default: newest results/borehole_stratigraphy*.csv)")
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--output", default="borehole_audit.md")
    args = ap.parse_args()

    csv_path = args.csv or find_latest_csv(args.results_dir)
    if not csv_path:
        raise SystemExit(f"No borehole_stratigraphy*.csv found in {args.results_dir}")

    reports = load_declared(args.reports_json)
    split_by_hole = scan_split_logs(args.splits_dir)
    csv_holes = scan_csv_holes(csv_path)

    report_text, findings = build_report(reports, split_by_hole, csv_holes, args.splits_dir, csv_path)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"Wrote {args.output}")
    print(json.dumps({k: (v if k != "stale" else [s[0] for s in v]) for k, v in findings.items()}, indent=2))


if __name__ == "__main__":
    main()
