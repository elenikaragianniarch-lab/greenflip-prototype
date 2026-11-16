"""
Step 12 - One page that holds everything: the street's digital twins, heat loss, overheating,
the agents' debate per building, the business case for two kinds of client, and what the checks changed.

Input : data/processed/street_buildings.json (Step 10), outputs/agents.json (Step 11), data/raw/osm/area_buildings.json
Output: outputs/arlington_demo.html  (self-contained; needs internet only for the map libraries)
"""
import json, math, pathlib, warnings, pyproj
warnings.filterwarnings("ignore")
S = json.loads(pathlib.Path("data/processed/street_buildings.json").read_text())
AG = json.loads(pathlib.Path("outputs/agents.json").read_text())
to_m = pyproj.Transformer.from_crs(4326, 27700, always_xy=True).transform
to_ll = pyproj.Transformer.from_crs(27700, 4326, always_xy=True).transform
SUNW = {"S": 1.0, "SW": 1.0, "W": 0.9, "SE": 0.7, "E": 0.5, "NW": 0.3, "NE": 0.2, "N": 0.0}
T, SH = 0.4, 3.0

panels, roofs, B = [], [], []
for b in S["buildings"]:
    r = AG["buildings"].get(b["id"], {})
    if not r.get("ruling"): continue
    ring = [to_m(*xy) for xy in b["ring"]]; cx, cy = to_m(*b["centroid"])
    n = int(round(b["storeys"]))
    for e in b["edges"]:
        ax, ay = to_m(*e["a"]); bx, by = to_m(*e["b"]); dx, dy = bx - ax, by - ay; L = math.hypot(dx, dy) or 1
        nx, ny = dy / L, -dx / L; mx, my = (ax + bx) / 2, (ay + by) / 2
        if (mx + nx - cx) ** 2 + (my + ny - cy) ** 2 < (mx - cx) ** 2 + (my - cy) ** 2: nx, ny = -nx, -ny
        quad = [to_ll(*p) for p in [(ax, ay), (bx, by), (bx + nx * T, by + ny * T), (ax + nx * T, ay + ny * T), (ax, ay)]]
        for s in range(n):
            panels.append({"b": b["id"], "p": [[round(x, 7), round(y, 7), s * SH] for x, y in quad], "party": e["party"],
                           "top": s == n - 1, "sun": SUNW[e["faces"]] >= 0.7})
    roofs.append({"b": b["id"], "p": [[round(x, 7), round(y, 7), n * SH] for x, y in b["ring"]]})
    hp = str(r["plan"].get("heat_pump", ""))
    r["plan"]["heat_pump"] = "ready_now" if "ready" in hp else "not_yet" if "not" in hp else "after_fabric"
    keep = ["id", "name", "kind", "homes", "homes_certified", "storeys", "storeys_assumed", "height", "footprint", "gia", "centroid", "U", "A", "loss_w", "total_kw", "flux",
            "annual_kwh", "bill_now_gbp", "co2_now_t", "measures", "fabric", "hp", "solar", "overheat", "flags", "sensitivity", "tenure", "ratings", "below_c", "age", "epc_words"]
    B.append({**{k: b[k] for k in keep}, "expl": (b.get("sceptic") or {}).get("likely_explanation"), "ag": r})

context = []
osm = pathlib.Path("data/raw/osm/area_buildings.json")
if osm.exists():
    from shapely.geometry import Polygon, Point
    pts = [Point(b["centroid"]) for b in B]
    for e in json.loads(osm.read_text())["elements"]:
        g = e.get("geometry", [])
        if len(g) < 4: continue
        poly = Polygon([(p["lon"], p["lat"]) for p in g])
        if not any(poly.contains(pt) for pt in pts): context.append([[round(p["lon"], 6), round(p["lat"], 6)] for p in g])

DATA = {"B": B, "panels": panels, "roofs": roofs, "context": context, "meta": S["meta"], "assume": S["assumptions"], "totals": AG["totals"], "memos": AG["memos"]}

HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arlington Road — retrofit twin</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.0.38/dist.min.js"></script>
<style>
:root{--ink:#111;--paper:#fafaf8;--line:#e4e2dc;--mute:#6b6b6b;--red:#FF3131}
*{box-sizing:border-box;margin:0;padding:0}body{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper);overflow:hidden;font-size:13px}
#map{position:absolute;inset:0 440px 0 0}
aside{position:absolute;top:0;right:0;bottom:0;width:440px;display:flex;flex-direction:column;background:var(--paper);border-left:1px solid var(--line)}
.top{padding:14px 22px 0;border-bottom:1px solid var(--line)}
.brand{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.brand b{font-size:12px;letter-spacing:.12em;text-transform:uppercase}
.seg{display:flex;border:1px solid var(--ink)}.seg button{border:0;background:none;font:inherit;font-size:12px;padding:5px 11px;cursor:pointer}.seg button.on{background:var(--ink);color:#fff}
.tabs{display:flex;gap:18px}.tabs button{border:0;background:none;font:inherit;font-size:12.5px;color:var(--mute);padding:8px 0;cursor:pointer;border-bottom:2px solid transparent}.tabs button.on{color:var(--ink);border-color:var(--ink)}
#pane{flex:1;overflow-y:auto;padding:18px 22px 30px}
.k{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute)}
h1{font-size:21px;line-height:1.18;margin:5px 0 12px;letter-spacing:-.01em}
h3{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin:20px 0 8px;font-weight:600}
.modes{position:absolute;top:14px;left:14px;display:flex;background:#fff;border:1px solid var(--line);z-index:2}
.modes button{border:0;background:none;padding:9px 13px;font:inherit;font-size:12.5px;cursor:pointer;color:var(--mute)}.modes button.on{background:var(--ink);color:#fff}
#scale{position:absolute;left:14px;bottom:18px;background:rgba(255,255,255,.94);border:1px solid var(--line);padding:10px 12px;font-size:11px;z-index:2;width:270px}
#scale .ramp{height:8px;margin:6px 0 3px}.ends{display:flex;justify-content:space-between;color:var(--mute)}
.lg{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:11px;color:#444}.lg span{display:flex;align-items:center;gap:5px}.sw{width:9px;height:9px;display:inline-block}
.stack{display:flex;height:20px;margin:6px 0 5px}.stack i{display:block;height:100%}
.ladder{border-top:1px solid var(--ink)}.rung{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:9px 0;border-bottom:1px solid var(--line)}
.rung b{font-size:13.5px}.rung .n{font-size:19px;font-weight:700;letter-spacing:-.02em;text-align:right;white-space:nowrap}.rung small{color:var(--mute);font-size:11.5px}.rung .bar{grid-column:1/3;height:5px;background:var(--line);margin-top:4px}.rung .bar i{display:block;height:100%;background:var(--ink)}
.memo{background:#f1efe9;padding:12px 14px;margin-top:6px;font-size:12.5px;line-height:1.5}.memo b{display:block;font-size:14px;line-height:1.35;margin-bottom:6px}.memo li{margin:4px 0 4px 16px}.memo em{display:block;color:var(--mute);font-style:normal;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px}
.rank{display:grid;grid-template-columns:20px 1fr auto;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line);cursor:pointer}.rank:hover{background:#f0eee8}.rank b{color:var(--mute);font-size:12px}.rank small{color:var(--mute)}
.badge{display:inline-block;font-size:10px;letter-spacing:.08em;text-transform:uppercase;padding:3px 7px;color:#fff;margin:0 4px 4px 0}
.back{font-size:12px;color:var(--mute);cursor:pointer;display:inline-block;margin-bottom:8px}
table{width:100%;border-collapse:collapse;font-size:12.5px}td,th{padding:6px 4px;border-bottom:1px solid var(--line);text-align:right}td:first-child,th:first-child{text-align:left;padding-left:0}th{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600}
.tag{font-size:10px;padding:2px 6px;border:1px solid var(--ink);white-space:nowrap}.tag.now{background:var(--ink);color:#fff}.tag.no{border-color:#bbb;color:#999}
.say{display:grid;grid-template-columns:86px 1fr;gap:10px;padding:9px 0;border-bottom:1px solid var(--line);line-height:1.45;font-size:12.5px}.say i{font-style:normal;font-size:10px;letter-spacing:.1em;text-transform:uppercase;font-weight:700}.say ul{margin-left:14px}
.big2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:4px 0}.big2 div b{display:block;font-size:22px;letter-spacing:-.02em;white-space:nowrap}.big2 div span{font-size:11.5px;color:var(--mute)}
details{margin-top:14px;font-size:12px;line-height:1.5;color:#333}summary{cursor:pointer;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute)}
.flow{display:grid;grid-template-columns:1fr 14px 1fr 14px 1fr;align-items:stretch;margin:6px 0}.flow div{border:1px solid var(--ink);padding:8px;font-size:11.5px;line-height:1.35}.flow div b{display:block;font-size:12px;margin-bottom:3px}.flow span{align-self:center;text-align:center}
#how{position:fixed;inset:0;z-index:30;background:var(--paper);overflow-y:auto;display:none}#how .in{width:min(1180px,94vw);margin:34px auto 60px}
#how h2{font-size:34px;letter-spacing:-.02em;line-height:1.1;margin:6px 0 10px}#how .sub{font-size:15px;color:#444;max-width:820px;line-height:1.5;margin-bottom:22px}
.cols{display:grid;grid-template-columns:1fr 1fr 1fr;gap:26px;margin-top:26px}.cols h4{font-size:11px;letter-spacing:.14em;text-transform:uppercase;border-top:2px solid var(--ink);padding-top:8px;margin-bottom:8px}
.cols li{font-size:13px;line-height:1.45;margin:0 0 6px 16px}.pill{display:inline-block;font-size:10px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--ink);padding:2px 7px;margin-left:8px;vertical-align:middle}
#how .close{position:sticky;top:0;float:right;background:var(--ink);color:#fff;border:0;font:inherit;padding:9px 14px;cursor:pointer}
#hero{position:fixed;inset:0;z-index:20;background:rgba(250,250,248,.97);display:flex;align-items:center;justify-content:center}
#hero .in{width:min(1100px,92vw)}#hero .k{margin-bottom:10px}#hero h2{font-size:44px;line-height:1.05;letter-spacing:-.025em;max-width:900px}
#hero h2 span{color:var(--red)}#hero .sub{font-size:17px;color:#444;margin:14px 0 30px;max-width:760px;line-height:1.45}
.lad{display:grid;grid-template-columns:200px 1fr 170px;gap:10px 18px;align-items:center;margin-bottom:30px}
.lad .l{font-size:14px;font-weight:700}.lad .l small{display:block;font-weight:400;color:var(--mute);font-size:12px}
.lad .b{height:34px;background:#e3e1da;position:relative}.lad .b i{position:absolute;inset:0 auto 0 0;display:block}
.lad .v{font-size:24px;font-weight:700;letter-spacing:-.02em}.lad .v small{display:block;font-size:12px;font-weight:400;color:var(--mute)}
.proc{display:grid;grid-template-columns:1fr 18px 1fr 18px 1fr 18px 1.25fr 18px 1fr;align-items:stretch;margin-bottom:26px}.proc em{align-self:center;text-align:center;font-style:normal;font-size:18px}.proc div{border:1.5px solid #111;padding:10px 12px;background:#fff}.proc div.ai{background:#111;color:#fff}.proc i{font-style:normal;font-size:11px;color:#999;display:block}.proc b{display:block;font-size:15px;margin:2px 0 4px}.proc span{font-size:12px;color:#666;line-height:1.35}.proc div.ai span{color:#bbb}
.trio{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:28px}.trio div{border-top:3px solid var(--ink);padding-top:8px;font-size:13.5px;line-height:1.4}
.trio b{display:block;font-size:15px;margin-bottom:2px}#hero button.go{background:var(--ink);color:#fff;border:0;font:inherit;font-size:15px;padding:13px 22px;cursor:pointer}
#strip{position:absolute;top:58px;left:14px;right:454px;z-index:2;display:flex;gap:0;background:#111;color:#fff;font-size:12.5px;cursor:pointer}
#strip div{padding:8px 14px;border-right:1px solid #333}#strip b{font-size:15px;margin-right:6px}
p.t{line-height:1.5;margin:6px 0;font-size:12.5px}.note{font-size:10.5px;color:#888;line-height:1.5;margin-top:20px}
</style></head><body>
<div id="map"></div>
<div id="hero"><div class="in"><div class="k"><span style="background:#111;color:#fff;padding:3px 8px;margin-right:8px">Prototype</span>Arlington Road, Camden · public data only · built in one evening by Eleni Karagianni</div>
<h2>A £9.8m retrofit wish-list, turned into <span>£376k you can fund tomorrow</span> and a survey list of 70.</h2>
<div class="sub">Every building becomes a heat-loss twin; three AI agents decide what is safe to fund.</div>
<div class="proc">
<div><i>1</i><b>Public data</b><span>EPC · OS · OpenStreetMap</span></div><em>→</em>
<div><i>2</i><b>3D twin</b><span>Python · shapely</span></div><em>→</em>
<div><i>3</i><b>Physics + cost</b><span>U × A × ΔT · £ · CO₂</span></div><em>→</em>
<div class="ai"><i>4</i><b>3 AI agents</b><span>Sceptic · Strategist · Challenger<br>Claude API</span></div><em>→</em>
<div><i>5</i><b>Funding plan</b><span>deck.gl 3D map</span></div></div>

<div id="lad" class="lad"></div>
<button class="go" onclick="document.getElementById('hero').remove()">Explore the street in 3D →</button> <button class="go" style="background:#fff;color:#111;border:1px solid #111;margin-left:8px" onclick="document.getElementById('hero').remove();showHow()">How it's built, and its limits</button><p style="font-size:12px;color:#777;margin-top:14px;max-width:760px">A working prototype, not a product: figures are indicative (not a SAP assessment), costs are typical unit rates, and nothing has yet been validated against surveyed homes.</p></div></div>
<div id="how"><div class="in"><button class="close" onclick="hideHow()">Close ✕</button>
<div class="k"><span style="background:#111;color:#fff;padding:3px 8px;margin-right:8px">Prototype</span>How it's built</div>
<h2>Code does the maths. AI judges and explains.</h2>
<svg viewBox="0 0 1180 470" width="100%" style="display:block;background:#f4f2ec;border:1px solid #e4e2dc" font-family="Helvetica Neue,Helvetica,Arial,sans-serif">
<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#111"/></marker></defs>
<g font-size="11" fill="#111">
<text x="20" y="30" font-size="11" letter-spacing="1.5" fill="#6b6b6b">1 · PUBLIC DATA</text>
<rect x="20" y="42" width="190" height="56" fill="#fff" stroke="#111"/><text x="30" y="62" font-weight="700">EPC register</text><text x="30" y="78">670 certificates, 93 fields</text><text x="30" y="92" fill="#6b6b6b">MHCLG bulk download</text>
<rect x="20" y="108" width="190" height="56" fill="#fff" stroke="#111"/><text x="30" y="128" font-weight="700">OS Open UPRN</text><text x="30" y="144">address point per home</text><text x="30" y="158" fill="#6b6b6b">OS Features API</text>
<rect x="20" y="174" width="190" height="56" fill="#fff" stroke="#111"/><text x="30" y="194" font-weight="700">OpenStreetMap</text><text x="30" y="210">building outlines, storeys</text><text x="30" y="224" fill="#6b6b6b">Overpass API</text>
<rect x="20" y="240" width="190" height="56" fill="#fff" stroke="#111"/><text x="30" y="260" font-weight="700">Prices and grants</text><text x="30" y="276">Ofgem cap Oct–Dec 2026</text><text x="30" y="290" fill="#6b6b6b">£7,500 Boiler Upgrade Scheme</text>
<text x="250" y="30" letter-spacing="1.5" fill="#6b6b6b">2 · TWIN PER BUILDING</text>
<rect x="250" y="42" width="200" height="122" fill="#fff" stroke="#111"/><text x="262" y="62" font-weight="700">Geometry</text><text x="262" y="80">homes placed in outlines</text><text x="262" y="96">exposed vs party walls</text><text x="262" y="112">storeys, roof, orientation</text><text x="262" y="128">77 buildings, ~1,166 homes</text><text x="262" y="150" fill="#6b6b6b">pandas · shapely · pyproj</text>
<rect x="250" y="174" width="200" height="122" fill="#fff" stroke="#111"/><text x="262" y="194" font-weight="700">Physics and cost</text><text x="262" y="212">U-values from EPC wording</text><text x="262" y="228">heat loss = U × A × ΔT + air</text><text x="262" y="244">heat pump size, overheating</text><text x="262" y="260">each fix: £, saving, payback, CO₂</text><text x="262" y="282" fill="#6b6b6b">plain Python, no AI</text>
<text x="490" y="30" letter-spacing="1.5" fill="#6b6b6b">3 · RULE CHECKS</text>
<rect x="490" y="42" width="190" height="254" fill="#fff" stroke="#111"/><text x="502" y="62" font-weight="700">Contradictions</text><text x="502" y="82">certificate vs certificate</text><text x="502" y="98">certificate vs geometry</text><text x="502" y="114">missing address IDs (40)</text><text x="502" y="130">flats disagreeing on walls</text><text x="502" y="146">assumed storey counts</text><text x="502" y="162">expired certificates</text><text x="502" y="186" font-weight="700">Output</text><text x="502" y="204">flags with evidence +</text><text x="502" y="220">a confidence score</text><text x="502" y="282" fill="#6b6b6b">plain Python, no AI</text>
<text x="720" y="30" letter-spacing="1.5" fill="#6b6b6b">4 · THREE AGENTS PER BUILDING</text>
<rect x="720" y="42" width="250" height="254" fill="#111"/><g fill="#fff">
<text x="734" y="64" font-weight="700">Sceptic</text><text x="734" y="80">audits the data: trust / caution / do not use</text>
<text x="734" y="112" font-weight="700">Strategist</text><text x="734" y="128">picks fixes from the costed list</text>
<text x="734" y="160" font-weight="700">Challenger</text><text x="734" y="176">objects, then splits the plan:</text><text x="734" y="192">start now / survey first</text>
<text x="734" y="222" fill="#bbb">Claude Sonnet 5.5 via API</text><text x="734" y="238" fill="#bbb">fixed answer forms (tool use)</text><text x="734" y="254" fill="#bbb">~231 calls, run once, cached</text><text x="734" y="280" fill="#FF3131" font-weight="700">AI used here</text></g>
<line x1="845" y1="86" x2="845" y2="100" stroke="#fff" marker-end="url(#ar)"/><line x1="845" y1="134" x2="845" y2="148" stroke="#fff" marker-end="url(#ar)"/>
<text x="1010" y="30" letter-spacing="1.5" fill="#6b6b6b">5 · OUTPUT</text>
<rect x="1010" y="42" width="150" height="122" fill="#fff" stroke="#111"/><text x="1022" y="62" font-weight="700">Code re-adds</text><text x="1022" y="80">every total from</text><text x="1022" y="96">the agents' picks</text><text x="1022" y="120" font-weight="700">Memo agent</text><text x="1022" y="138">writes from those</text><text x="1022" y="152">totals only</text>
<rect x="1010" y="174" width="150" height="122" fill="#fff" stroke="#111"/><text x="1022" y="194" font-weight="700">This page</text><text x="1022" y="212">one HTML file</text><text x="1022" y="228">deck.gl 3D twins</text><text x="1022" y="244">MapLibre basemap</text><text x="1022" y="282" fill="#6b6b6b">no server needed</text>
<line x1="212" y1="170" x2="246" y2="170" stroke="#111" marker-end="url(#ar)"/><line x1="452" y1="170" x2="486" y2="170" stroke="#111" marker-end="url(#ar)"/><line x1="682" y1="170" x2="716" y2="170" stroke="#111" marker-end="url(#ar)"/><line x1="972" y1="104" x2="1006" y2="104" stroke="#111" marker-end="url(#ar)"/><line x1="1085" y1="166" x2="1085" y2="172" stroke="#111"/>
<text x="20" y="330" letter-spacing="1.5" fill="#6b6b6b">GUARDRAILS ON THE AGENTS</text>
<g font-size="12"><rect x="20" y="342" width="270" height="104" fill="#fff" stroke="#111"/><text x="32" y="364" font-weight="700">No maths, no new numbers</text><text x="32" y="382">Agents receive computed figures</text><text x="32" y="398">and may only choose among them.</text><text x="32" y="414">Invented values are rejected.</text>
<rect x="306" y="342" width="270" height="104" fill="#fff" stroke="#111"/><text x="318" y="364" font-weight="700">Fixed answer forms</text><text x="318" y="382">Each agent fills a JSON schema:</text><text x="318" y="398">verdict, picks, reasons, condition.</text><text x="318" y="414">Code validates every field.</text>
<rect x="592" y="342" width="270" height="104" fill="#fff" stroke="#111"/><text x="604" y="364" font-weight="700">Decisions derived by code</text><text x="604" y="382">"Start now" is computed from the</text><text x="604" y="398">Challenger's own split, and "do not</text><text x="604" y="414">use" data always blocks funding.</text>
<rect x="878" y="342" width="282" height="104" fill="#fff" stroke="#111"/><text x="890" y="364" font-weight="700">Confidence discounts ranking</text><text x="890" y="382">Saving × data confidence, so</text><text x="890" y="398">doubtful records can't reach</text><text x="890" y="414">the top of a funding list.</text></g>
</g></svg>
<div class="cols">
<div><h4>Tech stack</h4><ul><li>Python · pandas · shapely · pyproj</li><li>OS Features API · Overpass · EPC bulk data</li><li>Claude Sonnet 5.5 · tool use · cached JSON</li><li>deck.gl · MapLibre · one HTML file</li><li>12 scripts on GitHub</li></ul></div>
<div><h4>AI vs code</h4><ul><li><b>Code:</b> geometry, heat loss, costs, checks, every total</li><li><b>AI:</b> trust the data? which fixes? what could go wrong?</li><li>Built with AI-assisted coding (Claude)</li></ul></div>
<div><h4>Honest limits</h4><ul><li>Not validated against surveyed homes</li><li>Not a SAP assessment; costs are typical rates</li><li>Storeys assumed for 44 of 77 buildings</li><li>Listed status not checked</li></ul></div></div>
<h4 style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;border-top:2px solid #111;padding-top:8px;margin:28px 0 8px">Next, with Greenflip's data</h4>
<p style="font-size:14px;line-height:1.55">Validate on surveyed homes → add OS NGD heights and floors → calibrate the agents on real costs.</p>
</div></div>
<div id="strip" onclick="go('agents')"></div>
<div class="modes" id="modes"></div><div id="scale"></div>
<aside><div class="top"><div class="brand"><b>Arlington Road · retrofit twin</b><div class="seg" id="client"><button data-c="investor" class="on">Investor</button><button data-c="council">Council</button></div></div>
<div class="tabs" id="tabs"></div></div><div id="pane"></div></aside>
<script>
const D=__DATA__, B=D.B, byId=Object.fromEntries(B.map(b=>[b.id,b]));
let mode="heat", client="investor", tab="street", sel=null;
const EL={"walls":"#c8402b","roof":"#e98a3f","windows":"#4f7cac","floor":"#8a7f6e","air leakage":"#b9b4aa"}, ELN={"walls":"Walls","roof":"Roof","windows":"Windows","floor":"Floor","air leakage":"Draughts"};
const VC={trust:[17,17,17],use_with_caution:[150,150,150],do_not_use:[255,49,49]}, VN={trust:"Data: trusted",use_with_caution:"Data: caution",do_not_use:"Data: do not use"};
const DC={fund_now:[17,17,17],survey_first:[150,150,150],fix_data_first:[255,49,49]}, DN={fund_now:"Start now",survey_first:"Survey first",fix_data_first:"Fix data first"};
const MODES=[["heat","Heat loss"],["over","Overheating"],["start","Where to start"],["decision","Agents' decision"],["trust","Data trust"]];
const gbp=n=>"£"+(Math.abs(n)>=1e6?(n/1e6).toFixed(2)+"m":Math.abs(n)>=1e4?Math.round(n/1e3)+"k":Math.abs(n)>=1e3?(n/1e3).toFixed(1)+"k":Math.round(n));
const esc=s=>String(s??"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function lerp(stops,v){for(let i=1;i<stops.length;i++){const[a,ca]=stops[i-1],[b,cb]=stops[i];if(v<=b){const t=Math.max(0,(v-a)/(b-a));return ca.map((x,j)=>Math.round(x+(cb[j]-x)*t));}}return stops[stops.length-1][1];}
const HEAT=[[0,[236,233,226]],[10,[244,206,150]],[25,[236,140,74]],[40,[210,66,40]],[55,[120,22,16]]], OVER=[[0,[240,236,228]],[35,[247,200,120]],[60,[226,90,110]],[100,[110,14,96]]], START=[[0,[225,223,216]],[1,[20,20,20]]];
// per-building plan economics (code sums the costed measures the agents picked)
B.forEach(b=>{const pk=b.ag.plan.package, ok=b.ag.ruling.approved_package, m=b.measures; const sum=(keys,f)=>m.filter(x=>keys.includes(x.key)).reduce((a,x)=>a+x[f],0);
  b.conf=b.ag.sceptic.confidence??50; b.dec=b.ag.ruling.decision;
  b.plan={capex:sum(pk,"capex"),gbp:sum(pk,"saves_gbp"),co2:sum(pk,"saves_co2_t")}; b.now={capex:sum(ok,"capex"),gbp:sum(ok,"saves_gbp"),co2:sum(ok,"saves_co2_t")};
  b.social=(b.tenure["social rent"]||0);
  b.score={investor:b.plan.capex?b.plan.gbp*b.conf/100/b.plan.capex*100:0, council:b.plan.capex?b.plan.co2*b.conf/100/b.plan.capex*1e5:0};});
function ranked(){return B.filter(b=>b.dec!=="fix_data_first"&&b.plan.capex>0).sort((a,b)=>b.score[client]-a.score[client]);}
let RK={}; function rerank(){RK={};ranked().forEach((b,i)=>RK[b.id]=i+1);} rerank();
function color(p,roof){const b=byId[p.b]; if(p.party) return [212,211,205];
  if(mode==="heat") return lerp(HEAT,roof?b.flux.roof:b.flux.walls);
  if(mode==="over"){const k=roof?0.9:(p.top&&p.sun?1:p.top?0.75:p.sun?0.6:0.35);return lerp(OVER,b.overheat.score*k);}
  if(mode==="start"){const r=RK[b.id]; return r?lerp(START,1-(r-1)/Math.max(1,Object.keys(RK).length-1)*0.85):[255,190,190];}
  if(mode==="decision") return DC[b.dec]; return VC[b.ag.sceptic.verdict]||[150,150,150];}
const A=(id,c)=>sel&&sel!==id?[...c,45]:[...c,255];
function layers(){return[
  new deck.PolygonLayer({id:"ctx",data:D.context,getPolygon:d=>d,stroked:false,getFillColor:[232,231,226]}),
  new deck.PolygonLayer({id:"w",data:D.panels,getPolygon:d=>d.p,extruded:true,getElevation:2.82,pickable:true,getFillColor:d=>A(d.b,color(d,false)),updateTriggers:{getFillColor:[mode,sel,client]},material:{ambient:.6,diffuse:.45,shininess:6},onClick:i=>i.object&&pick(i.object.b)}),
  new deck.PolygonLayer({id:"r",data:D.roofs,getPolygon:d=>d.p,extruded:true,getElevation:.3,pickable:true,getFillColor:d=>A(d.b,color(d,true)),updateTriggers:{getFillColor:[mode,sel,client]},material:{ambient:.65,diffuse:.4},onClick:i=>i.object&&pick(i.object.b)})];}
const map=new maplibregl.Map({container:"map",style:"https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",center:[-0.1432,51.5372],zoom:16.4,antialias:true});
const tip=b=>mode==="heat"?b.total_kw+" kW lost on a cold day":mode==="over"?"Overheating risk: "+b.overheat.band:mode==="start"?(RK[b.id]?"Priority "+RK[b.id]:"Held back"):mode==="decision"?DN[b.dec]:VN[b.ag.sceptic.verdict];
const overlay=new deck.MapboxOverlay({interleaved:false,layers:layers(),getTooltip:({object})=>object&&byId[object.b]&&{text:byId[object.b].name+"\n"+tip(byId[object.b]),style:{fontSize:"12px"}}});
map.addControl(overlay); map.addControl(new maplibregl.NavigationControl({visualizePitch:true}),"top-right");
const xs=B.map(b=>b.centroid[0]),ys=B.map(b=>b.centroid[1]),HOME=[[Math.min(...xs),Math.min(...ys)],[Math.max(...xs),Math.max(...ys)]];
const home=d=>map.fitBounds(HOME,{padding:{top:70,bottom:70,left:40,right:40},pitch:56,bearing:-24,duration:d});
map.on("load",()=>home(0));
function redraw(){overlay.setProps({layers:layers()});scale();}
function scale(){const s=document.getElementById("scale"),g=st=>`linear-gradient(90deg,${st.map(([v,c])=>`rgb(${c}) ${v/st[st.length-1][0]*100}%`).join(",")})`;
  const dots=(o,n)=>`<div class="lg" style="margin-top:8px">${Object.keys(o).map(k=>`<span><i class="sw" style="background:rgb(${o[k]})"></i>${n[k]}</span>`).join("")}</div>`;
  s.innerHTML=mode==="heat"?`<b>Heat escaping through each wall and roof on a cold day</b><div class="ramp" style="background:${g(HEAT)}"></div><div class="ends"><span>insulated</span><span>55 W/m² · bare brick</span></div><div style="color:#666;margin-top:5px">Grey = wall shared with a neighbour.</div>`
  :mode==="over"?`<b>Summer overheating risk</b><div class="ramp" style="background:${g(OVER)}"></div><div class="ends"><span>low</span><span>high</span></div><div style="color:#666;margin-top:5px">Strongest on sun-facing top floors.</div>`
  :mode==="start"?`<b>${client==="investor"?"Return on each £, discounted by data confidence":"Carbon cut per £, discounted by data confidence"}</b><div class="ramp" style="background:${g(START)}"></div><div class="ends"><span>later</span><span>first</span></div><div style="color:#666;margin-top:5px">Pink = held back until the data is fixed.</div>`
  :mode==="decision"?`<b>What the three agents ruled</b>${dots(DC,DN)}`:`<b>Can the records be trusted?</b>${dots(VC,VN)}`;}
function stack(lw){const t=Object.values(lw).reduce((a,b)=>a+b,0);return `<div class="stack">${Object.keys(EL).map(k=>`<i style="width:${100*lw[k]/t}%;background:${EL[k]}"></i>`).join("")}</div><div class="lg">${Object.keys(EL).map(k=>`<span><i class="sw" style="background:${EL[k]}"></i>${ELN[k]} ${Math.round(100*lw[k]/t)}%</span>`).join("")}</div>`;}
function bars(o,cols){const t=Object.values(o).reduce((a,b)=>a+b,0),ks=Object.keys(cols).filter(k=>o[k]);return `<div class="stack" style="height:12px">${ks.map(k=>`<i style="width:${100*o[k]/t}%;background:${cols[k]}"></i>`).join("")}</div><div class="lg">${ks.map(k=>`<span><i class="sw" style="background:${cols[k]}"></i>${k} ${o[k]}</span>`).join("")}</div>`;}

// ---------- street ----------
function street(){const T=D.totals,M=D.meta,m=D.memos[client]||{},inv=client==="investor";
  const lw={};Object.keys(EL).forEach(k=>lw[k]=B.reduce((a,b)=>a+b.loss_w[k],0));
  const rung=(n,sub,t,w)=>`<div class="rung"><div><b>${n}</b><br><small>${sub}</small></div><div class="n">${inv?gbp(t.capex_gbp)+" → "+gbp(t.bill_saving_gbp_per_year)+"/yr":t.co2_saved_t_per_year+" tCO₂/yr"}<br><small>${inv?t.simple_payback_years+"-year payback · "+t.co2_saved_t_per_year+" tCO₂/yr":gbp(t.capex_gbp)+" · "+gbp(Math.round(t.capex_gbp/Math.max(1,t.co2_saved_t_per_year)/15))+" per tonne over 15 yrs"}</small></div><div class="bar"><i style="width:${w}%"></i></div></div>`;
  const top=ranked().slice(0,6), mx=T.full_fabric_if_all_confirmed[inv?"capex_gbp":"co2_saved_t_per_year"], w=t=>Math.max(2,100*t[inv?"capex_gbp":"co2_saved_t_per_year"]/mx);
  return `<div class="k">${M.placed} homes · ${B.length} buildings · every one a digital twin built from public data</div>
  <h1>${inv?"Where the first pound should go on this street, and what it returns.":"Which homes to treat first, and what each pound of budget buys."}</h1>
  <h3>The funding ladder the agents built</h3><div class="ladder">
  ${rung("1 · Start now","No-regret measures the agents cleared without a visit",T.approved_now,w(T.approved_now))}
  ${rung("2 · After a targeted survey",T.survey_visits_needed+" buildings, one named question each",T.after_survey,w(T.after_survey))}
  ${rung("3 · Everything, unchecked","What a model without the agents would recommend",T.full_fabric_if_all_confirmed,100)}</div>
  <div class="memo"><em>Memo written by the agent from these totals</em><b>${esc(m.headline)}</b><details style="margin-top:4px"><summary>Read the memo</summary><ul>${(m.points||[]).map(p=>`<li>${esc(p)}</li>`).join("")}</ul><p style="margin-top:6px"><b style="display:inline;font-size:12.5px">Next step:</b> ${esc(m.ask)}</p></details></div>
  <h3>Where the street loses heat · ${T.peak_heat_loss_kw.toLocaleString()} kW on a cold day</h3>${stack(lw)}
  <h3>${inv?"Best risk-adjusted returns":"Most carbon per pound"} · click to fly there</h3>
  ${top.map((b,i)=>`<div class="rank" onclick="pick('${b.id}')"><b>${i+1}</b><span>${esc(b.name)} <small>· ${b.homes>1?b.homes+" homes":"house"}${b.social?" · "+b.social+" social rent":""}</small></span><span>${inv?(b.score.investor).toFixed(1)+"% /yr":(b.score.council).toFixed(1)+" t per £100k"}</span></div>`).join("")}
  <h3>Who lives here · why ${inv?"landlords":"the council"} should care</h3>
  ${bars(M.tenure,{"social rent":"#111","private rent":"#777","owner-occupied":"#b5b1a8","unknown":"#dedbd3"})}
  <p class="t" style="margin-top:8px">${B.reduce((a,b)=>a+b.below_c,0)} of ${M.placed} certified homes are rated D or worse. ${inv?"Rented homes below C are the ones exposed if minimum standards tighten; this page shows which, and the cheapest route up.":"Over half the certified homes are social rent, and "+T.overheating_high_buildings+" buildings carry a high overheating risk that insulation alone can make worse."}</p>
  <div class="note">Indicative model, not a SAP or PAS 2035 assessment. ${esc(D.assume.prices)}. Costs are editable unit rates. Data: EPC open data (MHCLG); OS Open UPRN, contains OS data © Crown copyright 2026; outlines © OpenStreetMap contributors. Prototype by Eleni Karagianni.</div>`;}

// ---------- building section drawing ----------
function section(b){const W=396,H=230,n=Math.min(7,Math.round(b.storeys)),bw=b.kind==="house"?92:150,sh=Math.min(30,138/n),x0=(W-bw)/2,g=186,top=g-n*sh,t=Object.values(b.loss_w).reduce((a,c)=>a+c,0),pc=k=>Math.round(100*b.loss_w[k]/t);
  const pitched=/pitched|roof room/i.test(b.epc_words.roof), hot=b.overheat.band!=="low", base=b.expl==="basement_or_lower_ground", sunL=["W","SW","S","NW"].includes(b.overheat.sunny_face||"");
  const ar=(x1,y1,x2,y2,k)=>{const w=2+16*b.loss_w[k]/t,a=Math.atan2(y2-y1,x2-x1),hx=x2-Math.cos(a)*(w+5),hy=y2-Math.sin(a)*(w+5),px=Math.sin(a)*(w/2+4),py=-Math.cos(a)*(w/2+4);
    return `<line x1="${x1}" y1="${y1}" x2="${hx}" y2="${hy}" stroke="${EL[k]}" stroke-width="${w}"/><polygon points="${x2},${y2} ${hx+px},${hy+py} ${hx-px},${hy-py}" fill="${EL[k]}"/>`;};
  const lab=(x,y,k,anc)=>`<text x="${x}" y="${y}" text-anchor="${anc||"middle"}" font-size="11" font-weight="700" fill="${EL[k]==="#b9b4aa"?"#777":EL[k]}">${ELN[k]} ${pc(k)}%</text>`;
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block;background:#f4f2ec">`;
  s+=`<line x1="0" y1="${g}" x2="${W}" y2="${g}" stroke="#111"/>`;
  if(b.kind==="house") s+=`<rect x="${x0-58}" y="${top+6}" width="58" height="${g-top-6}" fill="#e2e0d9"/><rect x="${x0+bw}" y="${top+6}" width="58" height="${g-top-6}" fill="#e2e0d9"/><text x="${x0-29}" y="${g-8}" text-anchor="middle" font-size="9" fill="#888">neighbour</text><text x="${x0+bw+29}" y="${g-8}" text-anchor="middle" font-size="9" fill="#888">neighbour</text>`;
  for(let i=0;i<n;i++){const y=g-(i+1)*sh,isTop=i===n-1; s+=`<rect x="${x0}" y="${y}" width="${bw}" height="${sh}" fill="${isTop&&hot?"rgba(226,90,110,.38)":"#fff"}" stroke="#111"/>`;
    s+=`<rect x="${x0+bw*0.3}" y="${y+sh*0.25}" width="${bw*0.16}" height="${sh*0.5}" fill="#cfe0f0" stroke="#4f7cac" stroke-width=".8"/><rect x="${x0+bw*0.58}" y="${y+sh*0.25}" width="${bw*0.16}" height="${sh*0.5}" fill="#cfe0f0" stroke="#4f7cac" stroke-width=".8"/>`;}
  if(base) s+=`<rect x="${x0}" y="${g}" width="${bw}" height="22" fill="none" stroke="#111" stroke-dasharray="4 3"/><text x="${x0+bw/2}" y="${g+15}" text-anchor="middle" font-size="9.5" fill="#555">likely lower ground floor</text>`;
  s+=pitched?`<polygon points="${x0-4},${top} ${x0+bw/2},${top-20} ${x0+bw+4},${top}" fill="#fff" stroke="#111"/>`:`<rect x="${x0-3}" y="${top-5}" width="${bw+6}" height="5" fill="#111"/>`;
  const ry=top-(pitched?22:8); s+=ar(x0+bw/2,ry,x0+bw/2,ry-26,"roof")+lab(x0+bw/2+14,ry-14,"roof","start");
  const wy=g-n*sh*0.55, far=b.kind==="house"?70:26; s+=ar(x0+bw*0.5,wy,x0+bw+far+36,wy-34,"walls")+lab(x0+bw+far+38,wy-38,"walls","middle");
  s+=ar(x0+bw*0.38,g-sh*0.5,x0-far-34,g-sh*0.5-30,"windows")+lab(x0-far-36,g-sh*0.5-36,"windows","middle");
  s+=ar(x0+bw/2,g-2,x0+bw/2,g+(base?26:24),"floor")+lab(x0+bw/2+14,g+(base?38:20),"floor","start");
  s+=`<path d="M${x0+bw*0.8} ${top+sh*0.5} q14 -10 28 0 t28 0" fill="none" stroke="#999" stroke-width="${2+10*b.loss_w["air leakage"]/t}" stroke-dasharray="5 4"/>`+lab(W-8,top+sh*0.5+16,"air leakage","end");
  const sx=sunL?26:W-26; s+=`<circle cx="${sx}" cy="24" r="10" fill="#f2b632"/><text x="${sx}" y="48" text-anchor="middle" font-size="9.5" fill="#555">${b.overheat.sunny_face?"sun: "+b.overheat.sunny_face:"little direct sun"}</text>`;
  if(hot) s+=`<text x="${x0+bw/2}" y="${top+sh/2+4}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#8a1244">overheats</text>`;
  return s+`</svg>`;}

// ---------- building card ----------
function card(b){const a=b.ag,pk=a.plan.package,ok=a.ruling.approved_package,inv=client==="investor",many=b.homes>1;
  const tag=m=>`<span class="tag ${ok.includes(m.key)?"now":pk.includes(m.key)?"":"no"}" style="cursor:pointer" onclick="toDebate()">${ok.includes(m.key)?"start now":pk.includes(m.key)?"after survey":"not in plan"}</span>`;
  const hpn={ready_now:"ready now",after_fabric:"after the fabric work",not_yet:"not yet"}[a.plan.heat_pump];
  return `<span class="back" onclick="back()">← Whole street</span><div class="k">${RK[b.id]?"Priority "+RK[b.id]+" of "+Object.keys(RK).length+(inv?" for return":" for carbon per pound"):"Held back"} · ${b.kind==="house"?"house":b.homes_certified+" certified homes, about "+b.homes+" in the block"} · ${esc(b.age)}</div>
  <h1 style="margin-bottom:6px">${esc(b.name)}</h1>
  ${verdict(b)}
  <span class="badge" style="background:rgb(${DC[b.dec]});cursor:pointer" onclick="toDebate()">${DN[b.dec]} ↓</span><span class="badge" style="background:rgb(${VC[a.sceptic.verdict]||[150,150,150]});cursor:pointer" onclick="toDebate()">${VN[a.sceptic.verdict]} · ${b.conf}</span><span class="badge" style="background:${b.overheat.band==="high"?"#8a1244":b.overheat.band==="medium"?"#d9895a":"#aaa"}">Overheating ${b.overheat.band}</span>
  <h3>The twin · where ${b.total_kw} kW leaves on a cold day</h3>${section(b)}
  <div class="big2" style="margin-top:12px"><div><b>${b.hp.now_label} → ${b.hp.after_kw??">16"} kW</b><span>heat pump ${many?"per home":""}: today → after fabric · ${hpn}</span></div>
  <div><b>${gbp(b.plan.capex)} → ${gbp(b.plan.gbp)}/yr</b><span>agents' package · ${b.plan.gbp?(b.plan.capex/b.plan.gbp).toFixed(1):"–"}-yr payback · ${b.plan.co2.toFixed(1)} tCO₂/yr</span></div></div>
  <h3>Measures, costed</h3><table><tr><th>Measure</th><th>Cost</th><th>Saves/yr</th><th>Payback</th><th></th></tr>
  ${b.measures.map(m=>`<tr><td>${m.measure}</td><td>${gbp(m.capex)}</td><td>${gbp(m.saves_gbp)}</td><td>${m.payback_yrs} yr</td><td>${tag(m)}</td></tr>`).join("")}
  <tr><td>Heat pump${many?" ×"+b.homes:""}</td><td>${gbp(b.hp.capex-b.hp.grant)}</td><td>${b.hp.bill_change_gbp<=0?gbp(-b.hp.bill_change_gbp):"−"+gbp(b.hp.bill_change_gbp)}</td><td>${b.hp.co2_saved_t} tCO₂</td><td><span class="tag ${a.plan.heat_pump==="ready_now"?"now":""}">${hpn}</span></td></tr>
  <tr><td>Roof solar ${b.solar.kwp} kWp</td><td>${gbp(b.solar.capex)}</td><td>${gbp(b.solar.saves_gbp)}</td><td>${(b.solar.capex/Math.max(1,b.solar.saves_gbp)).toFixed(1)} yr</td><td></td></tr></table>
  <p class="t" style="color:#666;font-size:11.5px">Heat pump: the last column is carbon saved per year, not payback. ${b.hp.grant?"Heat pump cost is after the £7,500 Boiler Upgrade Scheme grant per home.":"Mostly social rent: no Boiler Upgrade Scheme grant assumed."} Heat pump row shows carbon saved, since bills stay roughly level.</p>
  <h3 id="debate">The agents' debate</h3>
  <div class="say"><i>Sceptic<br><span style="font-weight:400;color:#888">audits data</span></i><div>${esc(a.sceptic.reasoning)}</div></div>
  <div class="say"><i>Strategist<br><span style="font-weight:400;color:#888">proposes</span></i><div>${esc(a.plan.why)}<br><span style="color:#666">${esc(inv?a.plan.investor_line:a.plan.council_line)}</span></div></div>
  <div class="say"><i>Challenger<br><span style="font-weight:400;color:#888">objects, rules</span></i><div><ul>${a.ruling.objections.map(o=>`<li>${esc(o)}</li>`).join("")}</ul><p style="margin-top:6px"><b>${DN[b.dec]}.</b> ${esc(a.ruling.condition)}</p></div></div>
  <h3>Overheating · ${b.overheat.score}/100 · ${esc(b.overheat.where)}</h3><p class="t">${b.overheat.drivers.map(esc).join("; ")}. <b>${esc(a.plan.overheating_action)}</b></p>
  <details><summary>Data flags (${b.flags.length}) and inputs</summary><ul style="margin:8px 0 8px 16px">${b.flags.map(f=>`<li>${esc(f)}</li>`).join("")}</ul>
  <p>EPC wording: ${esc(b.epc_words.walls)}; ${esc(b.epc_words.roof)}; ${esc(b.epc_words.windows)}; ${esc(b.epc_words.heating)}. Ratings: ${Object.entries(b.ratings).map(([k,v])=>k+"×"+v).join(", ")}.<br>Twin: ${b.storeys} storeys${b.storeys_assumed?" (assumed)":""}, footprint ${b.footprint} m², exposed wall ${b.A.walls} m², windows ≈ ${b.A.windows} m², floor area ${b.gia} m². U-values: walls ${b.U.walls}, roof ${b.U.roof}, floor ${b.U.floor}, windows ${b.U.windows}.<br><b>What would settle it:</b> ${esc(a.sceptic.what_would_settle_it)}</p></details>`;}

function showHow(){document.getElementById("how").style.display="block";}
function hideHow(){document.getElementById("how").style.display="none";}
function toDebate(){const e=document.getElementById("debate");if(e)e.scrollIntoView({behavior:"smooth",block:"start"});}
function verdict(b){const a=b.ag,ok=a.ruling.approved_package,later=a.plan.package.filter(k=>!ok.includes(k)),M=Object.fromEntries(b.measures.map(m=>[m.key,m]));
  const line=(keys)=>keys.map(k=>M[k]&&M[k].measure).filter(Boolean).join(" + ");
  const sum=(keys,f)=>keys.reduce((x,k)=>x+(M[k]?M[k][f]:0),0);
  const box=(bg,fg,label,body)=>`<div style="background:${bg};color:${fg};padding:10px 12px;margin:2px 0 6px;display:grid;grid-template-columns:96px 1fr;gap:10px;align-items:baseline"><b style="font-size:10.5px;letter-spacing:.1em;text-transform:uppercase">${label}</b><span style="font-size:14px;line-height:1.35">${body}</span></div>`;
  let h="";
  if(b.dec==="fix_data_first") return box("#FF3131","#fff","Fix data first",`The records don't describe this building reliably. ${esc(a.sceptic.what_would_settle_it)}`);
  if(ok.length) h+=box("#111","#fff","Start now",`<b>${line(ok)}</b>: ${gbp(sum(ok,"capex"))} → saves ${gbp(sum(ok,"saves_gbp"))}/yr`);
  if(later.length) h+=box("#e6e4de","#111","Survey first",`<b>${line(later)}</b>: ${gbp(sum(later,"capex"))} → ${gbp(sum(later,"saves_gbp"))}/yr, if the survey confirms it. <span style="color:#555">${esc(a.ruling.condition)}</span>`);
  return h||box("#e6e4de","#111","No work","Nothing in the costed list is worth funding here.");}

// ---------- agents tab ----------
function agents(){const T=D.totals,prop=B.reduce((a,b)=>a+b.ag.plan.package.length,0),ok=B.reduce((a,b)=>a+b.ag.ruling.approved_package.length,0),dc={};B.forEach(b=>dc[b.dec]=(dc[b.dec]||0)+1);
  const ex=ranked().filter(b=>b.ag.ruling.objections.length).slice(0,3);
  return `<div class="k">Three agents per building, built to disagree</div><h1>The model proposes. The agents decide what is safe to fund.</h1>
  <div class="flow"><div><b>1 Sceptic</b>Audits the records. Can this building's data be trusted?</div><span>→</span><div><b>2 Strategist</b>Picks a package from the costed measures.</div><span>→</span><div><b>3 Challenger</b>Attacks the plan, then splits it: start now or survey first.</div></div>
  <div class="big2" style="margin-top:14px"><div><b>${prop} → ${ok}</b><span>measures proposed → cleared to start without a visit</span></div><div><b>${T.full_fabric_if_all_confirmed.simple_payback_years} → ${T.approved_now.simple_payback_years} yrs</b><span>payback: fund everything → fund what the agents cleared</span></div></div>
  <h3>Rulings across ${B.length} buildings</h3>${bars({"Start now":dc.fund_now||0,"Survey first":dc.survey_first||0,"Fix data first":dc.fix_data_first||0},{"Start now":"#111","Survey first":"#969696","Fix data first":"#FF3131"})}
  <h3>Why this is worth paying for</h3><p class="t"><b>It turns a ${gbp(T.full_fabric_if_all_confirmed.capex_gbp)} wish-list into a ${gbp(T.approved_now.capex_gbp)} first tranche</b> that can start tomorrow, and a ${gbp(T.after_survey.capex_gbp)} second tranche where every site visit has one named question to answer. A surveyor is sent to ${T.survey_visits_needed} buildings knowing what to look for, instead of to all of them to look at everything.</p>
  <h3>Guardrails</h3><p class="t">The agents never do the maths. They answer through fixed forms, may only choose from measures the code has costed, and every total on this page is re-added by code. The Challenger's ruling is derived from its own measure-by-measure split, so it cannot contradict itself.</p>
  <h3>Three debates</h3>${ex.map(b=>`<div class="rank" style="grid-template-columns:1fr auto" onclick="pick('${b.id}')"><span><b style="color:#111">${esc(b.name)}</b><br><small>${esc(b.ag.ruling.objections[0])}</small></span><span class="tag ${b.dec==="fund_now"?"now":""}">${DN[b.dec]}</span></div>`).join("")}`;}

// ---------- accuracy tab ----------
function accuracy(){const M=D.meta,vc={};B.forEach(b=>vc[b.ag.sceptic.verdict]=(vc[b.ag.sceptic.verdict]||0)+1);
  const dis=B.filter(b=>b.flags.some(f=>f.includes("disagree"))).length,asm=B.filter(b=>b.storeys_assumed).length,sens=B.filter(b=>b.sensitivity),mx=Math.max(1,...sens.map(b=>b.sensitivity.max_kw));
  const row=(n,t)=>`<tr><td>${t}</td><td><b>${n}</b></td></tr>`;
  return `<div class="k">Getting from 80% to 90%+</div><h1>Most of the error is in the inputs. So the inputs get audited first.</h1>
  <p class="t">A heat-loss model can only be as right as the floor area, wall type and storey count it is fed. On this one street:</p>
  <table>${row(M.uprn_missing,"certificates with no address ID (a join on ID alone silently drops them)")}${row(M.unplaced,"homes whose address point falls in no building outline")}${row(dis,"buildings whose own flats disagree about what the walls are made of")}${row(asm+" of "+B.length,"buildings with no storey count in open data")}${row(sens.length,"houses certified more than once, with different answers")}${row((vc.do_not_use||0),"buildings whose records the Sceptic refuses to use")}</table>
  <h3>Same house, different certificate, different heat pump</h3>
  <svg viewBox="0 0 396 ${sens.length*20+22}" width="100%">${sens.map((b,i)=>{const s=b.sensitivity,y=i*20+12,x=v=>120+v/mx*250;return `<text x="0" y="${y+4}" font-size="11">${esc(b.name.replace(/,? ?Arlington R(oa)?d/i,""))}</text><line x1="${x(s.min_kw)}" y1="${y}" x2="${x(s.max_kw)}" y2="${y}" stroke="#111" stroke-width="5"/>${s.certs.map(c=>`<circle cx="${x(c.kw)}" cy="${y}" r="4" fill="#fff" stroke="#111" stroke-width="1.5"><title>${c.date}: ${c.area} m², ${c.kw} kW</title></circle>`).join("")}<text x="${x(s.max_kw)+8}" y="${y+4}" font-size="10.5" fill="#666">${s.min_kw}–${s.max_kw} kW</text>`;}).join("")}<text x="120" y="${sens.length*20+18}" font-size="10" fill="#888">peak heat loss, one dot per certificate</text></svg>
  <h3>What the audit does about it</h3><p class="t">Rules flag every contradiction with its evidence. The Sceptic then decides which value to trust and names the one check that would settle it. Each building carries a confidence score, and that score discounts its ranking, so doubtful data cannot push a building to the top of a funding list.</p>
  <h3>What this page does not claim</h3><p class="t">No accuracy percentage is claimed, because that needs ground truth: surveyed homes or metered bills. With Greenflip's validation set, the next step is to measure how much each check moves the error, and keep only the checks that earn their place.</p>`;}

function method(){return `<button class="go" style="background:#111;color:#fff;border:0;font:inherit;padding:9px 14px;cursor:pointer;margin-bottom:14px" onclick="showHow()">Open the full diagram →</button><div class="k">How it is built</div><h1>Address in, investment case out. Twelve small steps, all on GitHub.</h1>
  <ol style="margin-left:18px;line-height:1.6">${["Every energy certificate on the street (EPC open data), all "+D.meta.certificates,"Address points (OS Open UPRN) place each home in a building outline (OpenStreetMap)","A twin per building: storeys, exposed walls, party walls, roof, orientation","U-values read from each certificate's own wording","Heat loss = U × area × temperature difference, element by element, plus air leakage","Heat pump sized per home, today and after fabric work","Each measure costed: capital, bill saving, payback, carbon","Overheating index: sun-facing glazing, roof, flat type, heat island","Rule checks: contradictions between certificates, and between certificates and geometry","Three agents debate each building and rule","Code re-adds every total; the agent writes the memo from them","This page"].map(s=>`<li>${s}</li>`).join("")}</ol>
  <h3>Assumptions</h3><table>${Object.entries(D.assume).filter(([k])=>k!=="unit costs (GBP)").map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>
  <h3>Unit costs (£, indicative, editable)</h3><table>${Object.entries(D.assume["unit costs (GBP)"]).map(([k,v])=>`<tr><td>${esc(k.replace(/_/g," "))}</td><td>${v}</td></tr>`).join("")}</table>
  <div class="note">Not a SAP or PAS 2035 assessment. Listed-building and conservation-area status is not checked here; the agents treat it as a risk to verify.</div>`;}

const TABS=[["street","Street"],["agents","Agents"],["accuracy","Accuracy"],["method","Method"]];
function render(){document.getElementById("tabs").innerHTML=TABS.map(([k,n])=>`<button class="${!sel&&tab===k?"on":""}" onclick="go('${k}')">${n}</button>`).join("");
  document.getElementById("modes").innerHTML=MODES.map(([k,n])=>`<button class="${mode===k?"on":""}" onclick="setMode('${k}')">${n}</button>`).join("");
  const p=document.getElementById("pane"); p.innerHTML=sel?card(byId[sel]):tab==="street"?street():tab==="agents"?agents():tab==="accuracy"?accuracy():method(); p.scrollTop=0; redraw();}
function go(t){tab=t;if(sel){sel=null;home(900);}render();} function back(){sel=null;home(900);render();}
function setMode(m){mode=m;render();}
function pick(id){sel=id;const b=byId[id];map.flyTo({center:b.centroid,zoom:b.footprint>400?18.2:19.3,pitch:60,duration:1100});render();}
document.querySelectorAll("#client button").forEach(x=>x.onclick=()=>{document.querySelectorAll("#client button").forEach(y=>y.classList.remove("on"));x.classList.add("on");client=x.dataset.c;rerank();render();});
function hero(){const T=D.totals,mx=T.full_fabric_if_all_confirmed.capex_gbp;
 const r=(l,sub,t,c)=>`<div class="l">${l}<small>${sub}</small></div><div class="b"><i style="width:${Math.max(1.2,100*t.capex_gbp/mx)}%;background:${c}"></i></div><div class="v">${gbp(t.capex_gbp)}<small>${t.simple_payback_years}-yr payback · ${t.co2_saved_t_per_year} tCO₂/yr</small></div>`;
 document.getElementById("lad").innerHTML=r("Fund everything","what a model alone recommends",T.full_fabric_if_all_confirmed,"#bdbab2")+r("After targeted surveys",T.survey_visits_needed+" visits, one question each",T.after_survey,"#777")+r("Start now","cleared by the agents",T.approved_now,"#FF3131");
 document.getElementById("strip").innerHTML=`<div><b>${gbp(T.approved_now.capex_gbp)}</b>cleared to start now</div><div><b>${T.survey_visits_needed}</b>targeted surveys</div><div><b>${T.decisions.fix_data_first}</b>blocked: bad data</div><div><b>${T.approved_now.simple_payback_years} yrs</b>payback vs ${T.full_fabric_if_all_confirmed.simple_payback_years} unchecked</div><div style="border:0;color:#bbb">How the agents decided →</div>`;}
hero();
render();
</script></body></html>"""
out = pathlib.Path("outputs/arlington_demo.html"); out.parent.mkdir(exist_ok=True)
out.write_text(HTML.replace("__DATA__", json.dumps(DATA, default=str, separators=(",", ":"))))
print(f"Wrote {out} ({out.stat().st_size/1e6:.1f} MB): {len(B)} buildings, {len(panels)} wall panels")
