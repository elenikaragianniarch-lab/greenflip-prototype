"""
Step 10 - Every building on the street, not just the single houses.

Most homes on Arlington Road are flats. This step takes EVERY dwelling with an energy certificate,
places it in its building, and builds one twin per building: geometry, heat loss by element,
overheating risk, retrofit measures with cost, bill saving, payback and carbon, and data checks.

Inputs : data/processed/arlington_all_certs.csv   (all certificates on the street, all property types)
         data/raw/os/uprns.geojson, data/raw/osm/area_buildings.json
         outputs/agent_notes.json                  (Step 6 verdicts for single houses, reused)
Output : data/processed/street_buildings.json

Everything here is plain arithmetic with stated assumptions (see ASSUMPTIONS). No AI in this step.
"""
import json, math, pathlib, re, warnings, pandas as pd, pyproj
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import transform
from shapely.strtree import STRtree
warnings.filterwarnings("ignore")

T_IN, T_OUT, HDD = 21.0, -2.0, 2000
DT = T_IN - T_OUT
GAS_P, ELEC_P = 0.0797, 0.2632          # GBP per kWh, Ofgem price cap Oct-Dec 2026
BOILER_EFF, SCOP = 0.85, 3.2
GAS_CO2, ELEC_CO2 = 0.183, 0.13         # kg CO2e per kWh (approx.)
BUS_GRANT = 7500                        # Boiler Upgrade Scheme, air-to-water heat pump, gas homes
COST = {"roof_loft": 25, "roof_flat": 120, "walls": 150, "windows": 500, "floor": 90,   # GBP per m2 (indicative)
        "draught": 600, "hp_base": 6500, "hp_per_kw": 600, "solar_per_kwp": 1500, "shading": 1500, "survey": 400}
HP_SIZES = [4, 5, 6, 7, 8.5, 11, 12, 14, 16]
ASSUMPTIONS = {
    "design day": f"{T_IN:g} C inside, {T_OUT:g} C outside", "heating degree days": HDD,
    "prices": f"gas {GAS_P*100:.2f}p, electricity {ELEC_P*100:.2f}p per kWh (Ofgem cap, Oct-Dec 2026)",
    "boiler efficiency": BOILER_EFF, "heat pump seasonal efficiency (SCOP)": SCOP,
    "carbon": f"gas {GAS_CO2}, electricity {ELEC_CO2} kg CO2e/kWh",
    "grant": f"Boiler Upgrade Scheme {BUS_GRANT} GBP per heat pump (private homes; social housing generally excluded)",
    "unit costs (GBP)": COST, "window area": "16% of floor area x EPC glazing level, capped at 45% of exposed wall",
    "storey height": "3.0 m", "status": "indicative model, not a SAP/PAS 2035 assessment",
}

to_m = pyproj.Transformer.from_crs(4326, 27700, always_xy=True).transform
to_ll = pyproj.Transformer.from_crs(27700, 4326, always_xy=True).transform

def u_wall(d):
    d = str(d).lower()
    if "basement" in d: return 0.5
    ins = ("insulated" in d or "internal insulation" in d or "external insulation" in d) and "no insulation" not in d and "partial" not in d
    if "cavity" in d: return 0.5 if ins else (1.0 if "partial" in d else 1.5)
    if "system" in d or "timber" in d: return 0.6 if ins else 1.7
    return 0.6 if ins else (1.2 if "partial" in d else 2.1)
LOFT = {0: 2.3, 12: 1.5, 25: 1.0, 50: 0.68, 75: 0.5, 100: 0.4, 150: 0.3, 200: 0.21, 250: 0.17, 270: 0.16, 300: 0.14, 400: 0.11}
def u_roof(d):
    d = str(d).lower()
    if "above" in d: return 0.0
    m = re.search(r"(\d+)\s*\+?\s*mm", d)
    if m: return LOFT[min(LOFT, key=lambda x: abs(x - int(m.group(1))))]
    if "no insulation" in d: return 2.3
    if "limited" in d: return 1.0
    if "insulated" in d: return 0.35
    return 1.0
