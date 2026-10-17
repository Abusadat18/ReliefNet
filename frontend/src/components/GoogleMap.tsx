/// <reference types="google.maps" />
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MapLayers, type LayerProps, type Project } from "./MapLayers";

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

// The basemap steps back like the paper of a printed chart, so our layers carry the news.
// Colours follow the chart tokens in styles.css.
function chartStyle(night: boolean): google.maps.MapTypeStyle[] {
  const c = night
    ? { land: "#1c2a26", road: "#2a3c45", major: "#34505c", water: "#10303f", label: "#74858c", halo: "#0f1a20", park: "#1f3229" }
    : { land: "#f1ead3", road: "#fbf8ee", major: "#ffffff", water: "#cfe5f1", label: "#7b8a92", halo: "#f7f9f8", park: "#e4e6c8" };
  return [
    { elementType: "geometry", stylers: [{ color: c.land }] },
    { elementType: "labels.text.fill", stylers: [{ color: c.label }] },
    { elementType: "labels.text.stroke", stylers: [{ color: c.halo }] },
    { elementType: "labels.icon", stylers: [{ visibility: "off" }] },
    { featureType: "poi", stylers: [{ visibility: "off" }] },
    { featureType: "poi.park", elementType: "geometry", stylers: [{ visibility: "on" }, { color: c.park }] },
    { featureType: "transit", elementType: "labels", stylers: [{ visibility: "off" }] },
    { featureType: "road", elementType: "geometry", stylers: [{ color: c.road }] },
    { featureType: "road.arterial", elementType: "geometry", stylers: [{ color: c.major }] },
    { featureType: "road.highway", elementType: "geometry", stylers: [{ color: c.major }] },
    { featureType: "road", elementType: "labels.icon", stylers: [{ visibility: "off" }] },
    { featureType: "water", elementType: "geometry", stylers: [{ color: c.water }] },
    { featureType: "administrative", elementType: "geometry", stylers: [{ visibility: "off" }] },
  ];
}

interface Drawn {
  P: Project;
  left: number;
  top: number;
  width: number;
  height: number;
  zoom: number;
}

const PAD = 0.004; // degrees around the area, so markers at the edge are not cut off

export function GoogleMap({ apiKey, onFail, ...props }: LayerProps & { apiKey: string; onFail: (why: string) => void }) {
  const { region } = props;
  const boxRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const [layer, setLayer] = useState<HTMLDivElement | null>(null);
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  const [satellite, setSatellite] = useState(false);
  const night = useNight();

  const bounds = useMemo(() => {
    const pts = region.wards.flatMap((w) => w.polygon);
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    return { s: Math.min(...lats), n: Math.max(...lats), w: Math.min(...lons), e: Math.max(...lons) };
  }, [region.wards]);

  const fit = () =>
    mapRef.current?.fitBounds({ south: bounds.s, west: bounds.w, north: bounds.n, east: bounds.e }, 24);

  useEffect(() => {
    let cancelled = false;
    let overlay: google.maps.OverlayView | null = null;
    const failed = () => onFail("Google Maps refused the key, so the built-in chart is showing. See docs/GOOGLE_MAPS.md.");
    authFailures.add(failed);

    loadMaps(apiKey)
      .then(async () => {
        const { Map, OverlayView } = (await google.maps.importLibrary("maps")) as google.maps.MapsLibrary;
        if (cancelled || !boxRef.current) return;
        const map = new Map(boxRef.current, {
          disableDefaultUI: true,
          clickableIcons: false,
          gestureHandling: "greedy",
          keyboardShortcuts: true,
          styles: chartStyle(night),
          backgroundColor: "transparent",
        });
        mapRef.current = map;
        map.fitBounds({ south: bounds.s, west: bounds.w, north: bounds.n, east: bounds.e }, 24);

        // One overlay holds our whole SVG. Google moves it while the map pans; we redraw it on zoom.
        const div = document.createElement("div");
        div.className = "gmap-layer";
        class ChartOverlay extends OverlayView {
          onAdd() {
            this.getPanes()!.overlayMouseTarget.appendChild(div);
          }
          draw() {
            const proj = this.getProjection();
            if (!proj) return;
            const nw = proj.fromLatLngToDivPixel(new google.maps.LatLng(bounds.n + PAD, bounds.w - PAD))!;
            const se = proj.fromLatLngToDivPixel(new google.maps.LatLng(bounds.s - PAD, bounds.e + PAD))!;
            const left = nw.x;
            const top = nw.y;
            Object.assign(div.style, {
              left: `${left}px`,
              top: `${top}px`,
              width: `${se.x - left}px`,
              height: `${se.y - top}px`,
            });
            const P: Project = (lat, lon) => {
              const p = proj.fromLatLngToDivPixel(new google.maps.LatLng(lat, lon))!;
              return [p.x - left, p.y - top];
            };
            setDrawn({ P, left, top, width: se.x - left, height: se.y - top, zoom: map.getZoom() ?? 15 });
          }
          onRemove() {
            div.remove();
          }
        }
        overlay = new ChartOverlay();
        overlay.setMap(map);
        setLayer(div);
      })
      .catch((e: Error) => onFail(`${e.message} The built-in chart is showing.`));

    return () => {
      cancelled = true;
      authFailures.delete(failed);
      overlay?.setMap(null);
      mapRef.current = null;
    };
    // The map is made once per key and area; theme and map type change it in place below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, bounds]);

  useEffect(() => {
    mapRef.current?.setOptions({ styles: chartStyle(night) });
  }, [night]);
  useEffect(() => {
    mapRef.current?.setMapTypeId(satellite ? "hybrid" : "roadmap");
  }, [satellite]);

  const zoomBy = (d: number) => {
    const m = mapRef.current;
    if (m) m.setZoom((m.getZoom() ?? 15) + d);
  };

  return (
    <>
      <div ref={boxRef} className={`gmap${satellite ? " satellite" : ""}`} role="region" aria-label={`Map of ${region.area?.title || "the area"}`} />
      {layer &&
        drawn &&
        createPortal(
          <svg className="chart gmap-svg" width={drawn.width} height={drawn.height} role="img" aria-label="Households, teams, routes and road reports">
            <MapLayers {...props} P={drawn.P} u={1} showLabels={drawn.zoom >= 16} roads="basemap" />
          </svg>,
          layer,
        )}
      <div className="neatline" aria-hidden="true" />
      <div className="zoom">
        <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1)}>
          +
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomBy(-1)}>
          −
        </button>
        <button type="button" aria-label="Show the whole area" onClick={fit} style={{ fontSize: 13 }}>
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
    </>
  );
}
