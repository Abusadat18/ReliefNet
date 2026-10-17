"""Flood simulator: messy messages in, simulated field teams out.

Every simulated household has a ground-truth id (`sim_household`) carried on
its messages, so the dashboard can score the Dedupe agent's accuracy.

    python -m reliefnet.sim --org redcross --rate 30 --minutes 5
    python -m reliefnet.sim --org redcross --burst 500      # load test
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
from dataclasses import dataclass, field

from . import areas, db, events, field_ops, orgs
from .db import now_ms, org_graph_name, query

log = logging.getLogger(__name__)

SURNAMES = ["Yadav", "Paswan", "Ansari", "Singh", "Khatoon", "Mahto", "Ram", "Sharma", "Prasad",
            "Mandal", "Sahni", "Manjhi", "Devi", "Choudhary", "Rajak", "Thakur", "Alam", "Mishra"]
FIRST = ["Ramesh", "Suresh", "Sunita", "Rekha", "Mohammad", "Salma", "Vijay", "Anil", "Pooja", "Raju", "Geeta",
         "Shankar", "Bablu", "Rani", "Imran", "Kavita", "Santosh", "Meena", "Arjun", "Farida"]
CHANNELS = ["whatsapp", "whatsapp", "whatsapp", "phone", "phone", "social", "telegram", "sms"]


@dataclass
class Household:
    hid: str
    first: str
    surname: str
    ward: int
    landmark: str
    alias: str
    people: int
    elderly: int
    kids: int
    pregnant: bool
    medical: str
    water_in: bool
    roof: bool
    needs: list[str] = field(default_factory=list)


def make_households(n: int, seed: int) -> list[Household]:
    rng = random.Random(seed)
    by_ward: dict[int, list[tuple[str, list[str]]]] = {}
    for lm in areas.region().landmarks:
        by_ward.setdefault(lm["ward"], []).append((lm["name"], lm["aliases"]))
    wards = sorted(by_ward)
    hot = [w for w in areas.drill().hotspot_wards if w in by_ward]
    out = []
    for i in range(n):
        # The worst-hit wards send most of the requests.
        ward = rng.choice(hot * 3 + wards)
        lm, aliases = rng.choice(by_ward.get(ward, [("", [])]))
        kids = rng.choice([0, 0, 1, 2, 3, 4])
        elderly = rng.choice([0, 0, 0, 1, 1, 2])
        people = max(1 + kids + elderly, rng.randint(2, 8))
        medical = rng.choice(["", "", "", "BP", "sugar", "asthma", "fever"])
        water_in = rng.random() < 0.45
        roof = rng.random() < 0.2
        needs = rng.sample(["food", "water", "food", "water", "blankets", "baby_food"], k=rng.randint(1, 2))
        if medical:
            needs.append("medicine")
        if water_in or roof:
            needs.append("evacuation")
        out.append(Household(
            hid=f"H{i:03d}", first=rng.choice(FIRST), surname=rng.choice(SURNAMES), ward=ward, landmark=lm,
            alias=rng.choice(aliases) if aliases else lm.lower(), people=people, elderly=elderly, kids=kids,
            pregnant=rng.random() < 0.06, medical=medical, water_in=water_in, roof=roof, needs=sorted(set(needs)),
        ))
    return out


def message_variants(h: Household, rng: random.Random) -> list[str]:
    elder = {0: "", 1: rng.choice(["dadi", "nana", "an old man", "buzurg amma"]), 2: "dadi aur dada"}.get(h.elderly, "")
    need_hi = {"food": "khana", "water": "peene ka paani", "medicine": f"{h.medical or 'BP'} ki dawai",
               "blankets": "kambal", "baby_food": "bachche ke liye doodh", "evacuation": "boat"}
    need_en = {"food": "food", "water": "drinking water", "medicine": f"{h.medical or 'BP'} medicine",
               "blankets": "blankets", "baby_food": "baby milk", "evacuation": "evacuation"}
    hi = " aur ".join(need_hi[n] for n in h.needs if n in need_hi)
    en = ", ".join(need_en[n] for n in h.needs if n in need_en)
    place_hi = f"{h.alias} ke paas ward {h.ward}" if h.alias else f"ward {h.ward}"
    place_en = f"near {h.landmark} ward {h.ward}" if h.landmark else f"ward {h.ward}"
    water = " paani ghar mein aa raha hai." if h.water_in else ""
    roof = " hum chhat pe fanse hain." if h.roof else ""
    kids = f" {h.kids} bachche bhi hain." if h.kids else ""
    preg = " ek pregnant mahila hai." if h.pregnant else ""
    opts = [
        f"pls help {h.people} ppl stuck {place_en}, {elder + ' needs ' + (h.medical or 'BP') + ' medicine,' if elder and h.medical else ''} {hi} chahiye.{water}",
        f"{h.first[0]}. {h.surname} family, {place_en}, {h.people} people.{' Water entering house.' if h.water_in else ''} Need {en}.",
        f"Mera naam {h.first} {h.surname} hai, {place_hi}, hum {h.people} log hain.{roof}{kids}{preg} {hi} chahiye.{water}",
        f"{h.surname} parivar {place_hi}. {h.people} log, {elder or 'koi buzurg nahi'}.{water} madad bhejo",
        f"URGENT {place_en}: family of {h.people} ({h.kids} kids{', ' + str(h.elderly) + ' elderly' if h.elderly else ''}). {en} needed.{' Pregnant woman inside.' if h.pregnant else ''}",
        f"Calling for my relatives {h.first} {h.surname}, {place_en}. {h.people} members. nobody has come since morning. need {en}",
    ]
    rng.shuffle(opts)
    return [" ".join(o.split()) for o in opts]


@dataclass
class SimState:
    org: str
    running: bool = False
    sent: int = 0
    started_at: int = 0
    rate_per_min: float = 20.0
    auto_field: bool = True
    scenario: str = "demo"
    task: asyncio.Task | None = None
    field_task: asyncio.Task | None = None
    log: list[str] = field(default_factory=list)


_sims: dict[str, SimState] = {}


def demo_script() -> list[tuple[int, str, tuple]]:
    """(seconds after start, kind, payload), in the area's own place names."""
    d = areas.drill()
    out = [(at, "msg", (ch, text, hid)) for at, ch, text, hid in d.messages]
    out += [(at, "road", (d.flood_road, team)) for at, team in zip(d.flood_at_s, d.flood_reporters)]
    return sorted(out, key=lambda x: x[0])


