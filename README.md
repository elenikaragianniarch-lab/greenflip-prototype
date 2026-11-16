# greenflip-prototype

**Can a house's public energy record be trusted before you model it?**

A one-street prototype: build simple digital twins (LOD1) of the houses on Arlington Road, Camden, link each one to its Energy Performance Certificates (EPCs), and let a "sceptic" agent flag where the records contradict each other or the building itself.

The idea: part of the gap between 80% and 90%+ accuracy in retrofit modelling is not the model, it's the inputs. Check the data before you trust it.

## First finding (Step 1, EPC data only)

| Check (Arlington Road, NW1 7, houses) | Houses |
| --- | --- |
| Houses on the street | 51 |
| Certified more than once | 14 |
| Same house, floor area differs by more than 10% | 7 |
| Same house, different construction age on different certificates | 5 |
| Newest certificate older than 10 years (expired) | 16 |

10 of the 14 houses certified more than once contradict themselves. One house is 202 m² on its 2009 certificate and 141 m² on its 2024 one.

## Pipeline

1. **Select the street** and compare each house's certificates with each other (`src/01_select_street.py`)
2. **Get geometry**: building footprints and heights (OS open data)
3. **Join on UPRN**: one row per house, with its geometry and its EPC record
4. **Build the twins (LOD1)**: extrude footprints; measure floor, wall and roof area, and orientation
5. **Checks**: EPC floor area vs footprint × storeys, certificate age, wall type vs building age
6. **Sceptic agent**: an LLM reads the flags and writes a note plus a confidence score (JSON). The LLM never does the maths.
7. **Map and 3D view**: houses coloured by confidence

## Data

Data is **not** in this repo. EPC data comes from [Get energy performance of buildings data](https://get-energy-performance-data.communities.gov.uk) (MHCLG). Its licence restricts republishing address data, so `data/` is git-ignored.

To reproduce:
1. Download domestic EPCs for Camden from the service above.
2. Save the file as `data/raw/epc_camden_domestic.csv`.
3. Run `python3 src/01_select_street.py`.

## Author

Eleni Karagianni, architect-engineer and computational designer. [eleni-karagianni.com](https://www.eleni-karagianni.com)
