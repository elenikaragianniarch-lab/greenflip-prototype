"""
Step 3b - Give every house its own footprint and compare it with what its certificates claim.

Inputs : data/processed/arlington_houses_summary.csv   (Step 1: one row per house, from the EPCs)
         data/raw/os/uprns.geojson                      (Step 3a: OS address points)
         data/raw/osm/area_buildings.json               (OpenStreetMap building outlines, fetched below if missing)
Outputs: data/processed/arlington_twins.csv             (one row per house: EPC + geometry + checks)
         data/processed/arlington_twins.geojson         (same, with footprints, for the map)

Logic, in plain words:
  1. Put each house's address point (from its UPRN) on the map.
  2. Find the OpenStreetMap building it falls inside: that's its footprint.
     If a footprint holds more than one house, it isn't a single house, so we mark it as shared.
  3. Footprint area x storeys = the floor area the building can physically hold.
     Compare with the EPC floor area. If storeys are unknown, turn it around:
     EPC floor area / footprint = how many storeys the certificate implies.
"""
import json, pathlib, requests, pandas as pd, pyproj
from shapely.geometry import Polygon, Point, mapping
from shapely.strtree import STRtree
from shapely.ops import transform

OSM = pathlib.Path("data/raw/osm/area_buildings.json")
if not OSM.exists():
    q = '[out:json][timeout:60];(way["building"](51.5330,-0.1475,51.5415,-0.1385););out body geom;'
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q},
                      headers={"User-Agent": "greenflip-prototype/0.1 (portfolio research)"}, timeout=120)
    r.raise_for_status(); OSM.parent.mkdir(parents=True, exist_ok=True); OSM.write_text(r.text)

to_metres = pyproj.Transformer.from_crs(4326, 27700, always_xy=True).transform  # lat/lon -> British National Grid (metres)

houses = pd.read_csv("data/processed/arlington_houses_summary.csv")
uprn_xy = {int(f["properties"]["UPRN"]): (f["properties"]["Longitude"], f["properties"]["Latitude"])
           for f in json.loads(pathlib.Path("data/raw/os/uprns.geojson").read_text())["features"]}
osm = [e for e in json.loads(OSM.read_text())["elements"] if len(e.get("geometry", [])) >= 4]
polys = [Polygon([(p["lon"], p["lat"]) for p in e["geometry"]]) for e in osm]
tree = STRtree(polys)

rows, shapes = [], []
for _, h in houses.iterrows():
    lon, lat = uprn_xy[int(h.uprn)]
    hit = tree.query(Point(lon, lat), predicate="within")
    rows.append(int(hit[0]) if len(hit) else None)
houses["osm_idx"] = rows
share = houses.osm_idx.value_counts()

def storeys(i):
    lv = osm[int(i)]["tags"].get("building:levels") if pd.notna(i) else None
    try: return float(lv)
    except (TypeError, ValueError): return None

houses["footprint_m2"] = houses.osm_idx.map(lambda i: round(transform(to_metres, polys[int(i)]).area, 1) if pd.notna(i) else None)
houses["houses_in_footprint"] = houses.osm_idx.map(lambda i: int(share[i]) if pd.notna(i) else None)
houses["osm_storeys"] = houses.osm_idx.map(storeys)
houses["own_footprint"] = houses.houses_in_footprint == 1

# Floor area the building can hold (only where we know storeys and the footprint is the house's own)
houses["geom_area_m2"] = (houses.footprint_m2 * houses.osm_storeys).where(houses.own_footprint)
houses["epc_vs_geom_pct"] = (100 * (houses.latest_area_m2 - houses.geom_area_m2) / houses.geom_area_m2).round(1)
# Storeys the certificate implies, for every house with its own footprint
houses["implied_storeys"] = (houses.latest_area_m2 / houses.footprint_m2).where(houses.own_footprint).round(2)

houses.drop(columns=["osm_idx"]).to_csv("data/processed/arlington_twins.csv", index=False)

features = []
for _, h in houses.iterrows():
    if pd.isna(h.osm_idx): continue
    props = {k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for k, v in h.drop(labels=["osm_idx"]).items()}
    features.append({"type": "Feature", "geometry": mapping(polys[int(h.osm_idx)]), "properties": props})
pathlib.Path("data/processed/arlington_twins.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, default=str))

own = houses[houses.own_footprint]
print(f"Houses: {len(houses)} | inside an OSM building: {houses.osm_idx.notna().sum()} | own footprint: {len(own)}")
print(f"Own footprint and storeys known: {own.osm_storeys.notna().sum()}")
print(f"Footprint m2, median: {own.footprint_m2.median()}")
print("\nStoreys implied by the EPC floor area (own footprints):")
print(own.implied_storeys.describe().round(2).to_string())
cols = ["address", "latest_area_m2", "footprint_m2", "osm_storeys", "geom_area_m2", "epc_vs_geom_pct", "implied_storeys"]
print("\nHouses where storeys are known:")
print(own[own.osm_storeys.notna()][cols].sort_values("epc_vs_geom_pct").to_string(index=False))
