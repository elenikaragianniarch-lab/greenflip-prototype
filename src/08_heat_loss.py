"""
Step 8 - Heat loss, element by element, and what to fix first.

For every house with its own twin (Step 4) we estimate, on a design day:
  - how much heat leaves through the walls, roof, ground floor, windows and air leakage (W),
  - the heat pump size it would need now and after fabric upgrades (kW),
  - which measures save the most (kWh/year) - the retrofit priority,
  - rough rooftop solar potential.

Method (a simplified, transparent version of what SAP/RdSAP and MCS heat-loss calculations do):
  heat loss through an element  = U-value (W/m2K) x area (m2) x temperature difference (K)
  heat loss through air leakage = 0.33 x air changes per hour x volume (m3) x temperature difference
  U-values come from the words on the house's own EPC ("Solid brick, as built, no insulation",
  "Pitched, 100 mm loft insulation", "Single glazed"...), mapped to typical values for that construction.
  Areas come from the twin: exposed wall length x height, footprint for roof and floor.

This is indicative, not a SAP assessment: window areas are estimated from floor area, the design day is
fixed at -2 C outside / 21 C inside, and annual demand uses ~2,000 heating degree days for London.
Every assumption is written into the output so it can be challenged.

Inputs : data/processed/arlington_lod1.geojson, arlington_houses_all_certs.csv, arlington_checks.json,
         data/raw/osm/area_buildings.json, outputs/agent_notes.json
Output : data/processed/arlington_heat.json   (per house: elements, measures, wall/roof geometry for the map)
         outputs/arlington_heat_summary.csv
"""
import json, math, pathlib, re, warnings, pandas as pd, pyproj
warnings.filterwarnings("ignore", category=DeprecationWarning)
from shapely.geometry import Polygon, LineString, shape
from shapely.ops import transform
from shapely.strtree import STRtree

T_IN, T_OUT = 21.0, -2.0
DT = T_IN - T_OUT                     # 23 K design temperature difference
HDD = 2000                            # heating degree days, London (approx.)
BOILER_EFF, GAS_CO2 = 0.85, 0.183     # gas boiler efficiency; kg CO2 per kWh of gas (approx.)
HP_SIZES = [4, 5, 6, 7, 8.5, 11, 12, 14, 16]

to_m = pyproj.Transformer.from_crs(4326, 27700, always_xy=True).transform
to_ll = pyproj.Transformer.from_crs(27700, 4326, always_xy=True).transform

# ---------- U-values from the EPC's own words ----------
def u_wall(d):
    d = str(d).lower()
    if "basement" in d: return 0.5
    if "cavity" in d:
        return 0.5 if re.search(r"\binsulated", d) and "no insulation" not in d and "partial" not in d else (1.0 if "partial" in d else 1.5)
    if "system built" in d: return 0.6 if "insulated" in d and "no insulation" not in d else 1.7
    # solid brick (most of this street)
    if "internal insulation" in d or "external insulation" in d or ("insulated" in d and "no insulation" not in d and "partial" not in d): return 0.6
    if "partial" in d: return 1.2
    return 2.1

LOFT = {0: 2.3, 12: 1.5, 25: 1.0, 50: 0.68, 75: 0.5, 100: 0.4, 150: 0.3, 200: 0.21, 250: 0.17, 270: 0.16, 300: 0.14, 350: 0.12, 400: 0.11}
def u_roof(d):
    d = str(d).lower()
    if "dwelling above" in d or "premises above" in d: return 0.0
    m = re.search(r"(\d+)\s*mm", d)
    if m:
        mm = int(m.group(1)); k = min(LOFT, key=lambda x: abs(x - mm)); return LOFT[k]
    if "no insulation" in d: return 2.3
    if "limited" in d: return 1.0
    if "insulated" in d: return 0.35 if "flat" in d else 0.4
    return 1.0

def u_floor(d):
    d = str(d).lower()
    if "below" in d: return 0.0
    if "insulated" in d and "no insulation" not in d and "limited" not in d: return 0.25
    if "limited" in d: return 0.5
    return 0.7 if "suspended" in d else 0.6

def u_window(d, multi_pct):
    d = str(d).lower()
    if "triple" in d: return 1.6
    if "single" in d: return 4.8
    if "full secondary" in d: return 2.4
    if "fully double" in d or "mostly" in d: return 2.8
    p = (multi_pct if pd.notna(multi_pct) else 50) / 100      # partial / some double or secondary glazing
    return round(p * 2.8 + (1 - p) * 4.8, 2)

GLAZE = {"much more than typical": 1.5, "more than typical": 1.25, "normal": 1.0, "less than typical": 0.75, "much less than typical": 0.5}