async def _send(st: SimState, channel: str, text: str, hid: str, backdate_min: float = 0) -> None:
    at = now_ms() - int(backdate_min * 60_000)
    await field_ops.ingest_message(st.org, text, channel, sender=f"sim:{hid}", received_at=at, sim_household=hid)
    st.sent += 1


async def _run(st: SimState, seed: int, households: int) -> None:
    rng = random.Random(seed)
    hs = make_households(households, seed)
    queue: list[tuple[str, str, str]] = []
    for h in hs:
        variants = message_variants(h, rng)
        copies = 1 if rng.random() < 0.6 else (2 if rng.random() < 0.75 else 3)
        for v in variants[:copies]:
            queue.append((rng.choice(CHANNELS), v, h.hid))
    rng.shuffle(queue)
    start = asyncio.get_running_loop().time()
    script = demo_script() if st.scenario == "demo" else []
    # A backlog of earlier messages makes waiting times and clusters visible at once.
    backlog = 12 if st.scenario == "demo" else 0
    for _ in range(min(backlog, len(queue))):
        ch, text, hid = queue.pop(0)
        await _send(st, ch, text, hid, backdate_min=rng.uniform(60, 360))
    next_msg = start
    try:
        while st.running and (queue or script):
            now = asyncio.get_running_loop().time()
            while script and now - start >= script[0][0]:
                _, kind, payload = script.pop(0)
                if kind == "msg":
                    await _send(st, payload[0], payload[1], payload[2])
                elif kind == "road":
                    res = await field_ops.report_road(st.org, payload[0], "flooded", reporter=f"sim:{payload[1]}",
                                                      team=payload[1], source_text=f"{payload[0]} flooded")
                    st.log.append(f"{payload[1]} reported {payload[0]} flooded -> {res.get('status')}")
            if queue and now >= next_msg:
                ch, text, hid = queue.pop(0)
                await _send(st, ch, text, hid)
                next_msg = now + rng.expovariate(st.rate_per_min / 60.0)
            await asyncio.sleep(0.2)
    finally:
        st.running = False


