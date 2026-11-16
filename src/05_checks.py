"""
Step 5 - Rule-based checks: where do the records disagree with each other or with the building?

Plain code, no AI. Every flag carries its evidence, so a person (or the agent in Step 6) can see why.
Each house starts at 100 points of confidence; each flag removes points according to how much it
would mislead a retrofit model (floor area drives heat-pump sizing, so it weighs most).

Input : data/processed/arlington_houses_summary.csv (Step 1), arlington_twins.csv (Step 3b), arlington_lod1.csv (Step 4)
Output: data/processed/arlington_checks.csv  - one row per house, with flags, evidence and a score
        data/processed/arlington_checks.json - the same, as structured input for the agent
"""
import json, pathlib, pandas as pd

s = pd.read_csv("data/processed/arlington_houses_summary.csv")
t = pd.read_csv("data/processed/arlington_twins.csv")[["uprn", "footprint_m2", "houses_in_footprint", "osm_storeys", "own_footprint", "implied_storeys"]]
g = pd.read_csv("data/processed/arlington_lod1.csv")[["uprn", "storeys", "storeys_assumed", "height_m", "exposed_wall_m", "party_wall_m", "main_facade_faces", "geom_floor_area_m2"]]
df = s.merge(t, on="uprn", how="left").merge(g, on="uprn", how="left")

WEIGHTS = {
    "area_vs_geometry": 30,   # certificate floor area doesn't fit the building
    "area_changes": 20,       # the house's own certificates disagree on floor area
    "age_changes": 10,        # ...or on when it was built
    "wall_vs_age": 15,        # cavity walls claimed on a pre-1900 house (cavity walls are a 20th-century type)
    "type_mismatch": 25,      # labelled a house, but looks like a flat
    "no_own_footprint": 15,   # geometry can't verify this house on its own
    "expired": 10,            # newest certificate over 10 years old
    "uprn_missing": 5,        # newest certificate had no address ID
}

def check(r):
    flags = []
    def add(code, evidence): flags.append({"check": code, "points": WEIGHTS[code], "evidence": evidence})
    if r.own_footprint is True and pd.notna(r.geom_floor_area_m2):
        diff = 100 * (r.latest_area_m2 - r.geom_floor_area_m2) / r.geom_floor_area_m2
        basis = "OSM storey count" if not r.storeys_assumed else "assumed 3 storeys"
        if abs(diff) > 20:
            add("area_vs_geometry", f"EPC says {r.latest_area_m2:g} m2; footprint {r.footprint_m2:g} m2 x {r.storeys:g} storeys ({basis}) = {r.geom_floor_area_m2:g} m2 ({diff:+.0f}%). "
                                    f"Implies {r.implied_storeys:g} storeys.")
    if r.area_spread_pct > 10:
        add("area_changes", f"Its certificates range from {r.area_min_m2:g} to {r.area_max_m2:g} m2 ({r.area_spread_pct:g}% apart).")
    if r.n_age_bands > 1:
        add("age_changes", f"Certificates give different construction periods: {r.age_bands}.")
    if isinstance(r.walls_latest, str) and "cavity" in r.walls_latest.lower() and "before 1900" in str(r.age_bands):
        add("wall_vs_age", f"Newest certificate says '{r.walls_latest}', but the house is recorded as built before 1900.")
    if "flat" in str(r.address).lower() or (pd.notna(r.footprint_m2) and r.footprint_m2 > 300):
        add("type_mismatch", f"Recorded as a house, but address is '{r.address}' and footprint is {r.footprint_m2:g} m2.")
    if r.own_footprint is not True:
        n = r.houses_in_footprint
        add("no_own_footprint", "No outline of its own in OpenStreetMap" + (f" (outline shared by {n:g} addresses)." if pd.notna(n) else " (address point not inside any outline)."))
    if r.cert_age_years > 10:
        add("expired", f"Newest certificate is {r.cert_age_years:g} years old (lodged {r.latest_cert}).")
    if r.uprn_was_missing:
        add("uprn_missing", "Newest certificate was lodged without a UPRN; matched by house number.")
    score = max(0, 100 - sum(f["points"] for f in flags))
    return pd.Series({"flags": flags, "n_flags": len(flags), "confidence": score})

df = pd.concat([df, df.apply(check, axis=1)], axis=1)
df["band"] = pd.cut(df.confidence, [-1, 49, 79, 100], labels=["low", "medium", "high"])
df.drop(columns=["flags"]).assign(flag_list=df["flags"].map(lambda fl: "; ".join(f["check"] for f in fl))).to_csv("data/processed/arlington_checks.csv", index=False)
recs = json.loads(df.to_json(orient="records"))
pathlib.Path("data/processed/arlington_checks.json").write_text(json.dumps(recs, indent=1))

print("Confidence bands:", df.band.value_counts().reindex(["high", "medium", "low"]).to_dict())
print("How often each check fires:", pd.Series([f["check"] for fl in df["flags"] for f in fl]).value_counts().to_dict())
print()
print(df.sort_values("confidence")[["address", "confidence", "n_flags"]].head(10).to_string(index=False))
