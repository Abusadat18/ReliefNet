/// <reference types="google.maps" />
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import { useEffect, useMemo, useRef, useState } from "react";
import { buildLayers, chartColours } from "./deckLayers";
import type { LayerProps } from "./MapLayers";

let loading: Promise<void> | null = null;
const authFailures = new Set<() => void>();

/** Loads the Maps JavaScript API once per page. */
function loadMaps(key: string): Promise<void> {
  if (loading) return loading;
  loading = new Promise<void>((resolve, reject) => {
    const w = window as unknown as Record<string, unknown>;
    w.__reliefnetMapsReady = () => resolve();
    // Google calls this global when it refuses the key (wrong key, API off, site not allowed).
    w.gm_authFailure = () => authFailures.forEach((f) => f());
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&loading=async&callback=__reliefnetMapsReady`;
    s.async = true;
    s.onerror = () => {
      loading = null;
      reject(new Error("The Google Maps script did not load. Check the internet connection."));
    };
    document.head.appendChild(s);
  });
  return loading;
}

/** True while the night chart is showing, from the toggle or from the system setting. */
function useNight(): boolean {
  const read = () => {
    const t = document.documentElement.getAttribute("data-theme");
    return t ? t === "night" : !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  };
  const [night, setNight] = useState(read);
  useEffect(() => {
    const update = () => setNight(read());
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener("change", update);
    return () => {
      mo.disconnect();
      mq?.removeEventListener("change", update);
    };
  }, []);
  return night;
}

interface Props extends LayerProps {
  apiKey: string;
  mapId: string;
  /** A second Map ID whose style shows all of Google's places; enables the Clean / Detailed switch. */
  mapIdDetailed: string | null;
  onFail: (why: string) => void;
}

/**
 * Google's vector map with our layers drawn by deck.gl in step with every map frame,
 * so households, routes and flood marks stay in place while the map zooms or turns.
 * The map's look comes from the Map Style linked to the Map ID in Google Cloud.
 */
const DETAIL_STORE = "reliefnet.mapDetail";

export function GoogleMap({ apiKey, mapId, mapIdDetailed, onFail, ...props }: Props) {
  const { region } = props;
  const boxRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const overlayRef = useRef<GoogleMapsOverlay | null>(null);
  // The map is made again when the theme changes; this keeps the view across that.
  const viewRef = useRef<{ center: google.maps.LatLngLiteral; zoom: number } | null>(null);
  const [ready, setReady] = useState(0);
  const [zoom, setZoom] = useState(15);
  const [satellite, setSatellite] = useState(false);
  const [detailed, setDetailed] = useState(() => {
    try {
      return localStorage.getItem(DETAIL_STORE) === "detailed";
    } catch {
      return false;
    }
  });
  const chooseDetail = (on: boolean) => {
    setDetailed(on);
    try {
      localStorage.setItem(DETAIL_STORE, on ? "detailed" : "clean");
    } catch {
      /* not kept in private mode */
    }
  };
  // Google takes a map's look only from its Map ID, so each look is its own Map ID.
  const activeMapId = detailed && mapIdDetailed ? mapIdDetailed : mapId;
  const night = useNight();

  const bounds = useMemo(() => {
    const pts = region.wards.flatMap((w) => w.polygon);
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    return { south: Math.min(...lats), north: Math.max(...lats), west: Math.min(...lons), east: Math.max(...lons) };
  }, [region.wards]);

  useEffect(() => {
    let cancelled = false;
    let waiting: google.maps.MapsEventListener | null = null;
    const failed = () => onFail("Google Maps refused the key, so the built-in chart is showing. See docs/GOOGLE_MAPS.md.");
    authFailures.add(failed);

    loadMaps(apiKey)
      .then(async () => {
        const { Map } = (await google.maps.importLibrary("maps")) as google.maps.MapsLibrary;
        if (cancelled || !boxRef.current) return;
        const view = viewRef.current;
        const map = new Map(boxRef.current, {
          mapId: activeMapId,
          colorScheme: night ? "DARK" : "LIGHT",
          renderingType: "VECTOR" as google.maps.RenderingType,
          mapTypeId: satellite ? "hybrid" : "roadmap",
          center: view?.center,
          zoom: view?.zoom,
          disableDefaultUI: true,
          clickableIcons: false,
          gestureHandling: "greedy",
          keyboardShortcuts: true,
        });
        if (!view) map.fitBounds(bounds, 24);
        map.addListener("zoom_changed", () => setZoom(map.getZoom() ?? 15));
        map.addListener("idle", () => {
          const c = map.getCenter();
          if (c) viewRef.current = { center: c.toJSON(), zoom: map.getZoom() ?? 15 };
        });
        mapRef.current = map;
        setZoom(map.getZoom() ?? 15);
        // deck.gl reads the rendering type once; attach only when the map knows it.
        const attach = () => {
          if (cancelled) return;
          // Not interleaved: deck.gl's vector path makes its Deck in the positioning overlay's
          // onAdd, before Google hands over its GL context, and then ignores that context
          // (deck.gl 9.3/9.4), so nothing draws. Its own canvas still takes the camera from
          // Google's WebGL overlay on every frame, so the layers follow the zoom.
          const overlay = new GoogleMapsOverlay({ interleaved: false, layers: [] });
          overlay.setMap(map);
          overlayRef.current = overlay;
          setReady((n) => n + 1);
        };
        if (map.getRenderingType() === "UNINITIALIZED") {
          waiting = google.maps.event.addListenerOnce(map, "renderingtype_changed", attach);
        } else {
          attach();
        }
      })
      .catch((e: Error) => onFail(`${e.message} The built-in chart is showing.`));

    return () => {
      cancelled = true;
      waiting?.remove();
      authFailures.delete(failed);
      overlayRef.current?.setMap(null);
      overlayRef.current?.finalize();
      overlayRef.current = null;
      mapRef.current = null;
      if (boxRef.current) boxRef.current.innerHTML = "";
    };
    // Colour scheme and rendering mode are fixed when a map is made, and deck.gl picks its
    // drawing mode once, so a theme or map type change makes a new map at the same view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, activeMapId, bounds, night, satellite]);

  const { snapshot, selected, focusRequest, flashes, show, onSelectFamily, onRoadClick } = props;
  useEffect(() => {
    overlayRef.current?.setProps({
      layers: buildLayers({
        region,
        families: snapshot?.families ?? [],
        routes: snapshot?.routes ?? [],
        teams: snapshot?.teams ?? [],
        pending: snapshot?.pending ?? [],
        flashes,
        selected,
        focusRequest,
        zoom,
        show,
        colours: chartColours(),
        onSelectFamily,
        onRoadClick,
      }),
    });
  }, [ready, region, snapshot, selected, focusRequest, flashes, zoom, night, show, onSelectFamily, onRoadClick]);

  const zoomBy = (d: number) => {
    const m = mapRef.current;
    if (m) m.setZoom((m.getZoom() ?? 15) + d);
  };

  return (
    <>
      <div ref={boxRef} className={`gmap${satellite ? " satellite" : ""}`} role="region" aria-label={`Map of ${region.area?.title || "the area"}`} />
      <div className="neatline" aria-hidden="true" />
      <div className="zoom">
        <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1)}>
          +
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomBy(-1)}>
          −
        </button>
        <button type="button" aria-label="Show the whole area" onClick={() => mapRef.current?.fitBounds(bounds, 24)} style={{ fontSize: 13 }}>
          ⤢
        </button>
      </div>
      <div className="maptype" role="group" aria-label="Map type">
        <button type="button" aria-pressed={!satellite} onClick={() => setSatellite(false)}>
          Map
        </button>
        <button type="button" aria-pressed={satellite} onClick={() => setSatellite(true)}>
          Satellite
        </button>
      </div>
      {mapIdDetailed && !satellite && (
        <div className="maptype detail" role="group" aria-label="Places on the map">
          <button type="button" aria-pressed={!detailed} onClick={() => chooseDetail(false)} title="Hide shops, food and hotels">
            Clean
          </button>
          <button type="button" aria-pressed={detailed} onClick={() => chooseDetail(true)} title="Show all of Google's places">
            Detailed
          </button>
        </div>
      )}
    </>
  );
}