async def _field_loop(st: SimState, speed: float = 0.6) -> None:
    """Simulated teams deliver after ETA scaled to demo time (ETA minutes x speed seconds)."""
    rng = random.Random(1)
    g = org_graph_name(st.org)
    while st.auto_field:
        rows = await query(
            g,
            "MATCH (r:Request {status:'ASSIGNED'})-[a:ASSIGNED_TO {active:true}]->(t:Team)"
            " RETURN r.id AS id, r.needs AS needs, a.at AS at, a.eta_min AS eta, t.name AS team",
            readonly=True,
        )
        now = now_ms()
        for r in rows:
            due = r["at"] + int((r["eta"] or 10) * speed * 1000) + rng.randint(2000, 9000)
            if now >= due:
                vol = await query(
                    g, "MATCH (v:Volunteer)-[:MEMBER_OF]->(:Team {name:$t}) RETURN v.id AS id LIMIT 1",
                    {"t": r["team"]}, readonly=True,
                )
                await field_ops.mark_delivered(
                    st.org, r["id"], r["needs"] or ["help"], "simulated field delivery",
                    by=vol[0]["id"] if vol else f"sim:{r['team']}", team=r["team"],
                )
        await asyncio.sleep(1.5)


async def start(org: str, *, rate_per_min: float = 20, auto_field: bool = True, scenario: str = "demo",
                seed: int = 42, households: int = 60) -> SimState:
    st = _sims.get(org)
    if st and st.running:
        return st
    if st:
        await stop(org)
    st = SimState(org=org, running=True, started_at=now_ms(), rate_per_min=rate_per_min, auto_field=auto_field,
                  scenario=scenario)
    _sims[org] = st
    st.task = asyncio.create_task(_run(st, seed, households))
    if auto_field:
        st.field_task = asyncio.create_task(_field_loop(st))
    await events.publish(org, "sim", f"Flood simulator started ({scenario}, {rate_per_min:g} msg/min)")
    return st


async def stop(org: str) -> None:
    st = _sims.get(org)
    if not st:
        return
    st.running = False
    st.auto_field = False
    for t in (st.task, st.field_task):
        if t:
            t.cancel()
    await events.publish(org, "sim", "Flood simulator stopped")


def status(org: str) -> dict:
    st = _sims.get(org)
    if not st:
        return {"running": False, "sent": 0}
    return {"running": st.running, "sent": st.sent, "rate_per_min": st.rate_per_min, "scenario": st.scenario,
            "auto_field": st.auto_field, "started_at": st.started_at, "log": st.log[-10:]}


async def burst(org: str, count: int, seed: int = 7) -> dict:
    """Load test: send `count` messages as fast as the graph accepts them."""
    rng = random.Random(seed)
    hs = make_households(max(10, count // 2), seed)
    t0 = now_ms()
    sem = asyncio.Semaphore(32)

    async def one(i: int):
        h = hs[i % len(hs)]
        async with sem:
            await field_ops.ingest_message(org, rng.choice(message_variants(h, rng)), rng.choice(CHANNELS),
                                           sender=f"load:{h.hid}", sim_household=f"L{seed}-{h.hid}")

    await asyncio.gather(*(one(i) for i in range(count)))
    ms = now_ms() - t0
    await events.publish(org, "sim", f"Load burst: {count} messages ingested in {ms} ms")
    return {"count": count, "ms": ms, "per_min": round(count * 60_000 / max(ms, 1))}


async def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", default="redcross")
    ap.add_argument("--rate", type=float, default=20)
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--burst", type=int, default=0)
    ap.add_argument("--scenario", default="demo", choices=["demo", "flood"])
    ap.add_argument("--no-field", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not await orgs.get(args.org):
        raise SystemExit(f"unknown org {args.org}; run python -m reliefnet.seed first")
    if args.burst:
        print(await burst(args.org, args.burst))
    else:
        await start(args.org, rate_per_min=args.rate, auto_field=not args.no_field, scenario=args.scenario)
        await asyncio.sleep(args.minutes * 60)
        await stop(args.org)
    await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
