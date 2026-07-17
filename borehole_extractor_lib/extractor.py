import time
import sys
import os
import google.generativeai as genai
import google.api_core.exceptions

SYSTEM_INSTRUCTION = (
    "Act as an expert geotechnical engineer analyzing raw borehole log images. "
    "Your task is to extract the geological stratigraphy into a structured CSV. "
    "Strictly follow ALL of the following rules without exception:\n\n"
    "EXTRACTION RULES:\n"
    "1. Disregard peripheral columns (flushing medium, shift times, core photos). "
    "Focus on the depth column, the Grade column, and the soil/rock description column.\n"
    "2. Output Start Depth and End Depth as numeric values in metres only (e.g. 10.50, not '10.50m').\n"
    "3. Sheet No must be a single positive integer number (e.g. 1, 2, not '1-3' or 'Sheet 1').\n"
    "4. Depth ranges must be STRICTLY CONTINUOUS: End Depth of row N must equal Start Depth of row N+1. "
    "If a gap exists in the log, bridge it with a 'No recovery' entry.\n"
    "5. Every layer's Start Depth must be LESS THAN its End Depth. "
    "Do not emit rows where Start Depth >= End Depth.\n"
    "6. Depth ranges must be in STRICTLY INCREASING order. Do not repeat or emit overlapping depth ranges.\n"
    "7. Do NOT emit duplicate rows. If the same depth range appears more than once, output it only once.\n"
    "8. If a thick stratum spans multiple log sheets, it will appear on each sheet as a separate entry. "
    "Merge them into a SINGLE row covering the full combined depth range with the same description.\n"
    "9. When a layer description reads 'As Sheet X', 'Per Sheet X', or 'Refer to Sheet X', "
    "do NOT output that string. Instead, find the actual material description on Sheet X and use it.\n"
    "10. The final row's End Depth must equal the total termination depth of the borehole "
    "(usually written at the bottom-left corner of the last log sheet).\n"
    "11. Classify a concise Soil/Rock Type (e.g. Sand, Clay, Granite, Fill, No Recovery).\n"
    "12. Confidence Level must be a DECIMAL NUMBER between 0.00 and 1.00 reflecting how legible and "
    "certain the extraction of that row is (1.00 = crisp and unambiguous; lower for faint, damaged, "
    "or ambiguous scans). Do NOT output words like 'High'/'Medium'/'Low' or percentages.\n"
    "13. Use a semicolon (;) as the delimiter for all fields in the CSV string output. "
    "If a field's own text ever needs to contain a semicolon (e.g. a list of joint dip "
    "angles like '10; 20, 40; 50'), wrap that ENTIRE field in double quotes so it is not "
    "mistaken for a column break (standard CSV quoting) — e.g. \"...dipping 10; 20, 40; 50...\". "
    "Prefer rewording such lists with commas only (e.g. '10, 20, 40, 50') to avoid the issue "
    "entirely wherever possible.\n"
    "14. GRADE COLUMN: read the sheet's dedicated 'Grade' column (the rock weathering grade, roman "
    "numerals I to VI, where I=fresh, II=slightly decomposed, III=moderately decomposed, IV=highly "
    "decomposed, V=completely decomposed, VI=residual soil). Output the grade EXACTLY as printed in "
    "that column for the row's depth interval. When a layer is logged as spanning TWO grades (the "
    "Grade cell shows e.g. 'IV/III' or 'III/II'), output BOTH joined by a single forward slash '/', "
    "in the same order printed (higher-decomposition grade first as logged). For any NON-rock layer "
    "(Fill, Concrete, Alluvium, Marine Deposit, Wash Boring / No Recovery) the Grade column is blank "
    "— output an EMPTY field for Grade. Also copy elliptical decomposition wording verbatim into the "
    "description (e.g. 'moderately to slightly decomposed', not paraphrased) — do not summarize it away.\n"
    "15. A brief 'No recovery at X-Ym' note inside an otherwise-cored, described rock or soil run "
    "(i.e. TCR/SCR/RQD percentages are reported for that run and a Grade is assigned either side of "
    "the gap) is a recovery-percentage footnote, NOT a separate geological layer — keep it as part of "
    "the enclosing layer's description (retaining that layer's Grade) and do not classify that "
    "sub-range as its own 'No Recovery' row. Only classify a range as 'No Recovery' / 'Wash Boring' "
    "when the ENTIRE interval has no lithological description at all (a genuine uncored/wash-bored "
    "section). Watch for a thin ALLUVIUM layer (sub-rounded cobbles/gravels, often in an inset/"
    "bracketed note) sandwiched between two Wash Boring/No Recovery zones just above bedrock — do not "
    "let the surrounding wash-boring swallow it.\n"
    "16. Any layer whose description ends in '(FILL)' must have Soil/Rock Type = 'Fill', regardless "
    "of the specific grain-size material named (sand, gravel, cobbles, etc). A standalone 'Concrete "
    "Slab' layer (not itself fill) must have Type = 'Concrete', not 'Fill'.\n"
    "17. CO-ORDINATES: from each sheet's header 'CO-ORDINATES' box, read the Easting (the number "
    "after 'E') and Northing (the number after 'N') as plain numbers. These are identical on every "
    "sheet of the same borehole; report them per page in the title_blocks output (do NOT put them in "
    "the CSV rows).\n\n"
    "18. DO NOT START A ROCK LAYER EARLY. A long Wash Boring / No Recovery zone can span an entire "
    "sheet or more before rock is actually reached. Before writing a Grade/rock description for any "
    "depth, confirm on THAT sheet that core recovery data genuinely starts there: the Total Core "
    "Recovery %, Solid Core Recovery %, and R.Q.D. columns are populated (not blank) and the Legend "
    "column has switched from the wash-boring texture to the rock-legend pattern, at or before the "
    "depth you are about to describe. If the recovery columns and legend are still blank/wash-boring "
    "at that depth, the ground is still 'No Recovery' there — do not invent or bring forward a rock "
    "description to fill it, even if you can see the rock description further down the sheet. The "
    "first row with an actual Grade and description must start at the exact depth where the recovery "
    "percentages first appear, not earlier.\n\n"
    "OUTPUT FORMAT:\n"
    "Provide the stratigraphy_csv STRICTLY as raw CSV text with the following headers (no markdown "
    "code blocks, no coordinates column):\n"
    "Hole No;Sheet No;Start Depth;End Depth;Grade;Soil/Rock Description;Soil/Rock Type;Confidence Level"
)


