"""
Step 3a - Fetch building outlines and UPRN locations for the Arlington Road area from Ordnance Survey.

Uses the OS Features API (free OS OpenData plan). The API key is read from secrets/os_api_key.txt,
which never leaves this Mac and is excluded from GitHub.

Output: data/raw/os/buildings.geojson   building outlines (OS Open Zoomstack, local buildings)
        data/raw/os/uprns.geojson       every UPRN (address point) in the area, with coordinates
"""
import json, pathlib, requests

KEY = pathlib.Path("secrets/os_api_key.txt").read_text().strip()
URL = "https://api.os.uk/features/v1/wfs"
# Bounding box around Arlington Road, NW1 7 (lat/lon, WGS84): south, west, north, east
BBOX = (51.5330, -0.1475, 51.5415, -0.1385)
OUT = pathlib.Path("data/raw/os"); OUT.mkdir(parents=True, exist_ok=True)

def fetch(layer):
    """Download every feature of one layer inside the box, 100 at a time (the API's page size)."""
    features, start = [], 0
    while True:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": layer, "outputFormat": "GEOJSON", "srsName": "EPSG:4326",
            "bbox": f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]},EPSG:4326",
            "count": 100, "startIndex": start, "key": KEY,
        }
        r = requests.get(URL, params=params, timeout=60)
        r.raise_for_status()
        page = r.json().get("features", [])
        features += page
        if len(page) < 100:
            return {"type": "FeatureCollection", "features": features}
        start += 100

for layer, name in [("osfeatures:Zoomstack_LocalBuildings", "buildings"), ("osfeatures:OpenUPRN_Address", "uprns")]:
    fc = fetch(layer)
    (OUT / f"{name}.geojson").write_text(json.dumps(fc))
    print(f"{name}: {len(fc['features'])} features")
    if fc["features"]:
        print("   fields:", list(fc["features"][0]["properties"].keys()))
