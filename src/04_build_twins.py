"""
Step 4 - Build a simple digital twin (LOD1) for every house with its own footprint.

LOD1 = the footprint extruded straight up to the building's height: a block with a flat roof.
That is enough to measure the surfaces that lose heat.

Input : data/processed/arlington_twins.geojson (Step 3b: footprint + EPC summary per house)
        data/raw/osm/area_buildings.json        (all outlines in the area, to find shared party walls)
Output: data/processed/arlington_lod1.csv / .geojson

For every house we measure (in metres, British National Grid):
  - footprint area and perimeter
  - party wall length: the part of the outline shared with a neighbouring building (it loses little heat)
  - exposed wall length = perimeter - party wall
  - height = storeys x 3.0 m (storeys from OpenStreetMap; if missing, the street's typical value, marked as assumed)
  - exposed wall area, roof area
  - orientation: which way the largest exposed wall faces (matters for solar gain and overheating)
"""
import json, math, pathlib, pandas as pd, pyproj
from shapely.geometry import shape, Polygon, LineString, mapping
from shapely.ops import transform
from shapely.strtree import STRtree

FLOOR_TO_FLOOR_M = 3.0          # typical storey height in a London terrace
to_m = pyproj.Transformer.from_crs(4326, 27700, always_xy=True).transform
to_ll = pyproj.Transformer.from_crs(27700, 4326, always_xy=True).transform

twins = json.loads(pathlib.Path("data/processed/arlington_twins.geojson").read_text())["features"]
osm = [e for e in json.loads(pathlib.Path("data/raw/osm/area_buildings.json").read_text())["elements"] if len(e.get("geometry", [])) >= 4]
all_m = [transform(to_m, Polygon([(p["lon"], p["lat"]) for p in e["geometry"]])) for e in osm]
tree = STRtree(all_m)

own = [f for f in twins if f["properties"].get("own_footprint")]
typical_storeys = pd.Series([f["properties"]["osm_storeys"] for f in own if f["properties"].get("osm_storeys")]).median()

def facing(dx, dy):
    """Compass direction an outward wall normal points to."""
    bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((bearing + 22.5) // 45) % 8], round(bearing)

rows, feats = [], []
for f in own:
    p = f["properties"]
    poly = transform(to_m, shape(f["geometry"])).buffer(0)
    ring = LineString(poly.exterior.coords)
    # Party walls: parts of this outline lying within 0.3 m of another building's outline
    party = 0.0
    for j in tree.query(poly.buffer(0.3)):
        other = all_m[j]
        if other.equals(poly) or other.area == 0 or poly.symmetric_difference(other).area < 1: continue
        party += ring.intersection(other.buffer(0.3)).length
    party = min(party, ring.length)
    exposed = ring.length - party
    storeys = p.get("osm_storeys") or typical_storeys
    height = storeys * FLOOR_TO_FLOOR_M
    # Largest exposed wall segment and the direction it faces
    best, best_len = None, 0
    coords = list(poly.exterior.coords)
    ccw = poly.exterior.is_ccw
    for a, b in zip(coords[:-1], coords[1:]):
        seg = LineString([a, b])
        if any(seg.centroid.distance(all_m[j].exterior) < 0.3 and not all_m[j].equals(poly) and poly.symmetric_difference(all_m[j]).area >= 1
               for j in tree.query(seg.buffer(0.3))):
            continue  # this segment is a party wall
        if seg.length > best_len:
            dx, dy = b[0] - a[0], b[1] - a[1]
            nx, ny = (dy, -dx) if ccw else (-dy, dx)   # outward normal
            best, best_len = facing(nx, ny), seg.length
    row = {
        "uprn": p["uprn"], "address": p["address"],
        "footprint_m2": round(poly.area, 1), "perimeter_m": round(ring.length, 1),
        "party_wall_m": round(party, 1), "exposed_wall_m": round(exposed, 1),
        "storeys": storeys, "storeys_assumed": p.get("osm_storeys") is None,
        "height_m": round(height, 1),
        "exposed_wall_area_m2": round(exposed * height, 1), "roof_area_m2": round(poly.area, 1),
        "main_facade_faces": best[0] if best else None, "main_facade_bearing": best[1] if best else None,
        "geom_floor_area_m2": round(poly.area * storeys, 1),
    }
    rows.append(row)
    feats.append({"type": "Feature", "geometry": mapping(transform(to_ll, poly)), "properties": {**p, **row}})

df = pd.DataFrame(rows)
df.to_csv("data/processed/arlington_lod1.csv", index=False)
pathlib.Path("data/processed/arlington_lod1.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, default=str))
print(f"Twins built: {len(df)} (storeys from OSM: {(~df.storeys_assumed).sum()}, assumed {typical_storeys:g}: {df.storeys_assumed.sum()})")
print(df[["footprint_m2", "party_wall_m", "exposed_wall_m", "exposed_wall_area_m2", "height_m"]].describe().loc[["min", "50%", "max"]].round(1).to_string())
print("Main facade faces:", df.main_facade_faces.value_counts().to_dict())
