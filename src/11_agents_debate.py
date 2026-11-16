"""
Step 11 - Three agents per building, and they are built to disagree.

  1. SCEPTIC      audits the data: can this building's records be trusted?            (Step 6, extended to flats)
  2. STRATEGIST   proposes a retrofit package from the measures the model costed.
  3. CHALLENGER   attacks the plan using the sceptic's doubts and practical risks, then rules:
                  fund now / survey first / fix data first, with the one condition that would change it.
Then two street-level memos (investor, council) written only from the totals the code computed.

Guardrails: agents answer through fixed forms (tools). They may only pick measures from the costed list
and may not introduce numbers; code checks the picks and recomputes every total itself.

Input : data/processed/street_buildings.json (Step 10)
Output: outputs/agents.json   (cached per building, so a re-run only calls for what is missing)
"""
import json, pathlib, concurrent.futures as cf, anthropic

MODEL = "claude-sonnet-5-5"
client = anthropic.Anthropic(api_key=pathlib.Path("secrets/anthropic_api_key.txt").read_text().strip(), max_retries=4)
data = json.loads(pathlib.Path("data/processed/street_buildings.json").read_text())
B = data["buildings"]
OUT = pathlib.Path("outputs/agents.json"); OUT.parent.mkdir(exist_ok=True)
cache = json.loads(OUT.read_text()) if OUT.exists() else {"buildings": {}, "memos": {}}

CONTEXT = """Context: Arlington Road, Camden Town, London NW1. Mostly early-19th-century brick terraces (many now flats) plus
later blocks. Terraces of this age often have a lower ground floor, rear extensions and loft rooms that maps do not show.
Many may be listed or in a conservation area: external insulation on street fronts and window replacement can need consent,
so treat that as a risk to check, never as a known fact. The numbers come from an indicative model (U-values read from the
EPC wording x areas from a simple 3D twin). Do not calculate and do not introduce any number that is not in the evidence."""

def call(system, tool, payload):
    for _ in range(3):
        msg = client.messages.create(model=MODEL, max_tokens=900, system=system + "\n\n" + CONTEXT, tools=[tool], tool_choice={"type": "auto"},
                                     messages=[{"role": "user", "content": json.dumps(payload, default=str)}])
        out = next((dict(b.input) for b in msg.content if b.type == "tool_use"), None)
        if out: return out
    return None

SCEPTIC_T = {"name": "record_audit", "description": "Record the data audit for one building.", "input_schema": {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["trust", "use_with_caution", "do_not_use"]},
    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
    "reasoning": {"type": "string", "description": "Max 2 short sentences citing the evidence."},
    "what_would_settle_it": {"type": "string", "description": "One short sentence."}},
    "required": ["verdict", "confidence", "reasoning", "what_would_settle_it"]}}
STRAT_T = {"name": "record_plan", "description": "Record the retrofit plan for one building.", "input_schema": {"type": "object", "properties": {
    "package": {"type": "array", "items": {"type": "string"}, "description": "Measure keys chosen from the list given, in the order to do them."},
    "heat_pump": {"type": "string", "enum": ["ready_now", "after_fabric", "not_yet"]},
    "why": {"type": "string", "description": "Max 2 short sentences: why this package and this order."},
    "overheating_action": {"type": "string", "description": "One short sentence, or 'none needed'."},
    "investor_line": {"type": "string", "description": "One sentence an investor would care about."},
    "council_line": {"type": "string", "description": "One sentence a council or social landlord would care about."}},
    "required": ["package", "heat_pump", "why", "overheating_action", "investor_line", "council_line"]}}
CHALL_T = {"name": "record_ruling", "description": "Challenge the plan and rule on it.", "input_schema": {"type": "object", "properties": {
    "objections": {"type": "array", "items": {"type": "string"}, "maxItems": 3, "description": "Short, specific objections."},
    "decision": {"type": "string", "enum": ["fund_now", "survey_first", "fix_data_first"]},
    "approved_package": {"type": "array", "items": {"type": "string"}, "description": "Measure keys from the plan that can start now, before any survey."},
    "condition": {"type": "string", "description": "The one thing that would change the decision. One short sentence."}},
    "required": ["objections", "decision", "approved_package", "condition"]}}

