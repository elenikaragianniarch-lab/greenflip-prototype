"""
Step 6 - The sceptic agent.

For each house, Claude reads the evidence from Steps 1-5 (the certificates, the twin's measurements
and the rule-based flags) and decides what is most likely going on: a basement, an extension, a data
error, a misclassified flat, or nothing to worry about.

Rules the agent works under (this is the point of the design):
  - It never does arithmetic or invents numbers. Every figure it may use is in the evidence;
    it may only CHOOSE which floor area to trust, from the values given.
  - Every judgement must cite the evidence it rests on.
  - It must say what would settle the question (e.g. a site visit, a planning record, a new survey).
  - Output is structured (a fixed JSON schema), so code can read it and the map can show it.

Input : data/processed/arlington_checks.json  (Step 5)
Output: outputs/agent_notes.json  and  outputs/agent_notes.csv  (derived judgements, safe to keep)
"""
import json, pathlib, concurrent.futures as cf, anthropic, pandas as pd

MODEL = "claude-sonnet-5-5"
client = anthropic.Anthropic(api_key=pathlib.Path("secrets/anthropic_api_key.txt").read_text().strip())
houses = json.loads(pathlib.Path("data/processed/arlington_checks.json").read_text())
pathlib.Path("outputs").mkdir(exist_ok=True)

SYSTEM = """You are a sceptical data auditor for a retrofit investment platform. You were trained as an architect and
know London terraced housing: many Georgian and Victorian terraces in Camden have a lower ground floor (basement),
rear extensions and loft rooms, none of which appear in a map footprint or an above-ground storey count.

You receive the evidence for ONE house: its Energy Performance Certificate (EPC) history, measurements of a simple
3D model built from map data, and flags raised by rule-based checks. Decide how far the house's data can be trusted
before anyone sizes a heat pump or prices a retrofit from it.

Rules:
- Do not calculate anything and do not invent numbers. Use only figures that appear in the evidence.
- For the floor area, choose one of the values given (an EPC value or the geometry value), or say none can be trusted.
- Cite the evidence for every judgement in plain words.
- Prefer the most ordinary explanation that fits (a basement is more likely than an error in a Camden terrace,
  a 2024 survey is more likely right than a 2009 one), but say how sure you are.
- Say what single piece of evidence would settle it.
Answer only by calling the record_verdict tool."""

TOOL = {
    "name": "record_verdict",
    "description": "Record the audit verdict for one house.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["trust", "use_with_caution", "do_not_use"]},
            "likely_explanation": {"type": "string", "enum": ["consistent", "basement_or_lower_ground", "extension_or_loft", "outdated_certificate", "data_entry_error", "misclassified_not_a_house", "cannot_verify_geometry", "mixed"]},
            "trusted_floor_area_m2": {"type": ["number", "null"], "description": "One of the floor areas given in the evidence, or null."},
            "trusted_floor_area_source": {"type": "string", "description": "Which value was chosen and why, e.g. 'latest EPC (2024)'."},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Your confidence in the data for retrofit use."},
            "reasoning": {"type": "string", "description": "2-4 sentences citing the evidence."},
            "what_would_settle_it": {"type": "string"},
        },
        "required": ["verdict", "likely_explanation", "trusted_floor_area_m2", "trusted_floor_area_source", "confidence", "reasoning", "what_would_settle_it"],
    },
}

KEEP = ["uprn", "address", "n_certs", "first_cert", "latest_cert", "latest_rating", "latest_area_m2", "area_min_m2", "area_max_m2",
        "age_bands", "walls_latest", "cert_age_years", "footprint_m2", "storeys", "storeys_assumed", "geom_floor_area_m2",
        "implied_storeys", "party_wall_m", "exposed_wall_m", "main_facade_faces", "own_footprint", "flags", "confidence"]

def audit(h):
    evidence = {k: h.get(k) for k in KEEP}
    evidence["rule_based_confidence"] = evidence.pop("confidence")
    out = None
    for attempt in range(3):  # this model can't be forced to call the tool, so retry if it answers in text
        msg = client.messages.create(
            model=MODEL, max_tokens=1200, system=SYSTEM, tools=[TOOL], tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": "Evidence for one house on Arlington Road, Camden (NW1 7):\n" + json.dumps(evidence, indent=1, default=str)}],
        )
        out = next((dict(b.input) for b in msg.content if b.type == "tool_use"), None)
        if out: break
    if out is None:
        return {"uprn": h["uprn"], "address": h["address"], "rule_based_confidence": h["confidence"], "verdict": "no_answer"}
    # Guardrail: the trusted floor area must be one of the numbers we gave it
    allowed = {evidence.get(k) for k in ["latest_area_m2", "area_min_m2", "area_max_m2", "geom_floor_area_m2"] if evidence.get(k) is not None}
    if out["trusted_floor_area_m2"] is not None and not any(abs(out["trusted_floor_area_m2"] - a) < 0.6 for a in allowed):
        out["guardrail"] = f"Rejected invented floor area {out['trusted_floor_area_m2']}"
        out["trusted_floor_area_m2"] = None
    return {"uprn": h["uprn"], "address": h["address"], "rule_based_confidence": h["confidence"], **out}

with cf.ThreadPoolExecutor(max_workers=4) as pool:
    notes = list(pool.map(audit, houses))

pathlib.Path("outputs/agent_notes.json").write_text(json.dumps(notes, indent=1, default=str))
df = pd.DataFrame(notes); df.to_csv("outputs/agent_notes.csv", index=False)
print("Verdicts:", df.verdict.value_counts().to_dict())
print("Explanations:", df.likely_explanation.value_counts().to_dict())
print("Guardrail triggered:", df.get("guardrail", pd.Series(dtype=str)).notna().sum())