# ---------- inputs ----------
lod1 = json.loads(pathlib.Path("data/processed/arlington_lod1.geojson").read_text())["features"]
certs = pd.read_csv("data/processed/arlington_houses_all_certs.csv", low_memory=False).sort_values("lodgement_date")
latest = certs.groupby("uprn").tail(1).set_index(certs.groupby("uprn").tail(1).uprn.astype(int).astype(str))
checks = {str(int(c["uprn"])): c for c in json.loads(pathlib.Path("data/processed/arlington_checks.json").read_text())}
notes = {str(int(n["uprn"])): n for n in json.loads(pathlib.Path("outputs/agent_notes.json").read_text())}
osm = [e for e in json.loads(pathlib.Path("data/raw/osm/area_buildings.json").read_text())["elements"] if len(e.get("geometry", [])) >= 4]
others = [transform(to_m, Polygon([(p["lon"], p["lat"]) for p in e["geometry"]])).buffer(0) for e in osm]
tree = STRtree(others)

def facing(nx, ny):
    b = (math.degrees(math.atan2(nx, ny)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((b + 22.5) // 45) % 8]

houses = []
for f in lod1:
    p = f["properties"]; u = str(int(p["uprn"]))
    if u not in latest.index: continue
    e = latest.loc[u]
    poly = transform(to_m, shape(f["geometry"])).buffer(0)
    if poly.geom_type != "Polygon": poly = max(poly.geoms, key=lambda g: g.area)
    height = float(p["height_m"]); storeys = float(p["storeys"])
    note = notes.get(u, {})
    floor_area = note.get("trusted_floor_area_m2") or float(e.total_floor_area)

    # --- walls: classify every edge as party (touches a neighbour) or exposed, keep geometry for the map
    coords = list(poly.exterior.coords); ccw = poly.exterior.is_ccw
    edges, exposed_len = [], 0.0
    for a, b in zip(coords[:-1], coords[1:]):
        seg = LineString([a, b])
        if seg.length < 0.3: continue
        party = any(seg.centroid.distance(others[j].exterior) < 0.35 and others[j].symmetric_difference(poly).area > 1
                    for j in tree.query(seg.buffer(0.35)))
        dx, dy = b[0] - a[0], b[1] - a[1]
        nx, ny = (dy, -dx) if ccw else (-dy, dx)
        if not party: exposed_len += seg.length
        edges.append({"a": list(to_ll(*a)), "b": list(to_ll(*b)), "party": party, "faces": facing(nx, ny), "len": round(seg.length, 2)})

    glaze = GLAZE.get(str(e.glazed_area).lower(), 1.0)
    win_area = round(0.16 * floor_area * glaze, 1)                 # typical window-to-floor ratio, scaled by the EPC's glazing level
    wall_gross = exposed_len * height
    wall_net = max(wall_gross - win_area, 0)
    fh = float(e.floor_height) if pd.notna(e.floor_height) and 2.0 <= float(e.floor_height) <= 3.6 else 2.6
    volume = floor_area * fh
    age = str(e.construction_age_band)
    ach = (0.8 if ("before 1900" in age or "Pre-1900" in age) else 0.6) + 0.15 * min(0 if pd.isna(e.number_open_fireplaces) else float(e.number_open_fireplaces), 3)

    U = {"walls": u_wall(e.walls_description), "roof": u_roof(e.roof_description),
         "floor": u_floor(e.floor_description), "windows": u_window(e.windows_description, e.multi_glaze_proportion)}
    A = {"walls": round(wall_net, 1), "roof": round(poly.area, 1), "floor": round(poly.area, 1), "windows": win_area}

    def loss(U, ach):
        el = {k: U[k] * A[k] * DT for k in U}
        el["air leakage"] = 0.33 * ach * volume * DT
        return el

    base = loss(U, ach)
    total_w = sum(base.values())
    kwh = lambda w: w / DT * HDD * 24 / 1000

    # --- measures: each tested on its own against today's house, then ranked by what it saves
    candidates = []
    def test(name, why, U2=None, ach2=None):
        after = loss(U2 or U, ach2 if ach2 is not None else ach)
        saved_w = total_w - sum(after.values())
        if saved_w > 50:
            candidates.append({"measure": name, "why": why, "saves_kw": round(saved_w / 1000, 2),
                               "saves_kwh_yr": round(kwh(saved_w)), "saves_co2_t_yr": round(kwh(saved_w) / BOILER_EFF * GAS_CO2 / 1000, 2)})
    if U["roof"] > 0.25: test("Roof / loft insulation", f"roof U {U['roof']} -> 0.16", {**U, "roof": 0.16})
    if U["walls"] > 0.7: test("Solid-wall insulation", f"walls U {U['walls']} -> 0.30 (internal at the front, external at the rear)", {**U, "walls": 0.30})
    if U["windows"] > 2.0: test("Glazing upgrade", f"windows U {U['windows']} -> 1.4 (slim double or secondary glazing)", {**U, "windows": 1.4})
    if U["floor"] > 0.4: test("Ground floor insulation", f"floor U {U['floor']} -> 0.25", {**U, "floor": 0.25})
    test("Draught-proofing", f"air changes {ach:.2f} -> {ach*0.7:.2f} per hour", ach2=ach * 0.7)
    candidates.sort(key=lambda m: -m["saves_kwh_yr"])

    fabric_U = {k: min(U[k], v) if U[k] > 0 else 0 for k, v in {"walls": 0.30, "roof": 0.16, "floor": 0.25, "windows": 1.4}.items()}
    after_all = sum(loss(fabric_U, ach * 0.7).values())
    hp = lambda w: next((s for s in HP_SIZES if s >= w / 1000), HP_SIZES[-1])
    solar_kwp = round(0.4 * poly.area * 0.2, 1) if U["roof"] > 0 else 0       # ~40% of roof usable, ~0.2 kWp per m2

    c = checks.get(u, {})
    houses.append({
        "uprn": u, "address": c.get("address"), "height": height, "storeys": storeys, "storeys_assumed": bool(p.get("storeys_assumed")),
        "roof": [list(to_ll(*xy)) for xy in poly.exterior.coords], "edges": edges,
        "floor_area": floor_area, "floor_area_source": note.get("trusted_floor_area_source") or "latest EPC",
        "U": U, "A": A, "ach": round(ach, 2),
        "loss_w": {k: round(v) for k, v in base.items()}, "total_kw": round(total_w / 1000, 2),
        "flux": {"walls": round(U["walls"] * DT, 1), "roof": round(U["roof"] * DT, 1)},     # W per m2 on the design day
        "annual_kwh": round(kwh(total_w)), "kwh_per_m2": round(kwh(total_w) / floor_area),
        "hp_now_kw": hp(total_w), "hp_after_kw": hp(after_all), "after_fabric_kw": round(after_all / 1000, 2),
        "saving_all_kwh": round(kwh(total_w - after_all)), "measures": candidates,
        "solar_kwp": solar_kwp, "solar_kwh_yr": round(solar_kwp * 850),
        "epc": {"walls": e.walls_description, "roof": e.roof_description, "floor": e.floor_description,
                "windows": e.windows_description, "heating": e.mainheat_description, "rating": e.current_energy_rating,
                "date": str(e.lodgement_date)[:10]},
        "trust": {"verdict": note.get("verdict"), "explanation": note.get("likely_explanation"), "confidence": note.get("confidence"),
                  "reasoning": note.get("reasoning"), "settle": note.get("what_would_settle_it")},
    })

# Retrofit priority: rank by what a full fabric package saves - but only houses whose data the agent will stand behind.
# "Do not use" houses get no rank: fix the data first, then decide.
# Risk-adjusted: an investor discounts a saving by how sure we are of the data behind it.
for h in houses:
    h["confidence"] = h["trust"]["confidence"] if h["trust"]["confidence"] is not None else 50
    h["risk_adjusted_kwh"] = round(h["saving_all_kwh"] * h["confidence"] / 100)
houses.sort(key=lambda h: -h["risk_adjusted_kwh"])
rank = 0
for h in houses:
    if h["trust"]["verdict"] == "do_not_use":
        h["priority_rank"] = None
    else:
        rank += 1; h["priority_rank"] = rank
    h["hp_now_label"] = f"{h['hp_now_kw']:g}" if h["total_kw"] <= HP_SIZES[-1] else f">{HP_SIZES[-1]:g}"
pathlib.Path("data/processed/arlington_heat.json").write_text(json.dumps({
    "assumptions": {"design_day": f"{T_IN:g} C inside, {T_OUT:g} C outside", "heating_degree_days": HDD,
                    "window_area": "16% of floor area x EPC glazing level", "boiler_efficiency": BOILER_EFF, "gas_kgco2_per_kwh": GAS_CO2},
    "houses": houses}, default=str))

rows = [{"address": h["address"], "rank": h["priority_rank"], "total_kw": h["total_kw"], "hp_now_kw": h["hp_now_kw"], "hp_after_kw": h["hp_after_kw"],
         "walls_w": h["loss_w"]["walls"], "roof_w": h["loss_w"]["roof"], "windows_w": h["loss_w"]["windows"], "floor_w": h["loss_w"]["floor"],
         "air_w": h["loss_w"]["air leakage"], "top_measure": h["measures"][0]["measure"] if h["measures"] else None,
         "saving_all_kwh": h["saving_all_kwh"], "risk_adjusted_kwh": h["risk_adjusted_kwh"], "trust": h["trust"]["verdict"]} for h in houses]
df = pd.DataFrame(rows); pathlib.Path("outputs").mkdir(exist_ok=True); df.to_csv("outputs/arlington_heat_summary.csv", index=False)

tot = {k: sum(h["loss_w"][k] for h in houses) for k in ["walls", "roof", "windows", "floor", "air leakage"]}
T = sum(tot.values())
print(f"Houses modelled: {len(houses)}")
print("Street heat loss on a design day:", {k: f"{100*v/T:.0f}%" for k, v in tot.items()}, f"total {T/1000:.0f} kW")
print("Heat pump now (median kW):", df.hp_now_kw.median(), "| after fabric:", df.hp_after_kw.median())
print("Top measure across houses:", df.top_measure.value_counts().to_dict())
print("Ranked:", df["rank"].notna().sum(), "| held back (do not use):", df["rank"].isna().sum())
print(df.sort_values("rank").head(8)[["address", "total_kw", "hp_now_kw", "hp_after_kw", "top_measure", "saving_all_kwh", "risk_adjusted_kwh", "trust"]].to_string(index=False))
