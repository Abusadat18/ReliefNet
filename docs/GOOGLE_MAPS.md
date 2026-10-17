# Google Maps

The operations dashboard can show a Google map under its layers. Without a key, it draws its own chart. The chart needs no internet, so it is also the offline mode.

## What Google does and does not do here

| Part | Source |
|---|---|
| The map picture, zoom, pan, tilt, rotation and satellite view | Google Maps JavaScript API (vector map) |
| The map style (colours, labels, places) | A Map Style in Google Cloud, linked to your Map ID |
| The road graph that Dispatch routes on | OpenStreetMap, stored in FalkorDB (see [AREAS.md](AREAS.md)) |
| Households, teams, routes, flooded roads, shelters | ReliefNet, drawn with deck.gl in the same frame as the map |

Google's terms do not allow you to copy Google's road data into your own database. Google's routing also cannot avoid a road that you choose, for example a flooded bridge. That is why the road graph comes from OpenStreetMap and FalkorDB.

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

## Create a vector Map ID

The dashboard uses a Google vector map. A vector map needs a Map ID. Without a Map ID, the dashboard uses Google's test id `DEMO_MAP_ID`. The test id is good for development, but not for production.

1. Open the Google Cloud console and select the project that has your key.
2. Open **Google Maps Platform > Map Management**.
3. Click **Create Map ID**.
4. Type a name, for example `reliefnet-ops`.
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

## Style the map in Google Cloud

With a Map ID, Google ignores styles that the app sets in code. You set the style in Google Cloud as a Map Style. Link the Map Style to your Map ID.

For a calm map under the ReliefNet layers, use fewer places (points of interest) and muted colours.

1. Open **Google Maps Platform > Map Styles**.
2. Click **Create style**.
3. Select a light base style, for example **Light** or **Muted**.
4. Set the density of points of interest to a low value.
5. Make the colours of roads, parks and water less strong.
6. Make a dark variant of the same style.
7. Click **Save** and type a name, for example `reliefnet-calm`.
8. Open the style and click **Link to Map IDs**.
9. Select your Map ID and click **Save**.
10. Reload the dashboard.

Google can take some minutes to apply a changed style.

The dashboard sends a colour scheme (light or dark) to the map. **Night chart** in the top bar selects the dark variant. **Day chart** selects the light variant. If the Map Style has no dark variant, the map stays light at night.

## How the layers follow the map

The dashboard draws its layers with deck.gl on the same WebGL canvas as the Google map. Each frame shows the map and the layers together. Thus the layers stay in their correct positions when you zoom, tilt or rotate the map. They do not move behind the map.

deck.gl needs WebGL in the browser. Without a Google key, the dashboard uses the built-in chart, which does not need WebGL.

## Use the map

- Drag to pan. Scroll or use **+** and **−** to zoom. Click **⤢** to show the whole area again.
- Click **Satellite** to see the real ground. Click **Map** to go back.
- Click a household to open it. Click any road to mark it flooded or open.
- The map shows only the roads that carry news: bridges and flyovers, low roads near drains (dotted), reported roads (dashed) and flooded roads (with a cross). The other streets come from Google's map.
- **Night chart** in the top bar also selects the dark variant of the Map Style.

## Problems

| What you see | Cause and fix |
|---|---|
| "Google Maps refused the key, so the built-in chart is showing." | The key is wrong, the Maps JavaScript API is not enabled, or the site address is not in the key's website list. Check steps 3 and 8, then reload. |
| "The Google Maps script did not load." | The browser cannot reach Google. Check the internet connection. The built-in chart still works. |
| The built-in chart shows and there is no message. | The API has no key. Check `GOOGLE_MAPS_API_KEY` in `.env`, then restart the API. |
| The map is grey with "For development purposes only". | Billing is not enabled on the Google Cloud project. |
| The map has the plain Google style. | No Map Style is linked to the Map ID, or the dashboard uses `DEMO_MAP_ID`. Set `GOOGLE_MAPS_MAP_ID` and link a Map Style to it. Then restart the API and reload. |
| The map stays light with **Night chart**. | The Map Style has no dark variant. Add a dark variant to the Map Style. |
| The map shows, but the layers do not show, or the browser console shows a WebGL error. | The browser or the GPU has WebGL disabled. Enable hardware acceleration in the browser settings. To use the built-in chart, remove `GOOGLE_MAPS_API_KEY` from `.env` and restart the API. |
