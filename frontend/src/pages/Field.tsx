import { ArrowUpIcon, CameraIcon, CheckIcon, LogOutIcon, NavigationIcon, PhoneIcon, RouteIcon, SendIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { useSession } from "../auth";
import { Eyebrow, urgency } from "../components/kit";
import { clock, needLabel, useLiveEvents } from "../hooks";
import type { Assignment, ChatTurn, LiveEvent } from "../types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface FieldMe {
  user: { id: string; name: string; team: string | null; org: string };
  assignments: Assignment[];
  telegram_linked: boolean;
}

const ACTION_LABEL: Record<string, string> = {
  mark_delivered: "Delivery recorded",
  report_road: "Road report sent",
  report_new_need: "New request logged",
  report_observation: "Observation saved",
  my_assignments: "Checked assignments",
  nearest_shelters: "Found shelters",
  road_status: "Checked roads",
};

function initials(name: string) {
  const parts = name.replace(/^Team\s+/i, "").split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "T") + (parts[1]?.[0] ?? "");
}

export function Field() {
  const { me, config, signOut, refresh } = useSession();
  const [data, setData] = useState<FieldMe | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [link, setLink] = useState<{ code: string; deep_link: string | null; bot: string | null } | null>(null);
  const [teams, setTeams] = useState<{ name: string }[]>([]);
  const threadRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setData(await api.get<FieldMe>("/api/field/me"));
  }, []);

  useEffect(() => {
    void load();
    api.get<ChatTurn[]>("/api/field/history").then(setTurns);
    api.get<{ name: string }[]>("/api/ops/teams").then(setTeams);
  }, [load]);

  useLiveEvents(
    useCallback(
      (e: LiveEvent) => {
        if (["assigned", "delivered", "rerouted", "road"].includes(e.kind)) void load();
      },
      [load],
    ),
  );

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  const send = async (msg: string) => {
    const t = msg.trim();
    if (!t || sending) return;
    setSending(true);
    setText("");
    setTurns((x) => [...x, { role: "user", text: t, at: Date.now() }]);
    try {
      const r = await api.post<{ reply: string; actions: ChatTurn["actions"] }>("/api/field/chat", { text: t });
      setTurns((x) => [...x, { role: "agent", text: r.reply, at: Date.now(), actions: r.actions }]);
      void load();
    } catch (e) {
      setTurns((x) => [...x, { role: "agent", text: `Not sent: ${e instanceof Error ? e.message : String(e)}. Try again.`, at: Date.now() }]);
    } finally {
      setSending(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(text);
  };

  const photo = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    setTurns((x) => [...x, { role: "user", text: `Photo: ${file.name}`, at: Date.now() }]);
    try {
      await api.upload("/api/field/photo", form);
      setTurns((x) => [...x, { role: "agent", text: "Photo saved for the coordinators.", at: Date.now() }]);
    } catch (e) {
      setTurns((x) => [...x, { role: "agent", text: `Photo not saved: ${e instanceof Error ? e.message : e}`, at: Date.now() }]);
    }
  };

  const jobs = data?.assignments ?? [];
  const next = jobs[0];
  const team = data?.user.team ?? me?.team;
  const u = urgency(next?.priority);

  return (
    <div className="mx-auto flex h-dvh max-w-xl flex-col bg-background">
      <header className="flex shrink-0 items-center gap-2.5 border-b px-4 py-3">
        <span className="num grid size-8 shrink-0 place-items-center rounded-lg bg-slate text-xs font-bold text-white">
          {team ? initials(team).toUpperCase() : "?"}
        </span>
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          <b className="truncate text-[15px] font-semibold">{team ?? "No team yet"}</b>
          <span className="truncate text-xs text-muted-foreground">
            {me?.name} · {me?.org_name}
          </span>
        </div>
        {data?.telegram_linked ? (
          <span className="num inline-flex h-6 items-center gap-1 rounded-full bg-success-soft px-2 text-[9px] font-semibold text-success">
            <SendIcon className="size-3" aria-hidden="true" />
            LINKED
          </span>
        ) : (
          <Button variant="outline" size="sm" onClick={async () => setLink(await api.post("/api/field/telegram-link"))}>
            <SendIcon data-icon="inline-start" />
            Link Telegram
          </Button>
        )}
        <Button variant="ghost" size="icon" onClick={signOut} aria-label="Sign out" title="Sign out">
          <LogOutIcon />
        </Button>
      </header>

      <div className="shrink-0 px-3 pt-3 pb-1">
        {!team ? (
          <section className="flex flex-col gap-3 rounded-2xl border bg-card p-4">
            <h2 className="text-xl font-normal tracking-tight">
              Join your <span className="accent-serif">team</span>
            </h2>
            <p className="text-sm text-muted-foreground">Choose the team you are working with today. Assignments for that team appear here.</p>
            {teams.length === 0 && <p className="text-sm text-muted-foreground">Your organisation has no teams yet. Ask an admin to add a team.</p>}
            <div className="flex flex-wrap gap-2">
              {teams.map((t) => (
                <Button
                  key={t.name}
                  variant="outline"
                  onClick={async () => {
                    await api.post("/api/field/team", { team: t.name });
                    refresh();
                    void load();
                  }}
                >
                  {t.name}
                </Button>
              ))}
            </div>
          </section>
        ) : next ? (
          <section className="flex flex-col gap-3 rounded-2xl bg-slate p-[18px] text-white" aria-label="Next assignment">
            <div className="flex items-center justify-between gap-2">
              <span className="eyebrow text-[#9fb0b6]">[ Next job · {next.id} ]</span>
              {next.priority != null && (
                <span
                  className={cn(
                    "num inline-flex h-5 items-center rounded-full px-2 text-[10px] font-semibold",
                    u.key === "critical" || u.key === "high" ? "bg-[#f0443833] text-[#ff8a80]" : "bg-white/10 text-white/80",
                  )}
                >
                  PRIORITY {next.priority}
                </span>
              )}
            </div>
            <h2 className="text-[26px] leading-tight font-normal tracking-tight">
              {next.name || next.family}, <span className="accent-serif">ward {next.ward}</span>
            </h2>
            <p className="text-sm leading-relaxed text-[#d5dbe1]">
              {next.landmark ? `Near ${next.landmark}. ` : ""}
              {next.people} people. Needs {next.needs.map(needLabel).join(", ")}.
            </p>
            <div className="flex items-start gap-2 rounded-lg bg-white/10 px-2.5 py-2 text-xs text-[#eef1f2]">
              <RouteIcon className="mt-0.5 size-3.5 shrink-0 text-rain" aria-hidden="true" />
              <span>
                ETA {next.eta_min} min{next.roads?.length ? ` via ${next.roads.slice(0, 3).join(", ")}${next.roads.length > 3 ? "…" : ""}` : ""}
              </span>
            </div>
            {(next.lat != null && next.lon != null) || next.call ? (
              <div className="flex gap-2">
                {next.lat != null && next.lon != null && (
                  <Button
                    render={
                      <a
                        href={`https://www.google.com/maps/dir/?api=1&destination=${next.lat},${next.lon}`}
                        target="_blank"
                        rel="noreferrer"
                        title="Google's route can differ. Follow the safe route above."
                      />
                    }
                    nativeButton={false}
                    className="h-10 flex-1 bg-rain font-semibold text-slate hover:bg-white"
                  >
                    <NavigationIcon data-icon="inline-start" />
                    Open in Maps
                  </Button>
                )}
                {next.call && (
                  <Button
                    render={<a href={`tel:${next.call}`} />}
                    nativeButton={false}
                    variant="outline"
                    className="h-10 border-white/35 bg-transparent text-white hover:bg-white/10 hover:text-white"
                  >
                    <PhoneIcon data-icon="inline-start" />
                    Call
                  </Button>
                )}
              </div>
            ) : null}
            {jobs.length > 1 && (
              <button type="button" className="self-start text-xs font-medium text-[#9fb0b6]" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Hide other assignments" : `${jobs.length - 1} more assignment${jobs.length > 2 ? "s" : ""}  ›`}
              </button>
            )}
            {showAll && (
              <ul className="flex flex-col gap-1.5 border-t border-white/15 pt-2 text-xs text-[#d5dbe1]">
                {jobs.slice(1).map((j) => (
                  <li key={j.id}>
                    <b className="font-semibold text-white">{j.name || j.family}</b>, ward {j.ward} {j.landmark}: {j.needs.map(needLabel).join(", ")}{" "}
                    <span className="num">
                      ({j.id}, ETA {j.eta_min} min)
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ) : (
          <section className="flex flex-col gap-1.5 rounded-2xl border bg-card p-4">
            <h2 className="text-xl font-normal tracking-tight">
              No assignment <span className="accent-serif">right now</span>
            </h2>
            <p className="text-sm text-muted-foreground">Dispatch sends the next household here. You can still report roads and new needs.</p>
          </section>
        )}
      </div>

      <div ref={threadRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto bg-muted px-4 py-4" aria-live="polite">
        {turns.length > 0 && <Eyebrow className="self-center">Today</Eyebrow>}
        {turns.length === 0 && (
          <div className="max-w-[85%] self-start rounded-2xl rounded-bl-sm border bg-background px-3.5 py-2.5 text-sm leading-relaxed">
            Tell me what is happening. For example: “done {next?.id ?? "R-123"}, gave water and tablets”, “{config?.area.example_road_report}”,
            or “7 people on a roof near the school, ward 10”.
          </div>
        )}
        {turns.map((t, i) => {
          const me = t.role === "user";
          return (
            <div key={i} className={cn("flex max-w-[85%] flex-col gap-1", me ? "items-end self-end" : "items-start self-start")}>
              <div
                className={cn(
                  "flex flex-col gap-1.5 px-3.5 py-2.5 text-sm leading-relaxed",
                  me ? "rounded-2xl rounded-br-sm bg-primary text-primary-foreground" : "rounded-2xl rounded-bl-sm border bg-background",
                )}
              >
                <span className="whitespace-pre-line">{t.text}</span>
                {t.actions && t.actions.length > 0 && (
                  <span className="flex flex-wrap gap-1">
                    {t.actions.map((a, j) => (
                      <span key={j} className="num inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-[10px] font-semibold text-success uppercase">
                        <CheckIcon className="size-3" aria-hidden="true" />
                        {ACTION_LABEL[a.tool] ?? a.tool}
                      </span>
                    ))}
                  </span>
                )}
              </div>
              <time className="num text-[10px] text-muted-foreground">
                {clock(t.at)}
                {!me && " · Field agent"}
              </time>
            </div>
          );
        })}
        {sending && <div className="self-start rounded-2xl rounded-bl-sm border bg-background px-3.5 py-2.5 text-sm text-muted-foreground">Recording…</div>}
      </div>

      <form className="flex shrink-0 flex-col gap-2.5 border-t px-3 pt-2.5 pb-[max(12px,env(safe-area-inset-bottom))]" onSubmit={onSubmit}>
        <div className="flex gap-1.5 overflow-x-auto" aria-label="Quick replies">
          {next && (
            <Button type="button" variant="outline" size="sm" onClick={() => setText(`Done ${next.id}, gave ${next.needs.map(needLabel).join(" and ")}`)}>
              Delivered to {next.name || next.family}
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-destructive text-destructive"
            onClick={() => setText(config?.area.example_road_report ?? "")}
          >
            Road flooded
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => void send("What are my tasks?")}>
            My tasks
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => void send("Nearest shelter with space?")}>
            Nearest shelter
          </Button>
        </div>
        <div className="flex items-center gap-1.5 rounded-full border bg-background py-1 pr-1 pl-1.5">
          <Button type="button" variant="ghost" size="icon" aria-label="Send a photo" onClick={() => fileRef.current?.click()}>
            <CameraIcon />
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            onChange={(e) => e.target.files?.[0] && void photo(e.target.files[0])}
          />
          <label htmlFor="say" className="sr-only">
            Message to the Field agent
          </label>
          <textarea
            id="say"
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(text);
              }
            }}
            placeholder="Type in English or Hinglish"
            className="max-h-28 min-w-0 flex-1 resize-none bg-transparent py-1.5 text-sm outline-none placeholder:text-muted-foreground"
          />
          <Button type="submit" size="icon" aria-label="Send" disabled={sending || !text.trim()}>
            <ArrowUpIcon />
          </Button>
        </div>
      </form>

      <Dialog open={!!link} onOpenChange={(o) => !o && setLink(null)}>
        <DialogContent className="gap-4 p-6">
          <DialogHeader>
            <DialogTitle className="text-xl font-normal">
              Link <span className="accent-serif">Telegram</span>
            </DialogTitle>
            <DialogDescription>
              {link?.deep_link ? (
                <>
                  Open{" "}
                  <a className="text-primary underline" href={link.deep_link}>
                    @{link.bot}
                  </a>{" "}
                  and press Start. The code links automatically.
                </>
              ) : (
                <>Open the ReliefNet bot in Telegram{config?.telegram_bot ? ` (@${config.telegram_bot})` : ""} and send this message:</>
              )}
            </DialogDescription>
          </DialogHeader>
          <p className="num rounded-xl bg-slate px-4 py-3 text-2xl font-semibold text-white">/link {link?.code}</p>
          <p className="text-sm text-muted-foreground">The code works once and expires in 15 minutes. After linking, new assignments arrive in Telegram too.</p>
          <DialogFooter className="-mx-6 -mb-6 px-6">
            <Button onClick={() => setLink(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
