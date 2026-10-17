import { useEffect, useRef, useState } from "react";

export type LayerKey = "wards" | "routes" | "served" | "low" | "places";
export type Visible = Record<LayerKey, boolean>;

const LAYERS: { key: LayerKey; label: string; hint: string }[] = [
  { key: "wards", label: "Ward zones", hint: "The 16 zones that messages call “ward 11”" },
  { key: "routes", label: "Team routes", hint: "The way each team takes" },
  { key: "served", label: "Served households", hint: "Households that got help" },
  { key: "low", label: "Low roads near drains", hint: "Roads that flood first" },
  { key: "places", label: "Landmarks and shelters", hint: "Places from the gazetteer, and relief camps" },
];

const STORE = "reliefnet.layers";
const ALL_ON: Visible = { wards: true, routes: true, served: true, low: true, places: true };

/** Which map layers this viewer wants to see. Each browser keeps its own choice. */
export function useMapLayers(): [Visible, (key: LayerKey, on: boolean) => void] {
  const [visible, setVisible] = useState<Visible>(() => {
    try {
      return { ...ALL_ON, ...JSON.parse(localStorage.getItem(STORE) ?? "{}") };
    } catch {
      return ALL_ON;
    }
  });
  const set = (key: LayerKey, on: boolean) =>
    setVisible((v) => {
      const next = { ...v, [key]: on };
      try {
        localStorage.setItem(STORE, JSON.stringify(next));
      } catch {
        /* not kept in private mode */
      }
      return next;
    });
  return [visible, set];
}

export function LayersMenu({ visible, onChange }: { visible: Visible; onChange: (key: LayerKey, on: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const hidden = LAYERS.filter((l) => !visible[l.key]).length;

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div className="layers-menu" ref={ref}>
      <button type="button" className="layers-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Layers{hidden ? ` (${hidden} hidden)` : ""}
      </button>
      {open && (
        <fieldset className="layers-list">
          <legend className="sr-only">Show on the map</legend>
          {LAYERS.map((l) => (
            <label key={l.key} title={l.hint}>
              <input type="checkbox" checked={visible[l.key]} onChange={(e) => onChange(l.key, e.target.checked)} />
              {l.label}
            </label>
          ))}
        </fieldset>
      )}
    </div>
  );
}