def u_floor(d):
    d = str(d).lower()
    if "below" in d: return 0.0
    if "insulated" in d and "no insulation" not in d and "limited" not in d: return 0.25
    return 0.5 if "limited" in d else (0.7 if "suspended" in d else 0.6)
def u_win(d, pct):
    d = str(d).lower()
    if "triple" in d: return 1.6
    if "single" in d: return 4.8
    if "full secondary" in d: return 2.4
    if "fully" in d or "mostly" in d or "high performance" in d: return 2.8
    p = (pct if pd.notna(pct) else 50) / 100
    return round(p * 2.8 + (1 - p) * 4.8, 2)
GLAZE = {"much more than typical": 1.5, "more than typical": 1.25, "normal": 1.0, "less than typical": 0.75, "much less than typical": 0.5}
def facing(nx, ny):
    b = (math.degrees(math.atan2(nx, ny)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((b + 22.5) // 45) % 8]
SUN = {"S": 1.0, "SW": 1.0, "W": 0.9, "SE": 0.7, "E": 0.5, "NW": 0.3, "NE": 0.2, "N": 0.0}
hp_size = lambda kw: next((s for s in HP_SIZES if s >= kw), None)
kwh = lambda w: w / DT * HDD * 24 / 1000

# ---------------- dwellings ----------------
c = pd.read_csv("data/processed/arlington_all_certs.csv", low_memory=False)
c["lodgement_date"] = pd.to_datetime(c.lodgement_date)
c["key"] = c.address.str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
known = c.dropna(subset=["uprn"]).groupby("key").uprn.agg(lambda u: u.iloc[0] if u.nunique() == 1 else None)
n_missing = int(c.uprn.isna().sum())
c["uprn_recovered"] = c.uprn.isna() & c.key.map(known).notna()
c["uprn"] = c.uprn.fillna(c.key.map(known))
c["house_no"] = c.address1.str.extract(r"^\s*(\d+[A-Za-z]?)[ ,]")[0]
hk = c[(c.property_type == "House")].dropna(subset=["uprn"]).groupby("house_no").uprn.agg(lambda u: u.iloc[0] if u.nunique() == 1 else None)
m = c.uprn.isna() & (c.property_type == "House") & c.house_no.map(hk).notna()
c.loc[m, "uprn_recovered"] = True; c.loc[m, "uprn"] = c.house_no.map(hk)
n_recovered = int(c.uprn_recovered.sum()); c = c.dropna(subset=["uprn"]); c["uprn"] = c.uprn.astype("int64")
c["tenure_n"] = c.tenure.str.lower().map(lambda t: "social rent" if "social" in str(t) else "private rent" if "private" in str(t) else "owner-occupied" if "owner" in str(t) else "unknown")
c["age_n"] = c.construction_age_band.astype(str).str.replace("England and Wales: ", "").str.replace("Pre-1900", "before 1900")
c = c.sort_values("lodgement_date")
latest = c.groupby("uprn").tail(1).set_index("uprn")

pts = {int(f["properties"]["UPRN"]): (f["properties"]["Longitude"], f["properties"]["Latitude"])
       for f in json.loads(pathlib.Path("data/raw/os/uprns.geojson").read_text())["features"]}
osm = [e for e in json.loads(pathlib.Path("data/raw/osm/area_buildings.json").read_text())["elements"] if len(e.get("geometry", [])) >= 4]
polys = []
for e in osm:
    p = transform(to_m, Polygon([(q["lon"], q["lat"]) for q in e["geometry"]])).buffer(0)
    polys.append(max(p.geoms, key=lambda g: g.area) if p.geom_type != "Polygon" else p)
tree = STRtree(polys)
notes = {int(n["uprn"]): n for n in json.loads(pathlib.Path("outputs/agent_notes.json").read_text())} if pathlib.Path("outputs/agent_notes.json").exists() else {}

assign, unplaced = {}, 0
for u in latest.index:
    if u not in pts: unplaced += 1; continue
    pt = Point(to_m(*pts[u]))
    hit = [j for j in tree.query(pt.buffer(4)) if polys[j].distance(pt) < 4]
    if not hit: unplaced += 1; continue
    assign.setdefault(min(hit, key=lambda j: polys[j].distance(pt)), []).append(u)

def losses(U, A, ach, vol):
    el = {k: U[k] * A[k] * DT for k in U}; el["air leakage"] = 0.33 * ach * vol * DT; return el

buildings = []
for j, uprns in assign.items():
    poly, tags = polys[j], osm[j]["tags"]
    D = latest.loc[uprns]
    single_house = len(uprns) == 1 and D.property_type.iloc[0] == "House" and poly.area < 300 and "flat" not in str(D.address1.iloc[0]).lower() and "room" not in str(D.address1.iloc[0]).lower()
    try: lv = float(tags.get("building:levels"))
    except (TypeError, ValueError): lv = None
    sum_area = float(D.total_floor_area.sum())
    if lv: storeys, assumed = lv, False
    elif single_house: storeys, assumed = 3.0, True
    else:
        fsc = pd.to_numeric(D.flat_storey_count, errors="coerce").max()
        storeys, assumed = float(min(10, max(3, fsc if pd.notna(fsc) and fsc < 12 else 0, math.ceil(sum_area / (poly.area * 0.8))))), True
    height = storeys * 3.0
    note = notes.get(int(uprns[0])) if single_house else None
    gia = float((note or {}).get("trusted_floor_area_m2") or D.total_floor_area.iloc[0]) if single_house else round(poly.area * storeys * 0.85, 1)
    mean_dw = float(D.total_floor_area.median()) or 60
    homes = 1 if single_house else max(len(uprns), round(gia / max(mean_dw, 25)))

    # geometry: exposed vs party edges
    ring = list(poly.exterior.coords); ccw = poly.exterior.is_ccw
    edges, exp_len, sun_w = [], 0.0, 0.0
    for a, b in zip(ring[:-1], ring[1:]):
        seg = LineString([a, b])
        if seg.length < 0.3: continue
        party = any(k != j and seg.centroid.distance(polys[k].exterior) < 0.35 for k in tree.query(seg.buffer(0.35)))
        dx, dy = b[0] - a[0], b[1] - a[1]; nx, ny = (dy, -dx) if ccw else (-dy, dx); fc = facing(nx, ny)
        if not party: exp_len += seg.length; sun_w += seg.length * SUN[fc]
        edges.append({"a": list(to_ll(*a)), "b": list(to_ll(*b)), "party": party, "faces": fc, "len": round(seg.length, 1)})
    sun_share = sun_w / exp_len if exp_len else 0
    exp_faces = {}
    for e in edges:
        if not e["party"]: exp_faces[e["faces"]] = exp_faces.get(e["faces"], 0) + e["len"]
    sunny = max((f for f in exp_faces if SUN[f] >= 0.7), key=lambda f: exp_faces[f], default=None)

    # fabric from the dwellings' own certificates
    uw = [u_wall(x) for x in D.walls_description]; ur = [x for x in (u_roof(d) for d in D.roof_description) if x > 0]
    uf = [x for x in (u_floor(d) for d in D.floor_description) if x > 0]; ug = [u_win(d, p) for d, p in zip(D.windows_description, D.multi_glaze_proportion)]
    U = {"walls": round(sum(uw) / len(uw), 2), "roof": round(sum(ur) / len(ur), 2) if ur else 1.0,
         "floor": round(sum(uf) / len(uf), 2) if uf else 0.6, "windows": round(sum(ug) / len(ug), 2)}
    glaze = sum(GLAZE.get(str(g).lower(), 1.0) for g in D.glazed_area) / len(D)
    wall_gross = exp_len * height
    win = round(min(0.16 * gia * glaze, 0.45 * wall_gross), 1)
    A = {"walls": round(max(wall_gross - win, 0), 1), "roof": round(poly.area, 1), "floor": round(poly.area, 1), "windows": win}
    old = D.age_n.str.contains("before 1900|1900-1929").mean() > 0.5
    ach = 0.8 if old else 0.6
    fh = pd.to_numeric(D.floor_height, errors="coerce"); fh = float(fh[(fh >= 2) & (fh <= 3.6)].median()) if ((fh >= 2) & (fh <= 3.6)).any() else 2.6
    vol = gia * fh
    base = losses(U, A, ach, vol); total = sum(base.values())
    flat_roof = D.roof_description.astype(str).str.lower().str.contains("flat").mean() > 0.5

    # measures: each tested alone, with cost, bill saving, payback, carbon
    measures = []
    def add(name, key, capex, U2=None, ach2=None, why=""):
        saved = total - sum(losses(U2 or U, A, ach2 or ach, vol).values())
        if saved < 50: return
        k = kwh(saved); gbp = k / BOILER_EFF * GAS_P
        measures.append({"measure": name, "key": key, "why": why, "capex": round(capex, -2), "saves_kwh": round(k), "saves_gbp": round(gbp),
                         "saves_co2_t": round(k / BOILER_EFF * GAS_CO2 / 1000, 2), "payback_yrs": round(capex / gbp, 1) if gbp else None, "saves_kw": round(saved / 1000, 2)})
    if U["roof"] > 0.25: add("Roof insulation", "roof", A["roof"] * COST["roof_flat" if flat_roof else "roof_loft"], {**U, "roof": 0.16}, why=f"U {U['roof']} to 0.16")
    if U["walls"] > 0.7: add("Wall insulation", "walls", A["walls"] * COST["walls"], {**U, "walls": 0.30}, why=f"U {U['walls']} to 0.30")
    if U["windows"] > 2.0: add("Glazing upgrade", "windows", A["windows"] * COST["windows"], {**U, "windows": 1.4}, why=f"U {U['windows']} to 1.4")
    if U["floor"] > 0.4: add("Floor insulation", "floor", A["floor"] * COST["floor"], {**U, "floor": 0.25}, why=f"U {U['floor']} to 0.25")
    add("Draught-proofing", "air", COST["draught"] * homes, ach2=ach * 0.7, why="30% less air leakage")
    measures.sort(key=lambda m: m["payback_yrs"] or 999)

    Uf = {k: min(U[k], t) for k, t in {"walls": 0.30, "roof": 0.16, "floor": 0.25, "windows": 1.4}.items()}
    after = sum(losses(Uf, A, ach * 0.7, vol).values())
    per_home_now, per_home_after = total / homes / 1000, after / homes / 1000
    hp_now, hp_after = hp_size(per_home_now), hp_size(per_home_after)
    heat_after = kwh(after)
    hp_capex = homes * (COST["hp_base"] + COST["hp_per_kw"] * (hp_after or 16))
    social = (D.tenure_n == "social rent").mean() > 0.5
    hp = {"now_kw": hp_now, "after_kw": hp_after, "now_label": f"{hp_now:g}" if hp_now else ">16", "per_home_now_kw": round(per_home_now, 1), "per_home_after_kw": round(per_home_after, 1),
          "capex": round(hp_capex, -2), "grant": 0 if social else BUS_GRANT * homes,
          "bill_change_gbp": round(heat_after / SCOP * ELEC_P - heat_after / BOILER_EFF * GAS_P),
          "co2_saved_t": round((heat_after / BOILER_EFF * GAS_CO2 - heat_after / SCOP * ELEC_CO2) / 1000, 2)}
    fab_capex = sum(m["capex"] for m in measures); fab_kwh = kwh(total - after); fab_gbp = fab_kwh / BOILER_EFF * GAS_P
    quick = [m for m in measures if (m["payback_yrs"] or 99) <= 10]

    # overheating (0-100): sun-facing glazing, hot roof, single-aspect flats, city heat island, thermal mass
    oh = 40 * sun_share * min(glaze, 1.5) + (25 if U["roof"] > 1 else 12 if U["roof"] > 0.35 else 5) + (0 if single_house else 15) + 10 - (5 if U["walls"] > 1.5 and old else 0)
    oh = int(max(0, min(100, round(oh))))
    over = {"score": oh, "band": "high" if oh >= 60 else "medium" if oh >= 40 else "low",
            "where": f"top floor{', ' + sunny + '-facing rooms' if sunny else ''}", "sunny_face": sunny,
            "drivers": [x for x in [f"{round(100*sun_share)}% of exposed wall faces the sun" if sun_share > 0.3 else None,
                                    "roof poorly insulated: top floor heats up" if U["roof"] > 1 else None,
                                    "flats, likely single-aspect" if not single_house else None, "London heat island"] if x],
            "note": "Roof insulation also cuts summer heat gain; add shading and night ventilation with any fabric upgrade."}

    # data checks at building level
    flags = []
    kinds = set("cavity" if "cavity" in str(w).lower() else "solid" if "solid" in str(w).lower() else "other" for w in D.walls_description)
    if {"cavity", "solid"} <= kinds: flags.append(f"Dwellings in this building disagree about its walls ({(D.walls_description.str.lower().str.contains('solid')).sum()} say solid brick, {(D.walls_description.str.lower().str.contains('cavity')).sum()} say cavity).")
    if D.age_n.nunique() > 1: flags.append(f"Certificates give {D.age_n.nunique()} different construction periods: {', '.join(sorted(D.age_n.unique())[:4])}.")
    if assumed: flags.append(f"Storey count ({storeys:g}) is assumed, not measured.")
    yrs = (pd.Timestamp("2026-11-16") - D.lodgement_date).dt.days / 365.25
    if (yrs > 10).mean() > 0.5: flags.append(f"{int((yrs > 10).sum())} of {len(D)} certificates are over 10 years old.")
    if not single_house and len(uprns) < homes: flags.append(f"Only {len(uprns)} of about {homes} homes have a certificate.")
    if not ur and not single_house: flags.append("No top-floor certificate: roof insulation is assumed.")
    if single_house and note:
        for fl in []: pass
    # sensitivity: which certificate you pick changes the answer
    sens = None
    if single_house:
        hist = c[c.uprn == uprns[0]]
        if len(hist) > 1:
            vals = []
            for _, h in hist.iterrows():
                U2 = {"walls": u_wall(h.walls_description), "roof": u_roof(h.roof_description) or U["roof"], "floor": u_floor(h.floor_description) or U["floor"], "windows": u_win(h.windows_description, h.multi_glaze_proportion)}
                w2 = round(min(0.16 * h.total_floor_area * GLAZE.get(str(h.glazed_area).lower(), 1), 0.45 * wall_gross), 1)
                A2 = {**A, "windows": w2, "walls": max(wall_gross - w2, 0)}
                vals.append({"date": str(h.lodgement_date)[:10], "area": float(h.total_floor_area), "kw": round(sum(losses(U2, A2, ach, h.total_floor_area * fh).values()) / 1000, 1)})
            sens = {"certs": vals, "min_kw": min(v["kw"] for v in vals), "max_kw": max(v["kw"] for v in vals)}
            if sens["max_kw"] - sens["min_kw"] > 1: flags.append(f"Depending on which certificate you use, peak heat loss is {sens['min_kw']} or {sens['max_kw']} kW.")
    rule_conf = max(20, 100 - 12 * len(flags))
    ratings = D.current_energy_rating.value_counts().to_dict()
    addr = D.address1.iloc[0] if single_house else (tags.get("name") or (tags.get("addr:housenumber", "") + " Arlington Road").strip() if tags.get("addr:housenumber") or tags.get("name") else re.sub(r"^(flat|apartment|room|unit)\s*\w+,?\s*", "", str(D.address.iloc[0]), flags=re.I).split(",")[0])
    buildings.append({
        "id": f"b{osm[j]['id']}", "name": str(addr).title().replace("Arlington Road", "Arlington Rd"), "kind": "house" if single_house else "flats",
        "uprns": [int(u) for u in uprns], "homes": int(homes), "homes_certified": len(uprns), "storeys": storeys, "storeys_assumed": assumed, "height": height,
        "footprint": round(poly.area, 1), "gia": round(gia, 1), "ring": [list(to_ll(*xy)) for xy in ring], "edges": edges,
        "centroid": list(to_ll(poly.centroid.x, poly.centroid.y)), "exposed_wall_m": round(exp_len, 1),
        "U": U, "A": A, "loss_w": {k: round(v) for k, v in base.items()}, "total_kw": round(total / 1000, 1),
        "flux": {"walls": round(U["walls"] * DT, 1), "roof": round(U["roof"] * DT, 1)},
        "annual_kwh": round(kwh(total)), "bill_now_gbp": round(kwh(total) / BOILER_EFF * GAS_P), "co2_now_t": round(kwh(total) / BOILER_EFF * GAS_CO2 / 1000, 1),
        "measures": measures, "quick_wins": [m["key"] for m in quick],
        "fabric": {"capex": round(fab_capex, -2), "saves_kwh": round(fab_kwh), "saves_gbp": round(fab_gbp), "saves_co2_t": round(fab_kwh / BOILER_EFF * GAS_CO2 / 1000, 1),
                   "payback_yrs": round(fab_capex / fab_gbp, 1) if fab_gbp else None, "after_kw": round(after / 1000, 1)},
        "hp": hp, "solar": {"kwp": round(0.4 * poly.area * 0.2, 1), "kwh": round(0.4 * poly.area * 0.2 * 850), "capex": round(0.4 * poly.area * 0.2 * COST["solar_per_kwp"], -2), "saves_gbp": round(0.4 * poly.area * 0.2 * 850 * ELEC_P * 0.6)},
        "overheat": over, "flags": flags, "rule_conf": rule_conf, "sensitivity": sens,
        "tenure": D.tenure_n.value_counts().to_dict(), "ratings": ratings, "below_c": int(D.current_energy_rating.isin(list("DEFG")).sum()),
        "age": D.age_n.mode().iloc[0], "epc_words": {"walls": D.walls_description.mode().iloc[0], "roof": D.roof_description.mode().iloc[0], "windows": D.windows_description.mode().iloc[0], "heating": D.mainheat_description.mode().iloc[0]},
        "sceptic": ({k: note.get(k) for k in ["verdict", "likely_explanation", "confidence", "reasoning", "what_would_settle_it"]} if note else None),
    })

meta = {"certificates": int(len(c)), "dwellings": int(latest.shape[0]), "placed": sum(len(v) for v in assign.values()), "unplaced": unplaced,
        "buildings": len(buildings), "uprn_missing": n_missing, "uprn_recovered": n_recovered,
        "tenure": latest.tenure_n.value_counts().to_dict(), "ratings": latest.current_energy_rating.value_counts().to_dict()}
pathlib.Path("data/processed/street_buildings.json").write_text(json.dumps({"assumptions": ASSUMPTIONS, "meta": meta, "buildings": buildings}, default=str))
print(meta)
print("houses:", sum(b["kind"] == "house" for b in buildings), "| flat buildings:", sum(b["kind"] == "flats" for b in buildings), "| homes est.:", sum(b["homes"] for b in buildings))
print("street peak kW:", round(sum(b["total_kw"] for b in buildings)), "| fabric capex GBPm:", round(sum(b["fabric"]["capex"] for b in buildings) / 1e6, 2),
      "| saves GBP/yr:", round(sum(b["fabric"]["saves_gbp"] for b in buildings)), "| tCO2/yr:", round(sum(b["fabric"]["saves_co2_t"] for b in buildings)))
print("overheating bands:", pd.Series([b["overheat"]["band"] for b in buildings]).value_counts().to_dict(), "| with flags:", sum(bool(b["flags"]) for b in buildings))
s = [b["sensitivity"] for b in buildings if b["sensitivity"]]
print("houses with 2+ certs:", len(s), "| heat-loss swing >1 kW:", sum(x["max_kw"] - x["min_kw"] > 1 for x in s))
