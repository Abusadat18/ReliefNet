import { useEffect, useState } from "react";

const KEY = "reliefnet.theme";
type Theme = "auto" | "day" | "night";

function read(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme) || "auto";
  } catch {
    return "auto";
  }
}

export function applyStoredTheme() {
  const t = read();
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
  const night =
    theme === "night" || (theme === "auto" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  return (
    <button
      type="button"
      className="btn quiet small"
      onClick={() => setTheme(night ? "day" : "night")}
      aria-label={night ? "Switch to the day chart" : "Switch to the night chart"}
    >
      {night ? "Day chart" : "Night chart"}
    </button>
  );
}
