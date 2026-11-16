"""
Step 9 - The digital twin map: where every house loses heat, what to fix first, and how far to trust it.

Each house is built from its parts so they can be coloured separately:
  - every exposed wall is a thin 3D panel coloured by heat loss per m2 on a cold day (W/m2),
  - party walls (shared with a neighbour) are grey, because they lose almost nothing,
  - the roof is a slab coloured the same way.
Three views: Heat loss, Where to start (retrofit priority), Data trust (the sceptic agent's verdict).

Input : data/processed/arlington_heat.json (Step 8), data/raw/osm/area_buildings.json (context)
Output: outputs/street_twin.html (self-contained page; needs internet for the map libraries)
"""
import json, math, pathlib, warnings, pyproj
warnings.filterwarnings("ignore", category=DeprecationWarning)

heat = json.loads(pathlib.Path("data/processed/arlington_heat.json").read_text())
to_m = pyproj.Transformer.from_crs(4326, 27700, always_xy=True).transform
to_ll = pyproj.Transformer.from_crs(27700, 4326, always_xy=True).transform
T = 0.35   # wall panel thickness (m), drawn just outside the footprint

panels, roofs, cards = [], [], []
for h in heat["houses"]:
    ring = [to_m(*xy) for xy in h["roof"]]
    cx = sum(x for x, _ in ring[:-1]) / (len(ring) - 1); cy = sum(y for _, y in ring[:-1]) / (len(ring) - 1)
    for e in h["edges"]:
        ax, ay = to_m(*e["a"]); bx, by = to_m(*e["b"])
        dx, dy = bx - ax, by - ay; L = math.hypot(dx, dy) or 1
        nx, ny = dy / L, -dx / L
        mx, my = (ax + bx) / 2, (ay + by) / 2
        if (mx + nx - cx) ** 2 + (my + ny - cy) ** 2 < (mx - cx) ** 2 + (my - cy) ** 2: nx, ny = -nx, -ny   # point outwards
        poly = [(ax, ay), (bx, by), (bx + nx * T, by + ny * T), (ax + nx * T, ay + ny * T), (ax, ay)]
        panels.append({"uprn": h["uprn"], "party": e["party"], "flux": h["flux"]["walls"], "h": h["height"],
                       "polygon": [list(to_ll(x, y)) for x, y in poly]})
    roofs.append({"uprn": h["uprn"], "flux": h["flux"]["roof"], "polygon": [[x, y, h["height"]] for x, y in h["roof"]]})
    cards.append({k: h[k] for k in ["uprn", "address", "height", "storeys", "storeys_assumed", "floor_area", "floor_area_source", "U", "A",
                                     "loss_w", "total_kw", "flux", "annual_kwh", "hp_now_kw", "hp_now_label", "hp_after_kw", "after_fabric_kw",
                                     "saving_all_kwh", "risk_adjusted_kwh", "confidence", "measures", "solar_kwp", "solar_kwh_yr", "epc", "trust", "priority_rank"]}
                 | {"centroid": [sum(p[0] for p in h["roof"][:-1]) / (len(h["roof"]) - 1), sum(p[1] for p in h["roof"][:-1]) / (len(h["roof"]) - 1)]})

context = []
osm = pathlib.Path("data/raw/osm/area_buildings.json")
if osm.exists():
    from shapely.geometry import Polygon, Point
    pts = [Point(c["centroid"]) for c in cards]
    for e in json.loads(osm.read_text())["elements"]:
        g = e.get("geometry", [])
        if len(g) < 4: continue
        poly = Polygon([(p["lon"], p["lat"]) for p in g])
        if any(poly.contains(pt) for pt in pts): continue
        context.append([[p["lon"], p["lat"]] for p in g])

