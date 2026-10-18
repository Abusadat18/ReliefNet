import { MoonIcon, SunIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

const KEY = "reliefnet.theme";
type Theme = "auto" | "day" | "night";

function read(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme) || "auto";
  } catch {
    return "auto";
  }
}

function isNight(t: Theme) {
  return t === "night" || (t === "auto" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches);
}

export function applyStoredTheme() {
  const t = read();
  document.documentElement.classList.toggle("dark", isNight(t));
  // The map and the chart read data-theme; "auto" leaves them on the system setting.
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
}

/** Day chart / night chart, like the display modes on a ship's chart plotter. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* not persisted in private mode */
    }
    applyStoredTheme();
  }, [theme]);
  const night = isNight(theme);
  return (
    <Button
      variant="outline"
      size="icon"
      onClick={() => setTheme(night ? "day" : "night")}
      aria-label={night ? "Switch to the day chart" : "Switch to the night chart"}
      title={night ? "Day chart" : "Night chart"}
    >
      {night ? <SunIcon /> : <MoonIcon />}
    </Button>
  );
}
