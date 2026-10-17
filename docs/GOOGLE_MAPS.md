# Google Maps

The operations dashboard can show a Google map under its layers. Without a key, it draws its own chart. The chart needs no internet, so it is also the offline mode.

## What Google does and does not do here

| Part | Source |
|---|---|
| The map picture, zoom, pan and satellite view | Google Maps JavaScript API |
| The road graph that Dispatch routes on | OpenStreetMap, stored in FalkorDB (see [AREAS.md](AREAS.md)) |
| Households, teams, routes, flooded roads, shelters | ReliefNet, drawn on top of the map |

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

You do not need a Map ID. ReliefNet styles the map itself, so the map matches the day and night chart themes.

The API sends the key to the web app at run time (`/api/config`). You do not need to rebuild the web image after you change the key.

## Use the map

- Drag to pan. Scroll or use **+** and **−** to zoom. Click **⤢** to show the whole area again.
- Click **Satellite** to see the real ground. Click **Map** to go back.
- Click a household to open it. Click any road to mark it flooded or open.
- The map shows only the roads that carry news: bridges and flyovers, low roads near drains (dotted), reported roads (dashed) and flooded roads (with a cross). The other streets come from Google's map.
- **Night chart** in the top bar also changes the map to night colours.

## Problems

| What you see | Cause and fix |
|---|---|
| "Google Maps refused the key, so the built-in chart is showing." | The key is wrong, the Maps JavaScript API is not enabled, or the site address is not in the key's website list. Check steps 3 and 8, then reload. |
| "The Google Maps script did not load." | The browser cannot reach Google. Check the internet connection. The built-in chart still works. |
| The built-in chart shows and there is no message. | The API has no key. Check `GOOGLE_MAPS_API_KEY` in `.env`, then restart the API. |
| The map is grey with "For development purposes only". | Billing is not enabled on the Google Cloud project. |
