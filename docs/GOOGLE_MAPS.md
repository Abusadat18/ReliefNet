# Google Maps

The operations dashboard can show a Google map under its layers. Without a key, it draws its own chart. The chart needs no internet, so it is also the offline mode.

## What Google does and does not do here

| Part | Source |
|---|---|
| The map picture, zoom, pan, tilt, rotation and satellite view | Google Maps JavaScript API (vector map) |
| The map style (colours, labels, places) | A Map Style in Google Cloud, linked to each Map ID |
| The road graph that Dispatch routes on | OpenStreetMap, stored in FalkorDB (see [AREAS.md](AREAS.md)) |
| Households, teams, routes, flooded roads, shelters | ReliefNet, drawn with deck.gl on top of the map, in step with each map frame |

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

The clean style keeps the places that people use as landmarks in a flood. It hides the places that do not help relief work:

| Keep (landmarks) | Hide |
|---|---|
| Hospitals, pharmacies, police and fire stations | Shops and markets |
| Schools | Restaurants, cafes and bars |
| Places of worship | Hotels and hostels |
| Government offices | Cinemas, museums and other entertainment |
| Transit (stations, airports) | Banks, ATMs, petrol stations and other services |

In the style editor, these places are map features under **Points of interest**. The table below gives the names that Google used when we wrote this guide. Google can change the names in the console. If a name is different, find the nearest match.

| Map feature in the style editor | Contains | Clean style |
|---|---|---|
| **Emergency** | Fire, Hospital, Pharmacy, Police | On |
| **Other** | Bridge, Cemetery, Government, Library, Military, Place of worship, School, Town square | On |
| **Transit** | Airport | On |
| **Landmark** | Large landmarks | On |
| **Recreation** | Parks, sports fields and other open land | On |
| **Retail** | Grocery, Shopping | Off |
| **Food and drink** | Bar, Cafe, Restaurant, Winery | Off |
| **Lodging** | Hotels and hostels | Off |
| **Entertainment** | Arts, Casino, Cinema, Historic, Museum, Theme park, Tourist attraction | Off |
| **Service** | ATM, Bank, Car rental, EV charging, Gas station, Parking lot, Post office, Rest stop, Restroom | Off |

Google has no "Medical" or "Education" group. Hospitals are in **Emergency**. Schools are in **Other**.

Make the light style:

1. Open **Google Maps Platform > Map Styles**.
2. Click **Create style**.
3. On the **Google styles** tab, select **Light**.
4. Click **Customize**.
5. Zoom in on Patna until the map shows places.
6. In **Map features**, click the settings gear icon to open **Map Settings**.
7. Under the POI density options, select a low density.
8. In **Map features**, open **Points of interest > Retail**.
9. Under **Visibility**, click the eye icon. The icon turns blue.
10. Click the eye icon again until the feature is off.
11. Do steps 8 to 10 again for **Food and drink**, **Lodging**, **Entertainment** and **Service**.
12. Make sure that **Emergency**, **Other**, **Transit** and **Landmark** stay on.
13. Make the colours of roads, parks and water less strong.
14. Click **Save**.
15. In the **Save and publish map style** dialog, type a name, for example `reliefnet-clean`.
16. Click **Save**.

Note: Google calls POI density an experimental setting. You can set it only on a light style. Google applies it to the linked dark style too.

Make the dark variant, so that **Night chart** works:

1. Open the `reliefnet-clean` style.
2. Click **Make a copy**.
3. Under **Style mode options**, select the checkbox for the dark version.
4. Click **Save**.
5. Open the dark copy and make sure that the same map features are off.

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

The dashboard sends a colour scheme (light or dark) to the map. **Night chart** in the top bar selects the dark variant. **Day chart** selects the light variant. If the Map ID has no dark style, the map stays light at night.

## Add a detailed map (optional)

The clean map hides shops, hotels and restaurants. Sometimes a coordinator needs them, for example to find a named shop in a report. A second Map ID gives a detailed map with all of Google's places.

1. Open **Google Maps Platform > Map Management**.
2. Click **Create Map ID**.
3. Type a name, for example `reliefnet-detailed`.
4. Under **Map type**, select **JavaScript**.
5. Under **Rendering type**, select **Vector**.
6. Click **Save**.
7. Keep Google's default style, or link a Map Style that shows all places.
8. Copy the Map ID.
9. Put the Map ID in `.env` in the repository root:

    ```sh
    GOOGLE_MAPS_MAP_ID_DETAILED=your-second-map-id
    ```

10. Restart the API: `docker compose up -d api`, or restart `uvicorn` in local development.
11. Reload the dashboard.

The dashboard then shows a **Clean / Detailed** switch on the map. **Clean** uses `GOOGLE_MAPS_MAP_ID`. **Detailed** uses `GOOGLE_MAPS_MAP_ID_DETAILED`. Each browser remembers its choice.

If `GOOGLE_MAPS_MAP_ID_DETAILED` is empty, the dashboard does not show the switch.

## How the layers follow the map

The dashboard draws its layers with deck.gl on a canvas above the Google map. For each map frame, Google gives deck.gl the camera position, and deck.gl draws the layers again. Thus the layers stay in their correct positions when you zoom, tilt or rotate the map. The layers are always above the map labels.

deck.gl needs WebGL in the browser. Without a Google key, the dashboard uses the built-in chart, which does not need WebGL.

## Hide map layers

Click **Layers** on the map to open the Layers menu. Each item shows or hides one ReliefNet layer. All layers are on by default.

- **Ward zones**: the 16 simple zones that messages refer to, for example "ward 11". They are not the official ward map.
- **Team routes**: the route that Dispatch gives to each team.
- **Served households**: the households that already got help.
- **Low roads near drains**: the dotted roads that flood first.
- **Landmarks and shelters**: the named places from the gazetteer, and the relief camps.

Each browser remembers its choice. Other people do not see your change. The Layers menu works on the Google map and on the built-in chart.

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
| The map has no **Clean / Detailed** switch. | `GOOGLE_MAPS_MAP_ID_DETAILED` is empty. Set it to a second vector Map ID, then restart the API and reload. |
| **Detailed** looks the same as **Clean**. | The two Map IDs have the same Map Style. Link a style with all places to the detailed Map ID. |
| Shops and hotels still show on the clean map. | The Map Style still shows those map features, or Google has not applied the change yet. Check the visibility of each feature, then wait some minutes. |
| The map stays light with **Night chart**. | The Map Style has no dark variant. Add a dark variant to the Map Style. |
| The map shows, but the layers do not show, or the browser console shows a WebGL error. | The browser or the GPU has WebGL disabled. Enable hardware acceleration in the browser settings. To use the built-in chart, remove `GOOGLE_MAPS_API_KEY` from `.env` and restart the API. |