def evidence(b):
    return {"name": b["name"], "kind": b["kind"], "homes_certified": b["homes_certified"], "homes_estimated": b["homes"], "storeys": b["storeys"],
            "storeys_assumed": b["storeys_assumed"], "built": b["age"], "epc_says": b["epc_words"], "epc_ratings": b["ratings"], "tenure": b["tenure"],
            "data_flags": b["flags"], "rule_based_confidence": b["rule_conf"], "certificate_sensitivity": b["sensitivity"]}

def run(b):
    try: return _run(b)
    except Exception as e:
        print("failed:", b["name"], type(e).__name__); return b["id"], cache["buildings"].get(b["id"], {})

def _run(b):
    r = cache["buildings"].get(b["id"], {})
    if "sceptic" not in r:
        if b["sceptic"]:
            s = b["sceptic"]; r["sceptic"] = {"verdict": s["verdict"], "confidence": s["confidence"], "reasoning": s["reasoning"], "what_would_settle_it": s["what_would_settle_it"]}
        else:
            r["sceptic"] = call("You are the SCEPTIC: a data auditor trained as an architect. Decide how far this building's records can be trusted for retrofit investment. Answer with the record_audit tool.", SCEPTIC_T, evidence(b))
    if r.get("sceptic"):
        r["sceptic"].setdefault("verdict", "use_with_caution"); r["sceptic"].setdefault("confidence", 50); r["sceptic"].setdefault("reasoning", ""); r["sceptic"].setdefault("what_would_settle_it", "")
    if r.get("sceptic") and "plan" not in r:
        ev = {**evidence(b), "heat_loss_share_pct": {k: round(100 * v / max(1, sum(b["loss_w"].values()))) for k, v in b["loss_w"].items()},
              "peak_kw": b["total_kw"], "costed_measures": [{k: m[k] for k in ["key", "measure", "capex", "saves_gbp", "payback_yrs", "saves_co2_t"]} for m in b["measures"]],
              "heat_pump_per_home_kw": {"today": b["hp"]["per_home_now_kw"], "after_fabric": b["hp"]["per_home_after_kw"]}, "heat_pump_grant_available": b["hp"]["grant"] > 0,
              "overheating": {k: b["overheat"][k] for k in ["band", "where", "drivers"]}}
        p = call("You are the RETROFIT STRATEGIST for an investment platform. Propose the package you would fund for this building, choosing only from costed_measures (use their keys). Favour short paybacks first, then what makes a heat pump viable. Answer with the record_plan tool.", STRAT_T, ev)
        if p:
            valid = {m["key"] for m in b["measures"]}; p["package"] = [k for k in (p.get("package") or []) if k in valid]
            for k in ["why", "overheating_action", "investor_line", "council_line"]: p.setdefault(k, "")
            p.setdefault("heat_pump", "after_fabric")
            r["plan"] = p
    if r.get("plan") and "ruling" not in r:
        ev = {"building": evidence(b), "data_audit": r["sceptic"], "strategist_plan": r["plan"],
              "costed_measures": [{k: m[k] for k in ["key", "capex", "payback_yrs"]} for m in b["measures"]], "overheating_band": b["overheat"]["band"]}
        g = call("You are the CHALLENGER. Find what is wrong with the strategist's plan before money is spent: data doubts from the audit, assumptions each saving depends on, heritage and practical risks, overheating. Then split the plan measure by measure. Put in approved_package every measure that can start now because its saving does not hinge on the doubtful inputs (typically draught-proofing, and roof insulation when a certificate records the roof); leave out measures that need a survey or consent first (typically wall insulation and glazing on old terraces). Be commercially useful: blocking every measure is a failure unless the data is unusable. Answer with the record_ruling tool.", CHALL_T, ev)
        if g:
            g["approved_package"] = [k for k in (g.get("approved_package") or []) if k in r["plan"]["package"]]
            g.setdefault("objections", []); g.setdefault("condition", ""); g.setdefault("decision", "survey_first")
            # the decision is derived by code from the split, so it cannot contradict it
            if r["sceptic"]["verdict"] == "do_not_use": g["decision"] = "fix_data_first"; g["approved_package"] = []
            else: g["decision"] = "fund_now" if g["approved_package"] else "survey_first"
            r["ruling"] = g
    return b["id"], r

