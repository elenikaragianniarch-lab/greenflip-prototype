"""
Step 1 - Select the study street and look for disagreements between certificates.

Input : data/raw/epc_camden_domestic.csv   (all domestic EPCs in Camden, 2008-2026)
Output: data/processed/arlington_houses_all_certs.csv  (every certificate for houses on the street)
        data/processed/arlington_houses_summary.csv    (one row per house, with disagreement flags)

Why: the same house is often certified several times over the years. If two certificates
for the same building disagree on things that cannot change (age) or rarely change
(floor area), at least one of them is wrong - and a model built on it inherits the error.
"""
import pandas as pd

RAW = "data/raw/epc_camden_domestic.csv"
STREET, SECTOR = "ARLINGTON ROAD", "NW1 7"

df = pd.read_csv(RAW, low_memory=False)

# 1. Keep houses on the street (flats need a different geometry check, so we leave them out for now)
on_street = df.address1.str.upper().str.contains(STREET, na=False) | df.address2.str.upper().str.contains(STREET, na=False)
houses = df[on_street & df.postcode.str.startswith(SECTOR, na=False) & (df.property_type == "House")].copy()

# 2. Clean the age band label (the register mixes two spellings of the same bands)
houses["age_band"] = houses.construction_age_band.str.replace("England and Wales: ", "", regex=False).str.replace("Pre-1900", "before 1900")
houses["lodgement_date"] = pd.to_datetime(houses.lodgement_date)
houses = houses.sort_values(["uprn", "lodgement_date"])
houses.to_csv("data/processed/arlington_houses_all_certs.csv", index=False)

# 3. One row per house: compare its certificates with each other
def summarise(g):
    areas = g.total_floor_area
    return pd.Series({
        "address": g.address1.iloc[-1],
        "n_certs": len(g),
        "first_cert": g.lodgement_date.min().date(),
        "latest_cert": g.lodgement_date.max().date(),
        "latest_rating": g.current_energy_rating.iloc[-1],
        "latest_area_m2": areas.iloc[-1],
        "area_min_m2": areas.min(),
        "area_max_m2": areas.max(),
        "area_spread_pct": round(100 * (areas.max() - areas.min()) / areas.min(), 1),
        "age_bands": " | ".join(sorted(g.age_band.dropna().unique())),
        "n_age_bands": g.age_band.nunique(),
        "walls_latest": g.walls_description.iloc[-1],
        "cert_age_years": round((pd.Timestamp("2026-11-16") - g.lodgement_date.max()).days / 365.25, 1),
    })

summary = houses.groupby("uprn")[houses.columns.drop("uprn")].apply(summarise).reset_index()
summary["flag_area"] = summary.area_spread_pct > 10          # same house, floor area differs by >10%
summary["flag_age"] = summary.n_age_bands > 1                 # same house, different construction age
summary["flag_old_cert"] = summary.cert_age_years > 10        # newest certificate has expired (EPCs last 10 years)
summary.to_csv("data/processed/arlington_houses_summary.csv", index=False)

print(f"Houses: {len(summary)}  |  certificates: {len(houses)}")
print(f"Houses with 2+ certificates: {(summary.n_certs > 1).sum()}")
print(f"  ...floor area differs by >10%: {summary.flag_area.sum()}")
print(f"  ...construction age differs:  {summary.flag_age.sum()}")
print(f"Houses whose newest certificate is over 10 years old: {summary.flag_old_cert.sum()}")
print()
print(summary[summary.flag_area | summary.flag_age][["address","n_certs","area_min_m2","area_max_m2","area_spread_pct","age_bands"]].to_string(index=False))
