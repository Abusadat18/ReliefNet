# Google Maps

The operations dashboard can show a Google map under its layers. Without a key, it draws its own chart. The chart needs no internet, so it is also the offline mode.

## What Google does and does not do here

| Part | Source |
|---|---|
| The map picture, zoom, pan, tilt, rotation and satellite view | Google Maps JavaScript API (vector map) |
| The map style (colours, places, and Google's labels off) | A Map Style in Google Cloud, linked to each Map ID |
| The road graph that Dispatch routes on | OpenStreetMap, stored in FalkorDB (see [AREAS.md](AREAS.md)) |
| The names on the map: neighbourhoods, roads, landmarks and shelters | ReliefNet, from OpenStreetMap and the gazetteer, drawn with deck.gl |
| Households, teams, routes, flooded roads, shelters | ReliefNet, drawn with deck.gl on top of the map, in step with each map frame |

Google's terms do not allow you to copy Google's road data into your own database. Google's routing also cannot avoid a road that you choose, for example a flooded bridge. That is why the road graph comes from OpenStreetMap and FalkorDB.

The clean map shows no Google labels. The dashboard draws its own names from the same data that Intake uses. Thus a name that you see on the map is a name that Intake can match in a message.

## Set up the key

You need a Google Cloud account with billing enabled. Google gives a free monthly quota for the Maps JavaScript API. A demo or a hackathon stays far inside it. Check the current quota on the Google Maps Platform pricing page.

1. Open the Google Cloud console and select or create a project.
2. Open **APIs & Services > Library**.
3. Find **Maps JavaScript API** and click **Enable**.
4. Open **APIs & Services > Credentials**.
5. Click **Create credentials > API key**.
6. Open the new key to edit it.
7. Under **Application restrictions**, select **Websites**.
8. Add each address that serves the dashboard, for example:
   - `http://localhost:8080/*`
   - `http://localhost:5173/*`
   - `https://your-demo-domain/*`
9. Under **API restrictions**, select **Restrict key**, then select only **Maps JavaScript API**.
10. Click **Save**.
11. Put the key in `.env` in the repository root:

    ```sh
    GOOGLE_MAPS_API_KEY=your-key
    ```

12. Restart the API: `docker compose up -d api`, or restart `uvicorn` in local development.
13. Reload the dashboard.

Caution: the browser always receives a Maps JavaScript key. It is not a secret. The restrictions in steps 7 to 9 stop other sites from using your quota. Do not skip them.

The API sends the key to the web app at run time (`/api/config`). You do not need to rebuild the web image after you change the key.

## Create the clean Map ID

The dashboard uses a Google vector map. A vector map needs a Map ID. Without a Map ID, the dashboard uses Google's test id `DEMO_MAP_ID`. The test id is good for development, but not for production.

The first Map ID is the clean map. The dashboard shows it by default. Link it to the clean Map Style (see [Make the clean style](#make-the-clean-style)).

1. Open the Google Cloud console and select the project that has your key.
2. Open **Google Maps Platform > Map Management**.
3. Click **Create Map ID**.
4. Type a name, for example `reliefnet-clean`.
5. Under **Map type**, select **JavaScript**.
6. Under **Rendering type**, select **Vector**.
7. Click **Save**.
8. Copy the Map ID.
9. Put the Map ID in `.env` in the repository root:

    ```sh
    GOOGLE_MAPS_MAP_ID=your-map-id
    ```

10. Restart the API: `docker compose up -d api`, or restart `uvicorn` in local development.
11. Reload the dashboard.

The API also sends the Map ID through `/api/config`. You do not need to rebuild the web image.

## Make the clean style

With a Map ID, Google ignores styles that the app sets in code. You set the style in Google Cloud as a Map Style. Then you link the Map Style to the Map ID.

The clean style turns off all of Google's labels: road names, place names, area names and the icons of places. It keeps the roads, water, parks and buildings. The dashboard then draws its own names on top (see [Names on the map](#names-on-the-map)).

The file [`google-map-style-no-labels.json`](google-map-style-no-labels.json) holds this style.

Make the light style:

1. Open **Google Maps Platform > Map Styles**.
2. Click **Create style**.
3. Select **Import JSON**.
4. Paste the contents of `docs/google-map-style-no-labels.json`.
5. Click **Save**.
6. In the **Save and publish map style** dialog, type a name, for example `reliefnet-clean`.
7. Click **Save**.
8. Zoom in on Patna. Make sure that the map shows no names and no place icons.

If you already have a `reliefnet-clean` style, you can change it. Open the style. If the style editor shows **Import JSON**, use it.

If the console has no **Import JSON** option, turn off the labels by hand:

1. Open the style in the style editor.
2. In **Map features**, select a top-level feature, for example **Points of interest**.
3. Under **Labels**, set **Visibility** to off.
4. Do steps 2 and 3 again for each top-level feature: **Political**, **Points of interest**, **Road network**, **Natural** and **Infrastructure**.
5. Under **Points of interest**, also set the **Icon** visibility to off, if the editor shows it.
6. Click **Save**.

Make the dark variant, so that the night chart works:

1. Open the `reliefnet-clean` style.
2. Click **Make a copy**.
3. Under **Style mode options**, select the checkbox for the dark version.
4. Click **Save**.
5. Open the dark copy and make sure that it also shows no labels.

Link the styles to the clean Map ID:

1. Open **Google Maps Platform > Map Management**.
2. Select the Map ID that is in `GOOGLE_MAPS_MAP_ID`.
3. In the **Map styles** section, click **Edit** for the light mode.
4. Select `reliefnet-clean` and click **Done**.
5. Click **Edit** for the dark mode.
6. Select the dark copy and click **Done**.
7. Click **Save**.
8. Reload the dashboard.

Google can take some minutes to apply a changed style.

The app cannot turn off Google's labels on a map with a real Map ID. Only the Map Style can do it. Without a Map ID, the dashboard uses Google's test id `DEMO_MAP_ID`. In that case, the dashboard draws a raster map and turns off Google's labels in code. A raster map cannot tilt.

The dashboard sends a colour scheme (light or dark) to the map. The moon button in the top bar (**Night chart**) selects the dark variant. The sun button (**Day chart**) selects the light variant. If the Map ID has no dark style, the map stays light at night.

> **Note:** The night chart is off for now. The dashboard always uses the day theme, and the moon button does not show. To turn it on again, set `NIGHT_MODE` to `true` in `frontend/src/components/ThemeToggle.tsx`.

## Add a detailed map (optional)

The clean map shows only the names that ReliefNet knows. Sometimes a coordinator needs Google's names, for example to find a named shop in a report. A second Map ID gives a detailed map with Google's labels and all of Google's places.

1. Open **Google Maps Platform > Map Management**.
2. Click **Create Map ID**.
3. Type a name, for example `reliefnet-detailed`.
4. Under **Map type**, select **JavaScript**.
5. Under **Rendering type**, select **Vector**.
6. Click **Save**.
7. Keep Google's default style, or link a Map Style that shows labels and all places.
8. Copy the Map ID.
9. Put the Map ID in `.env` in the repository root:

    ```sh
    GOOGLE_MAPS_MAP_ID_DETAILED=your-second-map-id
    ```

10. Restart the API: `docker compose up -d api`, or restart `uvicorn` in local development.
11. Reload the dashboard.

The dashboard then shows a **Clean / All** switch on the map. **Clean** uses `GOOGLE_MAPS_MAP_ID` and shows only ReliefNet's names. **All** uses `GOOGLE_MAPS_MAP_ID_DETAILED` and also shows Google's labels. Each browser remembers its choice.

On **All**, a name can show two times: once from Google and once from ReliefNet. Only the ReliefNet name is sure to match in Intake.

If `GOOGLE_MAPS_MAP_ID_DETAILED` is empty, the dashboard does not show the switch.

## How the layers follow the map

The dashboard draws its layers with deck.gl on a canvas above the Google map. For each map frame, Google gives deck.gl the camera position, and deck.gl draws the layers again. Thus the layers stay in their correct positions when you zoom, tilt or rotate the map. The layers are always above the map labels.

deck.gl needs WebGL in the browser. Without a Google key, the dashboard uses the built-in chart, which does not need WebGL.

## Names on the map

The dashboard draws these names. The built-in chart draws the same names.

| Name | Source | When it shows |
|---|---|---|
| Neighbourhood | The area's neighbourhoods from the API (`neighbourhoods` in `/api/ops/region`) | From the area view to a mid zoom. Close in, the landmark names replace it. |
| Road | The OpenStreetMap road graph | Bridges and long roads first. Short streets show when you zoom in. The text turns with the road. |
| Flooded road | The road graph, with the flood status | Always, in red, next to the cross |
| Landmark | The gazetteer: the area list, names that coordinators add, then OpenStreetMap | Area landmarks first, then coordinator names, then OpenStreetMap places |
| Shelter | The area's shelters | From a mid zoom |

The road importer gives a street with no name a name such as "Lane near Gandhi Maidan 108". The map shows such a name only when you zoom far in.

The names do not overlap. When two names need the same space, the more important name shows. The order is: flooded roads, neighbourhoods, shelters, area landmarks, coordinator landmarks, roads, OpenStreetMap places, then streets with no real name.

## Hide map layers

Click **Layers** on the map to open the Layers menu. Each item shows or hides one ReliefNet layer. All layers are on by default.

- **Names**: the names of neighbourhoods, roads and landmarks. The red names of flooded roads always show.
- **Ward zones**: the 16 simple zones that messages refer to, for example "ward 11". They are not the official ward map.
- **Team routes**: the route that Dispatch gives to each team.
- **Served households**: the households that already got help.
- **Low roads near drains**: the thin blue roads that flood first.
- **Landmarks and shelters**: the named places from the gazetteer, and the relief camps. With this item off, the map also hides the names of landmarks and shelters.

Each browser remembers its choice. Other people do not see your change. The Layers menu works on the Google map and on the built-in chart.

## Use the map

- Drag to pan. Scroll or use **+** and **−** to zoom. Click the square button below them to show the whole area again.
- Click **Sat** to see the real ground. Click **Map** to go back. The satellite view has no Google labels. The ReliefNet names stay on it.
- The map dims the world outside the operation area and draws a line around the area.
- Click a household to open it. A bubble with a number holds households that sit close together on the screen. Click it to zoom in. A pill with a number is a household with priority 70 or more.
- Click any road to mark it flooded or open.
- The map shows only the roads that carry news: bridges and flyovers, low roads near drains (thin blue), reported roads (dashed) and flooded roads (with a cross). The other streets come from Google's map. Their names come from ReliefNet.
- The moon button in the top bar also selects the dark variant of the Map Style.

## Problems

| What you see | Cause and fix |
|---|---|
| "Google Maps refused the key, so the built-in chart is showing." | The key is wrong, the Maps JavaScript API is not enabled, or the site address is not in the key's website list. Check steps 3 and 8, then reload. |
| "The Google Maps script did not load." | The browser cannot reach Google. Check the internet connection. The built-in chart still works. |
| The built-in chart shows and there is no message. | The API has no key. Check `GOOGLE_MAPS_API_KEY` in `.env`, then restart the API. |
| The map is grey with "For development purposes only". | Billing is not enabled on the Google Cloud project. |
| The map has the plain Google style. | No Map Style is linked to the Map ID. Link the clean Map Style to the Map ID in `GOOGLE_MAPS_MAP_ID`. Then reload. |
| Google's names show under the ReliefNet names. | The Map Style still shows labels, or Google has not applied the change yet. Import `docs/google-map-style-no-labels.json` into the Map Style again, or turn off the labels by hand. Then wait some minutes. |
| The map shows no neighbourhood names. | The API is older than the dashboard and sends no `neighbourhoods`. Update and restart the API. |
| The map has no **Clean / All** switch. | `GOOGLE_MAPS_MAP_ID_DETAILED` is empty. Set it to a second vector Map ID, then restart the API and reload. |
| **All** looks the same as **Clean**. | The two Map IDs have the same Map Style. Link a style with labels and all places to the detailed Map ID. |
| Google's labels show at night, but not in the day. | The dark copy of the Map Style still shows labels. Turn off the labels in the dark copy too. |
| The map stays light with the night chart. | The Map Style has no dark variant. Add a dark variant to the Map Style. |
| The map shows, but the layers do not show, or the browser console shows a WebGL error. | The browser or the GPU has WebGL disabled. Enable hardware acceleration in the browser settings. To use the built-in chart, remove `GOOGLE_MAPS_API_KEY` from `.env` and restart the API. |
