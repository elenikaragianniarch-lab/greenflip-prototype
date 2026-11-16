"""
Step 7 - An interactive 3D map of the street: every house coloured by the agent's verdict,
click a house to read the evidence and the agent's note.

Inputs : data/processed/arlington_lod1.geojson   (Step 4: the twins)
         data/processed/arlington_checks.json    (Step 5: rules and flags)
         data/raw/os/uprns.geojson               (Step 3a: address points, for houses with no footprint of their own)
         outputs/agent_notes.json                (Step 6: the agent's verdicts)
Output : outputs/street_map.html  (one self-contained page; open it in any browser)

The page uses deck.gl for the 3D blocks and MapLibre with a light OpenStreetMap-based basemap.
It stays local (outputs/ is git-ignored) because it shows addresses from the EPC data.
"""
import json, pathlib
from shapely.geometry import Polygon, Point

lod1 = json.loads(pathlib.Path("data/processed/arlington_lod1.geojson").read_text())
checks = {str(int(c["uprn"])): c for c in json.loads(pathlib.Path("data/processed/arlington_checks.json").read_text())}
notes = {str(int(n["uprn"])): n for n in json.loads(pathlib.Path("outputs/agent_notes.json").read_text())}
uprn_pts = {str(int(f["properties"]["UPRN"])): (f["properties"]["Longitude"], f["properties"]["Latitude"])
            for f in json.loads(pathlib.Path("data/raw/os/uprns.geojson").read_text())["features"]}

def record(uprn):
    c, n = checks.get(uprn, {}), notes.get(uprn, {})
    return {
        "uprn": uprn, "address": c.get("address"),
        "verdict": n.get("verdict"), "explanation": n.get("likely_explanation"),
        "agent_conf": n.get("confidence"), "rules_conf": c.get("confidence"),
        "trusted_area": n.get("trusted_floor_area_m2"), "trusted_src": n.get("trusted_floor_area_source"),
        "reasoning": n.get("reasoning"), "settle": n.get("what_would_settle_it"),
        "epc_area": c.get("latest_area_m2"), "n_certs": c.get("n_certs"), "latest_cert": c.get("latest_cert"),
        "rating": c.get("latest_rating"), "age": c.get("age_bands"),
        "footprint": c.get("footprint_m2"), "storeys": c.get("storeys"), "storeys_assumed": c.get("storeys_assumed"),
        "flags": [f["evidence"] for f in (c.get("flags") or [])],
    }

blocks = []
seen = set()
for f in lod1["features"]:
    u = str(int(f["properties"]["uprn"])); seen.add(u)
    blocks.append({"type": "Feature", "geometry": f["geometry"], "properties": {**record(u), "height": f["properties"]["height_m"]}})
points = []
for u in checks:
    if u in seen or u not in uprn_pts: continue
    lon, lat = uprn_pts[u]
    points.append({"position": [lon, lat], **record(u)})

# Context: every other OpenStreetMap building in the area, drawn pale so the street sits in its neighbourhood
study_pts = [Point(uprn_pts[u]) for u in checks if u in uprn_pts]
context = []
osm_path = pathlib.Path("data/raw/osm/area_buildings.json")
if osm_path.exists():
    for e in json.loads(osm_path.read_text())["elements"]:
        g = e.get("geometry", [])
        if len(g) < 4: continue
        poly = Polygon([(p["lon"], p["lat"]) for p in g])
        if any(poly.contains(pt) for pt in study_pts): continue   # already drawn as a study house
        try: lv = float(e["tags"].get("building:levels", 3))
        except ValueError: lv = 3
        context.append({"polygon": [[p["lon"], p["lat"]] for p in g], "height": lv * 3.0})

