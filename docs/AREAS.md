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
| Named places: temples, mosques, hospitals, schools, markets, stations, parks, banks | `<area>_places.json` | `import_osm.py --places`, from OpenStreetMap |
| Landmarks and the local names people use | `LANDMARKS` in `<area>.py` | By hand. These win over an OpenStreetMap place at the same spot. |
| More local names and landmarks | Redis, per area | Coordinators, in the dashboard (**Places**) |
| Wards (simple zones) | `LAT_EDGES`, `LON_EDGES`, `WARD_NAMES` | By hand |
| Shelters, team bases of the demo organisations | `SHELTERS`, `TEAM_BASES` | By hand |
| The drill story | `DRILL` | By hand |

The importer keeps every street that connects to others, because the side lanes are the detours when a main road floods. It also:

- keeps only the largest connected road network;
- joins pieces of one road where nothing else meets them, and removes unnamed dead ends shorter than 150 m (`--stub`);
- gives each bridge or flyover one name, even when OpenStreetMap splits it;
- names unnamed roads and bridges after the nearest landmark, for example "Bridge near Kali Mandir";
- adds the ward name when two separate streets share a name, for example "Road No.1, Lohanipur";
- marks roads near a drain or canal as low-lying.

Road status is set per road name. A report "Malahi Pakdi Road flooded" closes every piece of that road.

The places import (`--places`) does not touch the roads. A new places file changes only the landmarks. The next start replaces the landmarks and keeps the roads, their flood state and every organisation's graph.

ReliefNet drops a place that is outside every ward, has the name of a ward, or is the same place as a hand-written landmark. When two places have the same name, ReliefNet adds the ward name, for example "State Bank of India, Kankarbagh".

## Add a new area

Use a place that you know, or a famous flood from the news. Local knowledge makes the landmark names real.

1. Copy `backend/reliefnet/areas/patna.py` to a new file, for example `chennai.py`.
2. Change `NAME`, `TITLE` and `SNAPSHOT`.
3. Set `BBOX` (south, west, north, east). Keep it to about 3–5 km on each side.
4. Add the module to `AREAS` in `backend/reliefnet/areas/__init__.py`.
5. Write a short `LANDMARKS` list: 10 to 20 places that people name most, with the local names they type, for example `"nmch"`, `"sarkari aspatal"`. Point `TEAM_BASES` at them for any demo organisations. A real organisation adds its own teams in the dashboard.
6. Download the roads:

   ```sh
   cd backend
   python -m reliefnet.areas.import_osm chennai --cache chennai_osm.json
   ```

   The `--cache` file keeps the download, so you can run the importer again without a new download. Do not commit it.

7. Download the named places:

   ```sh
   python -m reliefnet.areas.import_osm chennai --places --cache chennai_places_osm.json
   ```

   This writes `chennai_places.json`. Commit it. Do not commit the cache file.

8. Read the list of places that the importer prints. If people use a local name for a place, add the place to `LANDMARKS` with that name. Coordinators can also add local names later in the dashboard (**Places**).
9. If you changed `LANDMARKS`, run the road importer again, so that it names unnamed roads after them.

   Caution: a new road import can change the junction IDs. Then the next start rebuilds every organisation's graph.
10. Set the ward edges and names, then the shelters, the team bases and `DRILL`.
11. Choose `DRILL.flood_road` from the importer's road list. A good choice is a main road whose loss forces a detour.
12. Set `route_check()` to two points at the two ends of that road.
13. Run the tests: `pytest tests/test_areas.py`. They check that the network is connected, that every landmark and team base is inside a ward, and that the drill road exists.

   Caution: when `AREA` changes, the next start rebuilds the region graph and every organisation's graph. Their teams, families and routes point at the old area's junctions, so ReliefNet cannot keep them.

14. Set `AREA=chennai` in `.env` and start ReliefNet.

## Data licence

OpenStreetMap data is © OpenStreetMap contributors, under the Open Database License (ODbL). The dashboard shows this credit in the **Shift status** card on the map. Keep the credit if you publish ReliefNet with OpenStreetMap data.

The named places in `<area>_places.json` also come from OpenStreetMap under the ODbL. The Places dialog shows the credit for them.
