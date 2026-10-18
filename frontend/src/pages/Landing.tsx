import { GitForkIcon, LayersIcon, MapIcon, PlusIcon, SendIcon, Share2Icon, ZapIcon, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { PathGraph } from "../components/FamilyDrawer";
import type { Trace } from "../types";
import { cn } from "@/lib/utils";

/** One real household trail from a demo shift (R. Ram, F-201), drawn with the same component as the Ask-why sheet. */
const DEMO_TRACE: Trace = {
  family: { id: "F-201", name: "R. Ram" },
  requests: [],
  current: null,
  timeline: [],
  graph: {
    nodes: [
      { id: "M-1009", label: "Message", title: "M-1009" },
      { id: "M-1005", label: "Message", title: "M-1005" },
      { id: "R-101", label: "Request", title: "R-101" },
      { id: "R-111", label: "Request", title: "R-111" },
      { id: "Intake-1", label: "Agent", title: "Intake-1" },
      { id: "Dedupe", label: "Agent", title: "Dedupe" },
      { id: "Triage", label: "Agent", title: "Triage" },
      { id: "Dispatch-2", label: "Agent", title: "Dispatch-2" },
      { id: "T2", label: "Team", title: "Team 2 North" },
      { id: "F-201", label: "Family", title: "R. Ram" },
    ],
    edges: [
      { from: "M-1009", to: "R-101", type: "BECAME" },
      { from: "M-1005", to: "R-111", type: "BECAME" },
      { from: "R-111", to: "R-101", type: "DUPLICATE_OF" },
      { from: "R-101", to: "Intake-1", type: "PROCESSED_BY" },
      { from: "R-101", to: "Triage", type: "PROCESSED_BY" },
      { from: "R-101", to: "Dispatch-2", type: "PROCESSED_BY" },
      { from: "R-111", to: "Dedupe", type: "PROCESSED_BY" },
      { from: "R-101", to: "T2", type: "ASSIGNED_TO" },
      { from: "R-101", to: "F-201", type: "FOR" },
    ],
  },
};

const BUILT_ON: [LucideIcon, string][] = [
  [Share2Icon, "FalkorDB"],
  [MapIcon, "OpenStreetMap"],
  [GitForkIcon, "LangGraph"],
  [ZapIcon, "FastAPI"],
  [SendIcon, "Telegram"],
  [LayersIcon, "deck.gl"],
];

const STEPS: [string, string, string, string][] = [
  ["Intake", "reads", "Turns a messy message into people, needs and a place, in Hindi, Hinglish or English.", "Message → NEW"],
  ["Dedupe", "merges", "Finds earlier messages from the same household by its own phone and landmark.", "NEW → RESOLVED"],
  ["Triage", "prioritises", "Scores urgency from medical need, age and the flood around the house.", "RESOLVED → TRIAGED"],
  ["Dispatch", "sends", "Picks the nearest free team and a route that avoids flooded roads.", "TRIAGED → ASSIGNED"],
  ["Field", "delivers", "Turns a volunteer’s short chat into a delivery or a road report.", "ASSIGNED → DELIVERED"],
  ["Learner", "remembers", "Reads field evidence and proposes lessons for later decisions.", "Periodic"],
];

function Bracket({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("num text-xs", className)}>[ {children} ]</span>;
}

function Pill({ to, children, kind = "fill", href }: { to?: string; href?: string; children: ReactNode; kind?: "fill" | "line" | "dark" }) {
  const cls = cn(
    "num inline-flex h-10 items-center rounded-full px-5 text-xs font-medium transition-colors",
    kind === "fill" && "bg-rain text-slate hover:bg-white",
    kind === "line" && "border border-white/70 text-white hover:bg-white/10",
    kind === "dark" && "border border-slate/20 text-slate hover:bg-slate/5",
  );
  return to ? (
    <Link to={to} className={cls}>
      {children}
    </Link>
  ) : (
    <a href={href} className={cls}>
      {children}
    </a>
  );
}

function H2({ sans, serif, className, light }: { sans: string; serif: string; className?: string; light?: boolean }) {
  return (
    <h2 className={cn("text-center text-[40px] leading-[1.1] font-normal tracking-tight md:text-[44px]", light ? "text-white" : "text-slate", className)}>
      {sans} <span className="accent-serif">{serif}</span>
    </h2>
  );
}

/** The public front page. It tells the story of the product in the editorial style of Design.pen. */
export function Landing() {
  return (
    // The front page is always the light edition, whatever theme the app uses.
    <div className="force-light bg-cream text-slate">
      <section
        className="relative flex min-h-[960px] flex-col items-center justify-between overflow-hidden bg-slate bg-cover bg-center px-6 pt-7 pb-10 text-white md:px-10"
        style={{ backgroundImage: "url(/landing/hero.jpg)" }}
      >
        <div
          className="absolute inset-0"
          style={{ background: "linear-gradient(180deg, #141D2199 0%, #141D2240 35%, #141D2180 62%, #141D21F2 100%)" }}
          aria-hidden="true"
        />
        <nav className="relative flex w-full items-center justify-between gap-4">
          <div className="num hidden gap-7 text-[11px] text-[#e6ecee] md:flex">
            <a href="#why">About</a>
            <a href="#how">How it works</a>
            <a href="#memory">Shared memory</a>
            <a href="#product">Field app</a>
          </div>
          <span className="font-display text-lg font-semibold tracking-tight md:hidden">ReliefNet</span>
          <div className="flex items-center gap-2.5">
            <Pill to="/help" kind="line">
              Ask for help
            </Pill>
            <Pill to="/login">Open the ops room</Pill>
          </div>
        </nav>
        <div className="relative flex max-w-[880px] flex-col items-center gap-6 text-center">
          <Bracket className="text-rain">Flood relief coordination for Patna</Bracket>
          <h1 className="text-[44px] leading-[1.08] font-normal tracking-[-0.03em] md:text-[58px]">
            Every family understood once, <br className="hidden md:block" />
            and reached <span className="accent-serif">only once</span>
          </h1>
          <p className="max-w-[600px] text-base leading-relaxed text-[#dce3e5]">
            In a flood, help requests arrive as messy messages from every direction. ReliefNet’s agents read, merge, prioritise and dispatch
            each one through a single shared memory.
          </p>
          <div className="flex gap-3 pt-1.5">
            <Pill to="/login">Watch a flood drill</Pill>
            <Pill href="#memory" kind="line">
              Read the architecture
            </Pill>
          </div>
        </div>
        <div className="relative flex w-full flex-col items-center gap-5">
          <span
            className="font-display leading-[0.85] font-semibold tracking-[-0.04em] text-[#f2efe9e6] select-none"
            style={{ fontSize: "clamp(72px, 18.5vw, 262px)" }}
            aria-hidden="true"
          >
            RELIEFNET
          </span>
          <span className="h-px w-full bg-white/35" />
          <Bracket className="text-[#c9d3d6]">Built on open tools</Bracket>
          <ul className="flex flex-wrap justify-center gap-x-12 gap-y-3">
            {BUILT_ON.map(([Icon, name]) => (
              <li key={name} className="flex items-center gap-2 text-[15px] font-semibold text-[#e6ecee]">
                <Icon className="size-[18px]" aria-hidden="true" />
                {name}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section id="why" className="flex flex-col items-center gap-6 px-6 pt-28 md:px-20">
        <H2 sans="Why one shared memory" serif="matters" />
        <p className="max-w-[680px] text-center text-base leading-relaxed text-[#6e7273]">
          A grandmother has a fever on a roof in ward 14. Her grandson posts on WhatsApp, a neighbour calls the helpline, and her daughter writes
          on Telegram. Three messages, one household, and no shared record of who already got help.
        </p>
        <div className="grid w-full max-w-[1080px] pt-12 md:grid-cols-3">
          {[
            ["One family, three teams", "Separate lists send every volunteer to the loudest household. ReliefNet merges the messages into one request first."],
            ["The next street, none", "A street with no phone signal stays silent. Triage scores the flood around each house, not only the noise."],
            ["An answer to “why?”", "Every agent writes its reason into the graph. A coordinator asks in plain words and reads the path back."],
          ].map(([h, d], i) => (
            <div key={h} className={cn("flex flex-col items-center gap-3.5 px-9 py-4 text-center", i > 0 && "md:border-l md:border-slate/10")}>
              <span className="num text-[22px] text-[#b5b2ab]">[0{i + 1}]</span>
              <h3 className="text-[17px] font-medium">{h}</h3>
              <p className="text-sm leading-relaxed text-[#6e7273]">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="px-6 pt-24 pb-28 md:px-10">
        <div
          className="relative flex min-h-[560px] items-end justify-end overflow-hidden rounded-[20px] bg-slate bg-cover bg-center p-8 md:p-12"
          style={{ backgroundImage: "url(/landing/supplies.jpg)" }}
        >
          <div className="absolute inset-0" style={{ background: "linear-gradient(90deg, #141D2100 20%, #141D2199 55%, #141D21F0 100%)" }} aria-hidden="true" />
          <div className="relative flex max-w-[440px] flex-col gap-4 text-white">
            <Bracket className="text-rain">From the field</Bracket>
            <h2 className="text-[44px] leading-[1.08] font-normal tracking-tight md:text-[48px]">
              Relief that reaches <br />
              <span className="accent-serif">every lane</span>
            </h2>
            <p className="text-base leading-relaxed text-[#dce3e5]">
              Volunteers report deliveries and flooded roads in a short chat, in any language. Every route updates for every team.
            </p>
          </div>
        </div>
      </div>

      <section id="how" className="flex flex-col items-center gap-4 px-6 pb-28 md:px-20">
        <Bracket className="text-[#6e7273]">How it works</Bracket>
        <h2 className="text-center text-[44px] leading-[1.1] font-normal tracking-tight">
          Six agents, <br />
          <span className="accent-serif">one graph</span>
        </h2>
        <p className="max-w-[560px] text-center text-base leading-relaxed text-[#6e7273]">
          Agents never message each other. Each one claims a request with a lease, does one job, and writes the result back.
        </p>
        <ol className="w-full max-w-[760px] pt-10">
          {STEPS.map(([agent, verb, desc, flow], i) => {
            const left = i % 2 === 1;
            const card = (
              <div className={cn("flex flex-col gap-1.5 pt-1", left ? "items-end text-right" : "items-start")}>
                <span className="flex items-end gap-2">
                  <span className="text-xl font-medium tracking-tight">{agent}</span>
                  <span className="font-serif text-[21px] text-[#6e7273] italic">{verb}</span>
                </span>
                <p className="max-w-[300px] text-sm leading-relaxed text-[#6e7273]">{desc}</p>
                <span className="num text-[10px] tracking-wide text-[#9a978f] uppercase">{flow}</span>
              </div>
            );
            return (
              <li key={agent} className="grid h-[124px] grid-cols-[1fr_56px_1fr]">
                <div>{left && card}</div>
                <div className="relative flex justify-center">
                  <span className="absolute inset-y-0 w-px bg-slate/20" aria-hidden="true" />
                  <PlusIcon className="relative mt-1.5 size-3.5 bg-cream text-[#6e9fbf]" aria-hidden="true" />
                </div>
                <div>{!left && card}</div>
              </li>
            );
          })}
        </ol>
      </section>

      <div className="relative h-[600px] bg-slate bg-cover bg-center" style={{ backgroundImage: "url(/landing/floodplain.jpg)" }}>
        <div className="absolute inset-0" style={{ background: "linear-gradient(180deg, #141D2100 35%, #141D2199 75%, #141D21 100%)" }} aria-hidden="true" />
      </div>
      <section id="memory" className="flex flex-col items-center gap-5 bg-slate px-6 pt-2 pb-28 text-white md:px-20">
        <h2 className="text-center text-[44px] leading-[1.1] font-normal tracking-tight">
          Grounded in <br />
          <span className="accent-serif">one shared memory</span>
        </h2>
        <p className="max-w-[640px] text-center text-base leading-relaxed text-[#aeb8bc]">
          FalkorDB holds every message, request, team and lesson. Each organisation keeps its own graph. Roads, landmarks and shelters live in
          one shared region graph.
        </p>
        <div className="grid w-full pt-14 md:grid-cols-4">
          {[
            ["Leases, not luck", "If an agent dies mid-shift, its lease expires and another copy takes the item."],
            ["Ask why", "Every step records its reason as an edge, so any decision can be explained."],
            ["Offline first", "With no model key, rule-based agents read, merge and route the same way."],
            ["Real streets", "Roads come from OpenStreetMap, so routes follow the lanes people really use."],
          ].map(([h, d], i) => (
            <div key={h} className={cn("flex flex-col items-center gap-2.5 px-7 py-3 text-center md:border-l md:border-white/15", i === 3 && "md:border-r")}>
              <h3 className="text-base font-medium">{h}</h3>
              <p className="text-[13px] leading-relaxed text-[#8f9a9f]">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="flex flex-col items-center gap-5 px-6 pt-28 pb-10 md:px-20">
        <Bracket className="text-[#6e7273]">Inside the graph</Bracket>
        <H2 sans="Every answer is" serif="a path you can read" />
        <p className="max-w-[620px] text-center text-base leading-relaxed text-[#6e7273]">
          When a coordinator asks why, ReliefNet does not guess. It walks the household’s edges in FalkorDB and reads back each agent’s own
          reason.
        </p>
        <div className="grid w-full max-w-[1180px] gap-6 pt-10 lg:grid-cols-[1fr_520px]">
          <div className="flex flex-col gap-3 rounded-[20px] border border-slate/10 bg-white p-5">
            <div className="flex justify-between">
              <Bracket className="font-medium">R. Ram · F-201</Bracket>
              <span className="num text-[11px] text-[#6e7273]">10 nodes · 9 edges</span>
            </div>
            <div className="mx-auto w-full max-w-[520px] [&_svg]:bg-[#efece5]">
              <PathGraph trace={DEMO_TRACE} labels />
            </div>
            <p className="font-serif text-base leading-relaxed text-ink-soft italic">
              Two messages, one household. Dedupe merged R-111 into R-101 with score 1.0, so only one team went.
            </p>
          </div>
          <div className="flex flex-col gap-4">
            <pre className="num overflow-x-auto rounded-2xl bg-slate px-5 py-4 text-[11px] leading-relaxed text-white">
              {`MATCH (r:Request)-[:FOR]->(:Family {id:'F-201'})
OPTIONAL MATCH (m:Message)-[:BECAME]->(r)
RETURN r.id, r.status, r.priority, m.id, m.text

MATCH (r:Request)-[p:PROCESSED_BY]->(a:Agent)
WHERE r.id IN $ids
RETURN r.id, a.name, p.at, p.action, p.reason`}
            </pre>
            <div className="grid grid-cols-2 overflow-hidden rounded-2xl border border-slate/10 bg-white">
              {[
                ["75", "nodes"],
                ["254", "edges"],
                ["91", "agent reasons"],
                ["3", "duplicate requests merged"],
              ].map(([n, l], i) => (
                <div key={l} className={cn("flex flex-col gap-0.5 px-5 py-4", i % 2 && "border-l border-slate/10", i > 1 && "border-t border-slate/10")}>
                  <span className="font-display text-[40px] leading-tight font-semibold tracking-tight">{n}</span>
                  <span className="text-[13px] text-[#6e7273]">{l}</span>
                </div>
              ))}
            </div>
            <Bracket className="text-[10px] text-[#6e7273]">From one demo shift in Patna</Bracket>
          </div>
        </div>
      </section>

      <section id="product" className="flex flex-col items-center gap-5 px-6 pt-28 md:px-10">
        <Bracket className="text-[#6e7273]">The product</Bracket>
        <H2 sans="The ops room," serif="explained" />
        <p className="max-w-[600px] text-center text-base leading-relaxed text-[#6e7273]">
          Coordinators see the pipeline, the flood and every team on one map. Click a household and ask why it is still waiting.
        </p>
        <div className="flex w-full items-end gap-6 pt-10">
          <img
            src="/landing/ops.jpg"
            alt="The ops room: the pipeline, the map of Rajendra Nagar and Kankarbagh, and the queue"
            className="min-w-0 flex-1 rounded-2xl border border-slate/10"
            loading="lazy"
          />
          <div className="hidden w-[154px] shrink-0 flex-col gap-6 md:flex">
            <img src="/landing/field.jpg" alt="The field app for volunteers" className="rounded-2xl border border-slate/10" loading="lazy" />
            <img src="/landing/help.jpg" alt="The public help form" className="rounded-2xl border border-slate/10" loading="lazy" />
          </div>
        </div>
        <div className="grid w-full max-w-[1080px] pt-12 md:grid-cols-3">
          {[
            ["Pipeline at a glance", "Five stations from New to Delivered. A station turns orange when work piles up."],
            ["Mark a road flooded", "Dispatch reroutes every team on that road, and the reason goes in the graph."],
            ["Ask why", "Plain questions, answered from the timeline, with the path of agents and teams."],
          ].map(([h, d], i) => (
            <div key={h} className={cn("flex flex-col items-center gap-3 px-8 py-2 text-center", i > 0 && "md:border-l md:border-slate/10")}>
              <span className="num text-xl text-[#b5b2ab]">[{"ABC"[i]}]</span>
              <h3 className="text-base font-medium">{h}</h3>
              <p className="text-sm leading-relaxed text-[#6e7273]">{d}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="px-6 py-28 md:px-10">
        <div className="flex flex-col items-center gap-5 rounded-[20px] bg-teal px-6 py-[88px] text-center text-white">
          <h2 className="text-[44px] leading-[1.1] font-normal tracking-tight md:text-[48px]">
            Ready when <span className="accent-serif">the water rises</span> next time?
          </h2>
          <p className="max-w-[540px] text-base leading-relaxed text-[#d3e0e5]">
            Start the full stack with one command. Then send a flood drill through real Patna streets. No model key needed.
          </p>
          <div className="flex flex-wrap justify-center gap-3 pt-2">
            <Pill to="/login">Open the ops room</Pill>
            <span className="num inline-flex h-10 items-center rounded-full border border-white/70 px-5 text-xs">docker compose up -d --build</span>
          </div>
        </div>
      </div>

      <footer className="flex flex-col items-center gap-10 bg-slate px-6 pt-12 pb-8 text-[#c9d3d6] md:px-10">
        <ul className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[13px]">
          {["Ops room", "Field app", "Help form", "Flood drill", "Ask why", "Telegram bot"].map((l, i) => (
            <li key={l} className="flex items-center gap-5">
              {i > 0 && <span className="size-1 rounded-full bg-[#6e7a7f]" aria-hidden="true" />}
              {l}
            </li>
          ))}
        </ul>
        <span className="font-display leading-[0.85] font-semibold tracking-[-0.04em] select-none" style={{ fontSize: "clamp(72px, 18.5vw, 262px)" }} aria-hidden="true">
          RELIEFNET
        </span>
        <div className="num flex w-full flex-wrap justify-between gap-2 text-[10px] text-[#6e7a7f]">
          <span>© 2026 ReliefNet · Open source · Photos: AI-generated illustrations and Unsplash</span>
          <span>Roads © OpenStreetMap contributors (ODbL)</span>
        </div>
      </footer>
    </div>
  );
}