import json

EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "stratigraphy_csv": {
            "type": "STRING",
            "description": "The extracted stratigraphy as raw CSV text with headers: Hole No;Sheet No;Start Depth;End Depth;Grade;Soil/Rock Description;Soil/Rock Type;Confidence Level. Use semicolon (;) as the delimiter. Sheet No must be a single integer. Grade is the rock weathering grade (roman numeral I-VI, or two grades joined by '/', empty for non-rock layers). Confidence Level is a decimal between 0.00 and 1.00. Do NOT include coordinates in these rows. If a field's text must contain a semicolon (e.g. a joint dip-angle list), wrap that field in double quotes so it isn't mistaken for a column break; prefer rewording with commas only instead. Do not wrap in markdown code blocks."
        },
        "termination_depth": {
            "type": "NUMBER",
            "description": "The total termination depth of the borehole in meters (e.g. 30.37). Look for 'Termination Depth', 'End of Hole', or 'EOB' at the bottom of the log sheets. Return 0.0 if not explicitly found."
        },
        "title_blocks": {
            "type": "ARRAY",
            "description": "List of title block information for each page",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "page_number": {"type": "INTEGER"},
                    "hole_no": {"type": "STRING"},
                    "project_name": {"type": "STRING"},
                    "project_number": {"type": "STRING"},
                    "date": {"type": "STRING"},
                    "easting": {"type": "NUMBER", "description": "Easting coordinate (the number after 'E' in the CO-ORDINATES box). 0.0 if not found."},
                    "northing": {"type": "NUMBER", "description": "Northing coordinate (the number after 'N' in the CO-ORDINATES box). 0.0 if not found."}
                },
                "required": ["page_number", "hole_no", "project_name", "project_number", "date", "easting", "northing"]
            }
        }
    },
    "required": ["stratigraphy_csv", "termination_depth", "title_blocks"]
}


class DailyQuotaExhaustedError(Exception):
    """Raised when the Gemini API daily requests quota is fully exhausted."""
    pass


def initialize_gemini_client(api_key: str, model_name: str) -> genai.GenerativeModel:
    """
    Configures and initializes the Gemini GenerativeModel with system instructions.
    """
    if not api_key:
        raise ValueError("Google AI Studio API key (GEMINI_API_KEY) is missing.")
        
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_INSTRUCTION
        )
    except Exception as e:
        print(f"[Error] Failed to initialize Gemini API client: {e}", file=sys.stderr)
        raise e


def extract_stratigraphy_with_retry(
    model: genai.GenerativeModel,
    images: list,
    borehole_name: str,
    max_retries: int = 5,
    initial_delay: float = 4.0,
    backoff_factor: float = 2.0
) -> dict:
    """
    Calls the Gemini API to extract stratigraphy from a list of PIL images.
    Implements exponential backoff to handle rate limits (429), server errors (5xx), and timeouts.
    Returns the parsed JSON response dict.
    """
    contents = list(images)
    contents.append(
        f"Please extract the stratigraphy table for borehole '{borehole_name}' from the provided log images. "
        "Also extract the termination depth and title block details for each page. "
        "Provide the output strictly as JSON matching the response schema."
    )
    
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            response = model.generate_content(
                contents,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": EXTRACTION_SCHEMA
                }
            )
            
            if not response or not response.text:
                print(f" [Warning] Received empty response from Gemini for borehole {borehole_name}.")
                return {}
                
            try:
                data = json.loads(response.text)
                return data
            except json.JSONDecodeError as je:
                print(f" [Warning] Failed to parse JSON response: {je}. Raw: {response.text}")
                if attempt == max_retries:
                    raise je
                time.sleep(delay)
                delay *= backoff_factor
            
        except (google.api_core.exceptions.GoogleAPICallError, Exception) as e:
            err_msg = str(e).lower()
            
            # Check for permanent daily quota exhaustion (do not retry, fail fast)
            is_daily_limit = "generaterequestsperday" in err_msg or "daily limit" in err_msg or "per day" in err_msg
            if is_daily_limit:
                print(f"\n    [Permanent Quota Error] Daily request limit exceeded: {e}")
                raise DailyQuotaExhaustedError(f"Daily API request limit exceeded: {e}") from e
                
            # Identify transient errors that can be retried (rate limits, timeouts, server overloads)
            is_transient = any(term in err_msg for term in [
                "429", "resource_exhausted", "rate limit", "quota", 
                "503", "service_unavailable", "500", "internal server error",
                "timeout", "deadline exceeded", "connection", "remote end closed"
            ])
            
            if is_transient and attempt < max_retries:
                print(f"\n    [Transient API Error] {e.__class__.__name__}: {e}. "
                      f"Retrying in {delay:.1f}s (Attempt {attempt}/{max_retries})...", end="", flush=True)
                time.sleep(delay)
                delay *= backoff_factor
            else:
                print(f"\n    [Error] API call failed: {e}")
                raise e
                
    raise Exception(f"Failed to extract stratigraphy for borehole {borehole_name} after {max_retries} attempts.")