tot = {k: sum(c["loss_w"][k] for c in cards) for k in ["walls", "roof", "windows", "floor", "air leakage"]}
street = {"total_kw": round(sum(tot.values()) / 1000), "by_element": {k: round(v / 1000, 1) for k, v in tot.items()},
          "n": len(cards), "saving_kwh": sum(c["saving_all_kwh"] for c in cards if c["priority_rank"]),
          "risk_adjusted_kwh": sum(c["risk_adjusted_kwh"] for c in cards if c["priority_rank"]),
          "hp_now_median": sorted(c["hp_now_kw"] for c in cards)[len(cards) // 2],
          "hp_after_median": sorted(c["hp_after_kw"] for c in cards)[len(cards) // 2],
          "held_back": sum(1 for c in cards if c["priority_rank"] is None)}
DATA = {"panels": panels, "roofs": roofs, "cards": cards, "context": context, "street": street, "assumptions": heat["assumptions"]}

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arlington Road — digital twin</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.0.38/dist.min.js"></script>
<style>
:root{--ink:#111;--paper:#fafaf8;--line:#e4e2dc;--mute:#6b6b6b;--red:#FF3131}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper);overflow:hidden}
#map{position:absolute;inset:0 380px 0 0}
aside{position:absolute;top:0;right:0;bottom:0;width:380px;overflow-y:auto;background:var(--paper);border-left:1px solid var(--line);padding:24px 24px 32px}
.k{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute)}
h1{font-size:22px;line-height:1.15;margin:6px 0 14px;letter-spacing:-.01em}
.big{display:flex;gap:18px;border-top:1px solid var(--ink);padding-top:12px;margin-bottom:16px}
.big div b{display:block;font-size:26px;letter-spacing:-.02em;line-height:1.05;white-space:nowrap}
.big div span{font-size:11.5px;color:var(--mute)}
.stack{display:flex;height:22px;margin:6px 0 4px}
.stack i{display:block;height:100%}
.legend-row{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:11px;color:#444;margin-bottom:14px}
.legend-row span{display:flex;align-items:center;gap:5px}.sw{width:9px;height:9px;display:inline-block}
h3{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin:18px 0 8px}
.rank{display:grid;grid-template-columns:22px 1fr 70px;gap:8px;align-items:center;font-size:13px;padding:6px 0;border-bottom:1px solid var(--line);cursor:pointer}
.rank:hover{background:#f0eee8}.rank b{font-size:12px;color:var(--mute)}
.mbar{height:6px;background:var(--ink)}
.modes{position:absolute;top:14px;left:14px;display:flex;background:#fff;border:1px solid var(--line);z-index:2}
.modes button{border:0;background:none;padding:9px 14px;font:inherit;font-size:12.5px;cursor:pointer;color:var(--mute)}
.modes button.on{background:var(--ink);color:#fff}
#scale{position:absolute;left:14px;bottom:18px;background:rgba(255,255,255,.92);border:1px solid var(--line);padding:10px 12px;font-size:11px;z-index:2;width:250px}
#scale .ramp{height:8px;margin:6px 0 3px}
#scale .ends{display:flex;justify-content:space-between;color:var(--mute)}
.back{font-size:12px;color:var(--mute);cursor:pointer;margin-bottom:10px;display:inline-block}
.badge{display:inline-block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;padding:3px 7px;color:#fff;margin:2px 0 10px}
.hp{display:flex;align-items:baseline;gap:8px;margin:4px 0}.hp b{font-size:24px;letter-spacing:-.02em;white-space:nowrap}.hp em{font-style:normal;color:var(--mute);font-size:12px}
.meas{font-size:13px;padding:7px 0;border-bottom:1px solid var(--line)}
.meas div{display:flex;justify-content:space-between}.meas small{color:var(--mute);font-size:11.5px}
details{font-size:12.5px;line-height:1.5;color:#333;margin-top:14px}summary{cursor:pointer;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute)}
.note{font-size:10.5px;color:#888;line-height:1.5;margin-top:22px}
</style></head><body>
<div id="map"></div>
<div class="modes"><button data-m="heat" class="on">Heat loss</button><button data-m="start">Where to start</button><button data-m="trust">Data trust</button></div>
<div id="scale"></div>
<aside id="side"></aside>
<script>
const D = __DATA__;
const EL = {"walls":"#c8402b","roof":"#e98a3f","windows":"#4f7cac","floor":"#8a7f6e","air leakage":"#b9b4aa"};
const ELN = {"walls":"Walls","roof":"Roof","windows":"Windows","floor":"Floor","air leakage":"Air leakage"};
const TRUST = {trust:[17,17,17], use_with_caution:[150,150,150], do_not_use:[255,49,49]};
const TRUSTN = {trust:"Data: trust", use_with_caution:"Data: use with caution", do_not_use:"Data: do not use"};
const byId = Object.fromEntries(D.cards.map(c => [c.uprn, c]));
let mode = "heat", selected = null;

// heat-flux ramp, W/m2 on the design day
const STOPS = [[0,[236,233,226]],[10,[244,206,150]],[25,[236,140,74]],[40,[210,66,40]],[55,[120,22,16]]];
function ramp(v){ for(let i=1;i<STOPS.length;i++){ const [a,ca]=STOPS[i-1],[b,cb]=STOPS[i];
  if(v<=b){ const t=(v-a)/(b-a); return ca.map((x,j)=>Math.round(x+(cb[j]-x)*t)); } } return STOPS[STOPS.length-1][1]; }
const maxSave = Math.max(...D.cards.filter(c=>c.priority_rank).map(c=>c.risk_adjusted_kwh));
function startColor(c){ if(!c.priority_rank) return [205,205,200]; const t=c.risk_adjusted_kwh/maxSave; return [Math.round(40+215*t),Math.round(40+9*(1-t)),Math.round(40+9*(1-t))]; }
function colorFor(uprn, part, flux){
  const c = byId[uprn];
  if (mode === "heat") return part === "party" ? [205,205,200] : ramp(flux);
  if (mode === "start") return part === "party" ? [215,215,210] : startColor(c);
  return part === "party" ? [215,215,210] : (TRUST[c.trust.verdict] || [200,200,200]);
}
const hi = (uprn, rgb) => selected && selected !== uprn ? [...rgb, 70] : [...rgb, 255];

function layers(){
  return [
    new deck.PolygonLayer({id:"ctx", data:D.context, getPolygon:d=>d, filled:true, stroked:false, getFillColor:[232,231,226], pickable:false}),
    new deck.PolygonLayer({id:"walls", data:D.panels, getPolygon:d=>d.polygon, extruded:true, getElevation:d=>d.h, pickable:true,
      getFillColor:d=>hi(d.uprn, colorFor(d.uprn, d.party?"party":"wall", d.flux)), updateTriggers:{getFillColor:[mode,selected]},
      material:{ambient:.55, diffuse:.5, shininess:8}, onClick:i=>pick(i.object&&i.object.uprn)}),
    new deck.PolygonLayer({id:"roofs", data:D.roofs, getPolygon:d=>d.polygon, extruded:true, getElevation:.35, pickable:true,
      getFillColor:d=>hi(d.uprn, colorFor(d.uprn, "roof", d.flux)), updateTriggers:{getFillColor:[mode,selected]},
      material:{ambient:.6, diffuse:.45}, onClick:i=>pick(i.object&&i.object.uprn)})
  ];
}

const map = new maplibregl.Map({container:"map", style:"https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  center:[-0.1432,51.5372], zoom:16, antialias:true});
const overlay = new deck.MapboxOverlay({interleaved:false, layers:layers(),
  getTooltip:({object})=>object && byId[object.uprn] && {text: byId[object.uprn].address, style:{fontSize:"12px"}}});
map.addControl(overlay);
map.addControl(new maplibregl.NavigationControl({visualizePitch:true}), "top-right");
const _cs=[...D.cards].sort((a,b)=>a.centroid[1]-b.centroid[1]), _m=_cs[Math.floor(_cs.length*0.55)].centroid;
const START={center:_m, zoom:17.6};
map.on("load", ()=>{ map.jumpTo({center:START.center, zoom:START.zoom, pitch:58, bearing:-22}); });
function redraw(){ overlay.setProps({layers:layers()}); drawScale(); }

document.querySelectorAll(".modes button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".modes button").forEach(x=>x.classList.remove("on")); b.classList.add("on");
  mode=b.dataset.m; redraw(); if(!selected) street();
});

function drawScale(){
  const s=document.getElementById("scale");
  if(mode==="heat"){ s.innerHTML=`<b>Heat escaping on a cold day</b><div class="ramp" style="background:linear-gradient(90deg,${STOPS.map(([v,c])=>`rgb(${c}) ${v/55*100}%`).join(",")})"></div>
    <div class="ends"><span>0 W/m² · insulated</span><span>55 W/m² · uninsulated</span></div><div style="margin-top:6px;color:#666">Grey walls are shared with a neighbour.</div>`; }
  else if(mode==="start"){ s.innerHTML=`<b>Risk-adjusted saving: kWh/yr × confidence in the data</b><div class="ramp" style="background:linear-gradient(90deg,rgb(40,40,40),rgb(255,31,31))"></div>
    <div class="ends"><span>less</span><span>most kWh/year</span></div><div style="margin-top:6px;color:#666">Light grey: held back until the data is fixed.</div>`; }
  else { s.innerHTML=`<b>Can the records be trusted?</b><div class="legend-row" style="margin:8px 0 0">
    <span><i class="sw" style="background:#111"></i>Trust</span><span><i class="sw" style="background:#969696"></i>Caution</span><span><i class="sw" style="background:#FF3131"></i>Do not use</span></div>`; }
}

const fmt = n => n>=1000 ? (n/1000).toFixed(n>=10000?0:1)+"k" : String(Math.round(n));
function stackBar(lw, total){
  return `<div class="stack">${Object.keys(EL).map(k=>`<i title="${ELN[k]}" style="width:${100*lw[k]/total}%;background:${EL[k]}"></i>`).join("")}</div>
  <div class="legend-row">${Object.keys(EL).map(k=>`<span><i class="sw" style="background:${EL[k]}"></i>${ELN[k]} ${Math.round(100*lw[k]/total)}%</span>`).join("")}</div>`;
}

function street(fly){
  selected=null; redraw();
  if(fly) map.flyTo({center:START.center, zoom:START.zoom, pitch:58, bearing:-22, duration:1000});
  const s=D.street, tw=Object.values(s.by_element).reduce((a,b)=>a+b,0);
  const ranked=D.cards.filter(c=>c.priority_rank).sort((a,b)=>a.priority_rank-b.priority_rank).slice(0,6);
  document.getElementById("side").innerHTML=`
  <div class="k">Arlington Road, Camden · ${s.n} houses</div>
  <h1>Where this street loses heat, and where to start.</h1>
  <div class="big"><div><b>${s.total_kw} kW</b><span>lost on a cold day</span></div>
    <div><b>${s.hp_now_median} → ${s.hp_after_median} kW</b><span>typical heat pump: today → after fabric fixes</span></div></div>
  <h3>Where the heat goes</h3>${stackBar(s.by_element, tw)}
  <h3>Start here · savings × confidence in the data</h3>
  ${ranked.map(c=>`<div class="rank" onclick="pick('${c.uprn}')"><b>${c.priority_rank}</b><span>${c.address.replace(/,? ?Arlington Road/i,"").replace(/ARLINGTON ROAD/,"")} · ${c.measures[0]?c.measures[0].measure:""}</span>
    <span style="text-align:right">${fmt(c.risk_adjusted_kwh)} kWh</span></div>`).join("")}
  <div style="font-size:12px;color:#666;margin-top:8px">${s.held_back} houses held back: their records describe something other than a house.</div>
  <div class="note">Indicative heat-loss model: U-values from each home's EPC description × areas from its 3D twin; ${D.assumptions.design_day}; ${D.assumptions.heating_degree_days} heating degree days; window area ${D.assumptions.window_area}. Not a SAP assessment.
  Data: EPC open data (MHCLG); OS Open UPRN, contains OS data © Crown copyright 2026; outlines © OpenStreetMap contributors. Prototype by Eleni Karagianni.</div>`;
}

function pick(uprn){
  if(!uprn) return; selected=uprn; redraw(); const c=byId[uprn];
  map.flyTo({center:c.centroid, zoom:19.2, pitch:62, bearing:map.getBearing(), duration:1200});
  const t=c.trust, col=TRUST[t.verdict]||[150,150,150];
  const maxm=Math.max(1,...c.measures.map(m=>m.saves_kwh_yr));
  document.getElementById("side").innerHTML=`
  <span class="back" onclick="street(true)">← Whole street</span>
  <div class="k">${c.priority_rank?("Priority "+c.priority_rank+" of "+D.cards.filter(x=>x.priority_rank).length):"Held back"}</div>
  <h1 style="margin-bottom:4px">${c.address}</h1>
  <span class="badge" style="background:rgb(${col})">${TRUSTN[t.verdict]||"—"} · ${t.confidence??"—"}</span>
  <h3>Heat lost on a cold day · ${c.total_kw} kW</h3>${stackBar(c.loss_w, c.total_kw*1000)}
  <h3>Heat pump</h3>
  <div class="hp"><b>${c.hp_now_label} kW</b><em>today</em><b style="margin-left:8px">${c.hp_after_kw} kW</b><em>after fabric upgrades</em></div>
  <h3>What to fix first · all together save ${fmt(c.saving_all_kwh)} kWh/yr (${fmt(c.risk_adjusted_kwh)} risk-adjusted)</h3>
  ${c.measures.slice(0,4).map(m=>`<div class="meas"><div><span>${m.measure}</span><span>${fmt(m.saves_kwh_yr)} kWh/yr</span></div>
     <div class="mbar" style="width:${100*m.saves_kwh_yr/maxm}%;margin-top:5px"></div><small>${m.why} · ${m.saves_co2_t_yr} t CO₂/yr</small></div>`).join("")||"<div class='meas'>Nothing major.</div>"}
  <h3>Roof solar</h3><div style="font-size:13px">≈ ${c.solar_kwp} kWp · ≈ ${fmt(c.solar_kwh_yr)} kWh/yr</div>
  <details><summary>Why the data is ${t.verdict==="trust"?"trusted":"in doubt"}</summary><p style="margin-top:8px">${t.reasoning||""}</p>
    <p style="margin-top:8px"><b>What would settle it:</b> ${t.settle||""}</p></details>
  <details><summary>Inputs</summary><p style="margin-top:8px">EPC ${c.epc.rating} (${c.epc.date}): ${c.epc.walls}; ${c.epc.roof}; ${c.epc.floor}; ${c.epc.windows}; ${c.epc.heating}.<br>
    Twin: ${c.storeys} storeys${c.storeys_assumed?" (assumed)":""}, ${c.height} m; exposed walls ${c.A.walls} m², roof ${c.A.roof} m², windows ≈ ${c.A.windows} m²; floor area ${c.floor_area} m² (${c.floor_area_source}).<br>
    U-values: walls ${c.U.walls}, roof ${c.U.roof}, floor ${c.U.floor}, windows ${c.U.windows} W/m²K.</p></details>`;
  document.getElementById("side").scrollTop=0;
}
street(); drawScale();
</script></body></html>"""

out = pathlib.Path("outputs/street_twin.html"); out.parent.mkdir(exist_ok=True)
out.write_text(HTML.replace("__DATA__", json.dumps(DATA, default=str)))
print(f"Wrote {out}: {len(cards)} houses, {len(panels)} wall panels, {len(context)} context buildings; street {street}")