with cf.ThreadPoolExecutor(max_workers=6) as pool:
    for i, (bid, r) in enumerate(pool.map(run, B), 1):
        cache["buildings"][bid] = r
        if i % 15 == 0: OUT.write_text(json.dumps(cache, indent=1))
OUT.write_text(json.dumps(cache, indent=1))

# ---- totals computed by code from the rulings, then handed to the memo writer ----
R = cache["buildings"]; byid = {b["id"]: b for b in B}
def tot(ids, pick):
    cap = gbp = co2 = 0
    for i in ids:
        for m in byid[i]["measures"]:
            if m["key"] in pick(i): cap += m["capex"]; gbp += m["saves_gbp"]; co2 += m["saves_co2_t"]
    return {"capex_gbp": round(cap, -3), "bill_saving_gbp_per_year": round(gbp, -2), "co2_saved_t_per_year": round(co2), "simple_payback_years": round(cap / gbp, 1) if gbp else None}
dec = {d: [i for i, r in R.items() if r.get("ruling", {}).get("decision") == d] for d in ["fund_now", "survey_first", "fix_data_first"]}
totals = {"buildings": len(B), "homes_with_certificates": data["meta"]["placed"], "tenure_of_homes": data["meta"]["tenure"], "epc_ratings_of_homes": data["meta"]["ratings"],
          "decisions": {k: len(v) for k, v in dec.items()},
          "approved_now": tot([i for i in R if R[i].get("ruling")], lambda i: R[i]["ruling"]["approved_package"]),
          "full_fabric_if_all_confirmed": tot(list(byid), lambda i: [m["key"] for m in byid[i]["measures"]]),
          "after_survey": tot([i for i in R if R[i].get("ruling")], lambda i: [k for k in R[i]["plan"]["package"] if k not in R[i]["ruling"]["approved_package"]]),
          "survey_visits_needed": sum(1 for i in R if R[i].get("ruling") and set(R[i]["plan"]["package"]) - set(R[i]["ruling"]["approved_package"])), "survey_cost_each_gbp": data["assumptions"]["unit costs (GBP)"]["survey"],
          "overheating_high_buildings": sum(b["overheat"]["band"] == "high" for b in B),
          "peak_heat_loss_kw": round(sum(b["total_kw"] for b in B))}
cache["totals"] = totals
MEMO_T = {"name": "record_memo", "description": "Record a short memo.", "input_schema": {"type": "object", "properties": {
    "headline": {"type": "string", "description": "One sentence, max 22 words."}, "points": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3, "description": "Three short points."},
    "ask": {"type": "string", "description": "The next step you recommend, one sentence."}}, "required": ["headline", "points", "ask"]}}
for who, brief in {"investor": "a property investor or asset manager who wants return, risk and where to deploy capital first",
                   "council": "a council or social landlord who wants carbon, fuel poverty, tenant comfort, compliance and how to spend a fixed budget"}.items():
    if who not in cache["memos"]:
        cache["memos"][who] = call(f"Write a memo for {brief}. Use only the figures given; quote them exactly; no new numbers. Plain English. Answer with the record_memo tool.", MEMO_T, totals)
OUT.write_text(json.dumps(cache, indent=1))
print("decisions:", totals["decisions"]); print("approved now:", totals["approved_now"]); print("full fabric:", totals["full_fabric_if_all_confirmed"])
print("after survey:", totals["after_survey"], "| visits:", totals["survey_visits_needed"]); print("missing:", sum(1 for b in B if "ruling" not in R.get(b["id"], {})))
print(json.dumps(cache["memos"]["investor"], indent=1)[:700])