counts = {}
for n in notes.values(): counts[n.get("verdict")] = counts.get(n.get("verdict"), 0) + 1
data = {"blocks": {"type": "FeatureCollection", "features": blocks}, "points": points, "context": context, "counts": counts, "total": len(notes)}

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arlington Road — can the data be trusted?</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.0.38/dist.min.js"></script>
<style>
  :root { --ink:#111; --mid:#9a9a9a; --red:#FF3131; --paper:#fafaf8; --line:#e2e2de; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color:var(--ink); background:var(--paper); }
  #map { position:absolute; inset:0 400px 0 0; }
  aside { position:absolute; top:0; right:0; bottom:0; width:400px; overflow-y:auto; background:var(--paper);
          border-left:1px solid var(--line); padding:28px 28px 40px; }
  .kicker { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:#666; }
  h1 { font-size:26px; line-height:1.1; font-weight:700; margin:8px 0 10px; letter-spacing:-.01em; }
  p.lead { font-size:13.5px; line-height:1.5; color:#333; }
  .stats { display:grid; grid-template-columns:repeat(3,1fr); gap:0; margin:22px 0 8px; border-top:1px solid var(--ink); }
  .stat { padding:10px 0 0; }
  .stat b { display:block; font-size:30px; font-weight:700; letter-spacing:-.02em; }
  .stat span { font-size:11.5px; color:#555; display:flex; align-items:center; gap:6px; }
  .sw { width:10px; height:10px; display:inline-block; }
  .hint { font-size:12px; color:#777; margin-top:14px; }
  #card { margin-top:26px; border-top:1px solid var(--ink); padding-top:16px; display:none; }
  #card h2 { font-size:20px; font-weight:700; letter-spacing:-.01em; }
  .verdict { display:inline-block; margin:8px 0 12px; font-size:11px; letter-spacing:.1em; text-transform:uppercase;
             padding:4px 8px; color:#fff; }
  .row { display:flex; justify-content:space-between; font-size:13px; padding:6px 0; border-bottom:1px solid var(--line); }
  .row span:first-child { color:#666; }
  h3 { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:#666; margin:18px 0 6px; }
  .body { font-size:13.5px; line-height:1.5; }
  ul.flags { list-style:none; font-size:12.5px; line-height:1.45; color:#333; }
  ul.flags li { padding:6px 0; border-bottom:1px dotted var(--line); }
  .bar { height:6px; background:var(--line); position:relative; margin-top:4px; }
  .bar i { position:absolute; left:0; top:0; bottom:0; background:var(--ink); }
  footer { font-size:10.5px; color:#888; margin-top:28px; line-height:1.5; }
</style></head>
<body>
<div id="map"></div>
<aside>
  <div class="kicker">Greenflip prototype · Arlington Road, Camden NW1</div>
  <h1>Can this street's housing data be trusted?</h1>
  <p class="lead">Each block is a house: its footprint raised to its height. The colour is the sceptic agent's verdict
  after reading the house's energy certificates, its 3D model and the rule-based flags. Dots are houses with no
  footprint of their own to check against.</p>
  <div class="stats">
    <div class="stat"><b id="n-trust"></b><span><i class="sw" style="background:#111"></i>Trust</span></div>
    <div class="stat"><b id="n-caution"></b><span><i class="sw" style="background:#787878"></i>Use with caution</span></div>
    <div class="stat"><b id="n-no"></b><span><i class="sw" style="background:#FF3131"></i>Do not use</span></div>
  </div>
  <div class="hint">Click a house to read why. Drag to rotate (right-click or ctrl), scroll to zoom.</div>
  <div id="card"></div>
  <footer>Data: EPC open data (MHCLG); OS Open UPRN and OS Open Zoomstack, contains OS data © Crown copyright and database right 2026;
  building outlines © OpenStreetMap contributors. Judgements by Claude, constrained to the evidence shown.
  Prototype by Eleni Karagianni.</footer>
</aside>
<script>
const DATA = __DATA__;
const COLORS = { trust:[17,17,17], use_with_caution:[120,120,120], do_not_use:[255,49,49], no_answer:[200,200,200] };
const LABEL = { trust:"Trust", use_with_caution:"Use with caution", do_not_use:"Do not use", no_answer:"No answer" };
const EXPL = { consistent:"Records are consistent", basement_or_lower_ground:"Probably a basement / lower ground floor",
  extension_or_loft:"Probably an extension or loft", outdated_certificate:"Certificate is out of date",
  data_entry_error:"Probably a data error", misclassified_not_a_house:"Not actually a house",
  cannot_verify_geometry:"Can't be verified from the map", mixed:"Several issues at once" };
document.getElementById("n-trust").textContent = DATA.counts.trust || 0;
document.getElementById("n-caution").textContent = DATA.counts.use_with_caution || 0;
document.getElementById("n-no").textContent = DATA.counts.do_not_use || 0;

const esc = s => String(s ?? "—").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function show(p) {
  if (!p) return;
  const col = COLORS[p.verdict] || [200,200,200];
  const flags = (p.flags || []).map(f => `<li>${esc(f)}</li>`).join("") || "<li>No flags.</li>";
  const card = document.getElementById("card");
  card.style.display = "block";
  card.innerHTML = `
    <h2>${esc(p.address)}</h2>
    <div class="verdict" style="background:rgb(${col})">${esc(LABEL[p.verdict])}</div>
    <div class="body"><b>${esc(EXPL[p.explanation] || p.explanation)}</b></div>
    <h3>Confidence</h3>
    <div class="row"><span>Rules (Step 5)</span><span>${esc(p.rules_conf)}</span></div>
    <div class="bar"><i style="width:${p.rules_conf||0}%;background:#9a9a9a"></i></div>
    <div class="row"><span>Agent (Step 6)</span><span>${esc(p.agent_conf)}</span></div>
    <div class="bar"><i style="width:${p.agent_conf||0}%"></i></div>
    <h3>Floor area</h3>
    <div class="row"><span>Latest certificate</span><span>${esc(p.epc_area)} m²</span></div>
    <div class="row"><span>Agent trusts</span><span>${p.trusted_area == null ? "none" : esc(p.trusted_area) + " m²"}</span></div>
    <div class="row"><span>Footprint × storeys</span><span>${p.footprint ? esc(p.footprint) + " m² × " + esc(p.storeys) + (p.storeys_assumed ? " (assumed)" : "") : "no own footprint"}</span></div>
    <div class="row"><span>Certificates</span><span>${esc(p.n_certs)} · latest ${esc(p.latest_cert)} · ${esc(p.rating)}</span></div>
    <h3>Agent's reasoning</h3><div class="body">${esc(p.reasoning)}</div>
    <h3>What would settle it</h3><div class="body">${esc(p.settle)}</div>
    <h3>Rule-based flags</h3><ul class="flags">${flags}</ul>`;
  card.scrollIntoView({behavior:"smooth", block:"start"});
}

const map = new maplibregl.Map({
  container: "map",
  style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  center: [-0.1432, 51.5372], zoom: 16, antialias: true
});
const overlay = new deck.MapboxOverlay({
  interleaved: false,
  layers: [
    new deck.PolygonLayer({
      id: "context", data: DATA.context, extruded: false, pickable: false, stroked: true,
      getPolygon: d => d.polygon,
      getFillColor: [232,232,227,255], getLineColor: [250,250,248], lineWidthMinPixels: 1
    }),
    new deck.GeoJsonLayer({
      id: "houses", data: DATA.blocks, extruded: true, wireframe: true, pickable: true,
      getElevation: f => f.properties.height,
      getFillColor: f => [...(COLORS[f.properties.verdict] || [200,200,200]), 235],
      getLineColor: [250,250,248], lineWidthMinPixels: 1,
      onClick: info => show(info.object && info.object.properties)
    }),
    new deck.ScatterplotLayer({
      id: "no-footprint", data: DATA.points, pickable: true, stroked: true, filled: true,
      getPosition: d => d.position, radiusMinPixels: 6, radiusMaxPixels: 10, getRadius: 3,
      getFillColor: d => [...(COLORS[d.verdict] || [200,200,200]), 255], getLineColor: [255,255,255], lineWidthMinPixels: 2,
      onClick: info => show(info.object)
    })
  ],
  getTooltip: ({object}) => object && (object.properties ? object.properties.address : object.address)
});
map.addControl(overlay);
map.on("load", () => {
  const xs = [], ys = [];
  DATA.blocks.features.forEach(f => f.geometry.coordinates.flat(2).forEach((v, i) => (i % 2 ? ys : xs).push(v)));
  DATA.points.forEach(d => { xs.push(d.position[0]); ys.push(d.position[1]); });
  map.fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]],
                {padding: {top: 40, bottom: 40, left: 40, right: 40}, pitch: 55, bearing: -20, duration: 0});
});
map.addControl(new maplibregl.NavigationControl({visualizePitch:true}), "top-left");
</script>
</body></html>"""

out = pathlib.Path("outputs/street_map.html")
out.parent.mkdir(exist_ok=True)
out.write_text(HTML.replace("__DATA__", json.dumps(data, default=str)))
print(f"Wrote {out}: {len(blocks)} blocks, {len(points)} dots, verdicts {counts}")
