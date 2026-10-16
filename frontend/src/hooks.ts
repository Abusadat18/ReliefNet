import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamUrl } from "./api";
import type { LiveEvent } from "./types";

/** Subscribe to the org's live event stream. Reconnects with backoff. */
export function useLiveEvents(onEvent: (e: LiveEvent) => void, enabled = true) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let es: EventSource | null = null;
    let stopped = false;
    let retry = 1000;
    let timer: number | undefined;

    const open = async () => {
      if (stopped) return;
      es = new EventSource(await streamUrl());
      es.addEventListener("hello", () => {
        setConnected(true);
        retry = 1000;
      });
      es.onmessage = (m) => {
        try {
          handler.current(JSON.parse(m.data) as LiveEvent);
        } catch {
          /* ignore malformed frames */
        }
      };
      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!stopped) timer = window.setTimeout(open, retry);
        retry = Math.min(retry * 2, 15000);
      };
    };
    void open();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      es?.close();
    };
  }, [enabled]);

  return connected;
}

/** Fetch JSON; refetch on demand and on an interval. */
export function useResource<T>(path: string | null, intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef(false);

  const load = useCallback(async () => {
    if (!path || inflight.current) return;
    inflight.current = true;
    try {
      setData(await api.get<T>(path));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inflight.current = false;
    }
  }, [path]);

  useEffect(() => {
    void load();
    if (!intervalMs) return;
    const t = window.setInterval(load, intervalMs);
    return () => window.clearInterval(t);
  }, [load, intervalMs]);

  return { data, error, reload: load, setData };
}

/** Call fn at most once per `ms`, trailing. */
export function useThrottled(fn: () => void, ms: number) {
  const last = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const f = useRef(fn);
  f.current = fn;
  return useCallback(() => {
    const now = Date.now();
    const wait = Math.max(0, last.current + ms - now);
    if (timer.current !== undefined) return;
    timer.current = window.setTimeout(() => {
      timer.current = undefined;
      last.current = Date.now();
      f.current();
    }, wait);
  }, [ms]);
}

export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(t);
  }, [ms]);
  return now;
}

export function clock(ms: number | null | undefined) {
  if (!ms) return "--:--";
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function ago(ms: number, now = Date.now()) {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = m / 60;
  return `${h.toFixed(h < 10 ? 1 : 0)} h ago`;
}

export function needLabel(n: string) {
  return n.replace("_", " ");
}
