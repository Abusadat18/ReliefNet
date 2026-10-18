import { LayersIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";

export type LayerKey = "names" | "wards" | "routes" | "served" | "low" | "places";
export type Visible = Record<LayerKey, boolean>;

const LAYERS: { key: LayerKey; label: string; hint: string }[] = [
  { key: "names", label: "Names", hint: "Neighbourhoods, roads and landmarks: the names that Intake knows" },
  { key: "wards", label: "Ward zones", hint: "The 16 zones that messages call “ward 11”" },
  { key: "routes", label: "Team routes", hint: "The way each team takes. The selected route stays bold." },
  { key: "served", label: "Served households", hint: "Households that got help" },
  { key: "low", label: "Low roads near drains", hint: "Roads that flood first" },
  { key: "places", label: "Landmarks and shelters", hint: "Places from the gazetteer, and relief camps" },
];

const STORE = "reliefnet.layers";
const ALL_ON: Visible = { names: true, wards: true, routes: true, served: true, low: true, places: true };

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
  const hidden = LAYERS.filter((l) => !visible[l.key]).length;
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button variant="outline" size="sm" className="bg-background shadow-sm">
            <LayersIcon data-icon="inline-start" />
            Layers
            {hidden > 0 && <span className="num text-[10px] text-muted-foreground">{hidden} off</span>}
          </Button>
        }
      />
      <PopoverContent align="end" className="w-80">
        <PopoverHeader>
          <PopoverTitle>Show on the map</PopoverTitle>
          <PopoverDescription>Each browser keeps its own choice.</PopoverDescription>
        </PopoverHeader>
        <div className="flex flex-col">
          {LAYERS.map((l) => (
            <label key={l.key} className="flex cursor-pointer items-start justify-between gap-3 rounded-md px-1 py-2 hover:bg-muted">
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">{l.label}</span>
                <span className="text-xs text-muted-foreground">{l.hint}</span>
              </span>
              <Switch checked={visible[l.key]} onCheckedChange={(on) => onChange(l.key, on)} className="mt-0.5" />
            </label>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
