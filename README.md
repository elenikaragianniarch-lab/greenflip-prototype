# greenflip-prototype

**Can a house's public energy record be trusted before you model it?**

A one-street prototype: build simple digital twins (LOD1) of the houses on Arlington Road, Camden, link each one to its Energy Performance Certificates (EPCs), and let a "sceptic" agent flag where the records contradict each other or the building itself.

The idea: part of the gap between 80% and 90%+ accuracy in retrofit modelling is not the model, it's the inputs. Check the data before you trust it.

## First finding (Step 1, EPC data only)

| Check (Arlington Road, NW1 7, houses) | Houses |
| --- | --- |
| Houses on the street | 51 |
| Certified more than once | 15 |
| Same house, floor area differs by more than 10% | 8 |
| Same house, different construction age on different certificates | 5 |
| Newest certificate older than 10 years (expired) | 15 |

11 of the 15 houses certified more than once contradict themselves. One house is 202 m² on its 2009 certificate and 141 m² on its 2024 one.

## Second finding (Step 3, adding geometry)

- The free OS map (Zoomstack) draws each terrace as one block: up to 15 houses share one outline. OpenStreetMap draws 40 of the 51 houses individually (median footprint about 49 m²).
- Where storeys are known (3 above ground), the EPC floor area is 8–45% larger than footprint × storeys for 10 of 12 houses. The likely reason is basements (lower ground floors), rear extensions or loft rooms, which neither map records. The twin needs that knowledge, and so does any heat-loss model built on it.
- The newest certificate for one house (Feb 2026) has no UPRN. A join on UPRN alone would silently use its 2015 certificate instead.
- One record is labelled a house but has a flat's address, 40 m², inside a 7-storey building.

## Third step: the heat-loss twin (Steps 8–9)

Each house is rebuilt from its parts: exposed walls, party walls and roof, coloured by how much heat they lose on a cold day.

- **Method:** heat loss = U-value × area × temperature difference. The U-values come from each home's own EPC wording ("Solid brick, as built, no insulation", "Pitched, 100 mm loft insulation"); the areas come from the 3D twin. Air leakage is added from the volume and the building's age. It's indicative, not a SAP assessment, and every assumption is in the output.
- **Street result (40 houses):** 490 kW lost on a design day (21 °C inside, −2 °C outside). Walls 41%, windows 18%, roof 17%, air leakage 17%, floor 8%.
- **Heat pumps:** a typical house needs about 11 kW today, and about 4 kW after a fabric package.
- **Priority:** houses are ranked by **risk-adjusted saving**, meaning kWh saved per year × the agent's confidence in the data. Houses the agent says not to use are held back until their records are fixed.
- **Map:** `outputs/street_twin.html`, with three views: Heat loss / Where to start / Data trust. Click a house for its heat-loss breakdown, heat pump size, ranked measures and solar potential.

## Pipeline

1. **Select the street** and compare each house's certificates with each other (`src/01_select_street.py`)
2. **Get geometry**: address points (OS Open UPRN) and building outlines (OS Zoomstack, OpenStreetMap) (`src/02_get_geometry.py`, `src/03_join_geometry.py`)
3. **Join on UPRN**: one row per house, with its geometry and its EPC record
4. **Build the twins (LOD1)**: extrude footprints; measure floor, wall and roof area, and orientation
5. **Checks**: EPC floor area vs footprint × storeys, certificate age, wall type vs building age
6. **Sceptic agent**: an LLM reads the flags and writes a note plus a confidence score (JSON). The LLM never does the maths.
7. **Map and 3D view**: houses coloured by confidence (`src/07_make_map.py`)
8. **Heat loss by element**: walls, roof, floor, windows, air; heat pump size; ranked measures; solar (`src/08_heat_loss.py`)
9. **Digital twin map**: walls and roofs coloured by heat loss; priority and trust views (`src/09_make_twin_map.py`)

## Data

Data is **not** in this repo. EPC data comes from [Get energy performance of buildings data](https://get-energy-performance-data.communities.gov.uk) (MHCLG). Its licence restricts republishing address data, so `data/` is git-ignored.

To reproduce:
1. Download domestic EPCs for Camden from the service above.
2. Save the file as `data/raw/epc_camden_domestic.csv`.
3. Run `python3 src/01_select_street.py`.

## Author

Eleni Karagianni, architect-engineer and computational designer. [eleni-karagianni.com](https://www.eleni-karagianni.com)
