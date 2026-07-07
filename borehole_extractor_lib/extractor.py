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
    "1. Disregard peripheral columns (flushing medium, shift times, coordinates, core photos). "
    "Focus entirely on the depth column and the soil/rock description column.\n"
    "2. Output Start Depth and End Depth as numeric values in metres only (e.g. 10.50, not '10.50m').\n"
    "3. Depth ranges must be STRICTLY CONTINUOUS: End Depth of row N must equal Start Depth of row N+1. "
    "If a gap exists in the log, bridge it with a 'No recovery' entry.\n"
    "4. Every layer's Start Depth must be LESS THAN its End Depth. "
    "Do not emit rows where Start Depth >= End Depth.\n"
    "5. Depth ranges must be in STRICTLY INCREASING order. Do not repeat or emit overlapping depth ranges.\n"
    "6. Do NOT emit duplicate rows. If the same depth range appears more than once, output it only once.\n"
    "7. If a thick stratum spans multiple log sheets, it will appear on each sheet as a separate entry. "
    "Merge them into a SINGLE row covering the full combined depth range with the same description.\n"
    "8. When a layer description reads 'As Sheet X', 'Per Sheet X', or 'Refer to Sheet X', "
    "do NOT output that string. Instead, find the actual material description on Sheet X and use it.\n"
    "9. The final row's End Depth must equal the total termination depth of the borehole "
    "(usually written at the bottom-left corner of the last log sheet).\n"
    "10. Classify a concise Soil/Rock Type (e.g. Sand, Clay, Granite, Fill, No Recovery).\n"
    "11. Set Confidence Level to 'High', 'Medium', or 'Low' based on legibility of the scanned image.\n\n"
    "OUTPUT FORMAT:\n"
    "Provide the output STRICTLY as raw CSV text with the following headers (no markdown code blocks):\n"
    "Hole No,Sheet No,Start Depth,End Depth,Soil/Rock Description,Soil/Rock Type,Confidence Level"
)


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
) -> str:
    """
    Calls the Gemini API to extract stratigraphy from a list of PIL images.
    Implements exponential backoff to handle rate limits (429), server errors (5xx), and timeouts.
    """
    contents = list(images)
    contents.append(
        f"Please extract the stratigraphy table for borehole '{borehole_name}' from the provided log images. "
        "Provide the output strictly as raw CSV text matching the headers and formatting specified in the system instructions. "
        "Do not wrap the CSV in markdown code blocks."
    )
    
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            response = model.generate_content(contents)
            
            if not response or not response.text:
                print(f" [Warning] Received empty response from Gemini for borehole {borehole_name}.")
                return ""
            return response.text
            
        except (google.api_core.exceptions.GoogleAPICallError, Exception) as e:
            err_msg = str(e).lower()
            
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
