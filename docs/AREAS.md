# Operation areas

An area is the place that the shared `region` graph describes: its roads, bridges, landmarks, wards and shelters. One deployment works on one area at a time. The `AREA` setting selects it.

| `AREA` | Place | Roads from |
|---|---|---|
| `patna` (default) | Rajendra Nagar and Kankarbagh, Patna. Heavy rain flooded these areas in September 2019. | OpenStreetMap |
| `ganga_nagar` | A fictional grid town with a river and three bridges | Generated |

## How an area works

Each area is one Python module in `backend/reliefnet/areas/`:

| Part | Where | Made by |
|---|---|---|
| Roads, bridges, underpasses, drains, railway | `<area>.json` | `import_osm.py`, from OpenStreetMap |
| Landmarks and the local names people use | `LANDMARKS` in `<area>.py` | By hand |
| Wards (simple zones) | `LAT_EDGES`, `LON_EDGES`, `WARD_NAMES` | By hand |
| Shelters, team bases | `SHELTERS`, `TEAM_BASES`, `DEFAULT_TEAMS` | By hand |
| The drill story | `DRILL` | By hand |

The importer keeps every street that connects to others, because the side lanes are the detours when a main road floods. It also:

- keeps only the largest connected road network;
- joins pieces of one road where nothing else meets them, and removes unnamed dead ends shorter than 150 m (`--stub`);
- gives each bridge or flyover one name, even when OpenStreetMap splits it;
- names unnamed roads and bridges after the nearest landmark, for example "Bridge near Kali Mandir";
- adds the ward name when two separate streets share a name, for example "Road No.1, Lohanipur";
- marks roads near a drain or canal as low-lying.

Road status is set per road name. A report "Malahi Pakdi Road flooded" closes every piece of that road.

## Add a new area

Use a place that you know, or a famous flood from the news. Local knowledge makes the landmark names real.

1. Copy `backend/reliefnet/areas/patna.py` to a new file, for example `chennai.py`.
2. Change `NAME`, `TITLE` and `SNAPSHOT`.
3. Set `BBOX` (south, west, north, east). Keep it to about 3–5 km on each side.
4. Add the module to `AREAS` in `backend/reliefnet/areas/__init__.py`.
5. Replace `LANDMARKS` with a first short list of places inside the box, and point `TEAM_BASES` and `DEFAULT_TEAMS` at them. A few places are enough for now.
6. Download the roads:

   ```sh
   cd backend
   python -m reliefnet.areas.import_osm chennai --cache chennai_osm.json
   ```

   The `--cache` file keeps the download, so you can run the importer again without a new download. Do not commit it.

7. Complete the list to 25–40 landmarks: temples, mosques, churches, hospitals, schools, parks, markets and stations. Use their OpenStreetMap positions, for example from https://www.openstreetmap.org.
8. For each landmark, write the names people type in a message, for example `"nmch"`, `"sarkari aspatal"`, `"mandir"`.
9. Run the importer again, so that it names unnamed roads after the full landmark list.
10. Set the ward edges and names, then the shelters, the team bases and `DRILL`.
11. Choose `DRILL.flood_road` from the importer's road list. A good choice is a main road whose loss forces a detour.
12. Set `route_check()` to two points at the two ends of that road.
13. Run the tests: `pytest tests/test_areas.py`. They check that the network is connected, that every landmark and team base is inside a ward, and that the drill road exists.

   Caution: when `AREA` changes, the next start rebuilds the region graph and every organisation's graph. Their teams, families and routes point at the old area's junctions, so ReliefNet cannot keep them.

14. Set `AREA=chennai` in `.env` and start ReliefNet.

## Data licence

OpenStreetMap data is © OpenStreetMap contributors, under the Open Database License (ODbL). The dashboard shows this credit in the chart's cartouche. Keep the credit if you publish ReliefNet with OpenStreetMap data.
