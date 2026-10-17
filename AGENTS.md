# AGENTS.md

Instructions for AI coding agents that work on this repository. For people, start with [README.md](README.md).

## The project

ReliefNet coordinates flood relief with a team of AI agents and one shared memory graph in FalkorDB. Help requests arrive as messy messages (Telegram, the web help form, coordinators). The agents read, merge, prioritise, dispatch and remember each request in the graph.

- `backend/`: Python 3.12, FastAPI, FalkorDB, LangChain and LangGraph.
- `frontend/`: React 18, TypeScript, Vite, deck.gl.
- The default area is Rajendra Nagar and Kankarbagh in Patna, with real roads from OpenStreetMap.

## Commands

Run the backend commands in `backend/` with the virtual environment active.

| Task | Command |
|---|---|
| Install the backend | `pip install -e ".[embed,dev]"` |
| Start FalkorDB | `docker run -d -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest` |
| Start the API | `uvicorn reliefnet.api:app --reload --port 8000` |
| Start the agents | `python -m reliefnet.workers` |
| Run all tests | `pytest` |
| Run one test file | `pytest tests/test_logic.py` |
| Check an area | `pytest tests/test_areas.py` |
| Download the roads of an area | `python -m reliefnet.areas.import_osm <area>` |
| Install the frontend (in `frontend/`) | `npm install` |
| Start the frontend | `npm run dev` |
| Type-check and build the frontend | `npm run build` |
| Start the full stack | `docker compose up -d --build` (repository root) |

The graph tests (`test_graph.py`, `test_field_agent.py`) need FalkorDB. They skip when FalkorDB is not reachable. A skipped graph test is not a passed graph test, so start FalkorDB before you change a graph query.

No model key is necessary for the tests. Without a key, ReliefNet uses its offline rule-based agents.

The frontend has no test runner and no linter. `npm run build` is the frontend check.

## Architecture rules

Do not break these rules. The demo and the tests depend on them.

1. **Agents never call other agents.** An agent watches one request status, claims one item with a lease, does one job, and writes the result. It moves the request to the next status in the same guarded query. See `backend/reliefnet/agents/base.py`.
2. **Write only while you hold the lease.** Every result write must check `claimed_by` and `lease_until`. If the lease is lost, the write must fail, and another copy takes the item. Do not add a write path that skips this check.
3. **Record the reason.** Every pipeline step adds a `PROCESSED_BY` edge with the agent's reason. The "Ask why" feature reads these edges.
4. **FalkorDB is the only memory.** Do not add a LangGraph checkpointer, a LangGraph store, LangChain memory classes or another database. LangChain only talks to the model. Each agent run starts fresh and writes what it learns to the graph.
5. **All model calls go through `llm.py`.** Do not import a provider SDK in an agent. Keep every model call provider-independent (`MODEL_FAST`, `MODEL_SMART`).
6. **Every model path has an offline path.** Intake has `parsing.py`, the Field agent has rule-based intents, and the Learner has `rule_lessons`. When you add a model call, add the rule-based result for the case with no key.
7. **Take the organisation from the verified identity.** The server reads the org from `auth.py`, never from the request body. Each organisation has its own graph (`org_<slug>`, from `org_graph_name`).
8. **The region graph is shared.** Roads, landmarks and shelters are in one `region` graph for all organisations. Families, requests, teams and lessons are in the organisation's graph.
9. **Roads come from OpenStreetMap, not Google.** Google's terms do not allow a copy of its roads in our database. Google Maps is only a base layer under our layers. Keep the OpenStreetMap credit (ODbL).

## Request statuses

| Agent | File | Moves |
|---|---|---|
| Intake | `agents/intake.py` | Message → `NEW` |
| Dedupe | `agents/dedupe.py` | `NEW` → `RESOLVED` or `MERGED` |
| Triage | `agents/triage.py` | `RESOLVED` → `TRIAGED` |
| Dispatch | `agents/dispatch.py` | `TRIAGED` → `ASSIGNED` |
| Field | `agents/field.py` | `ASSIGNED` → `DELIVERED` |
| Shift Coordinator | `agents/coordinator.py` | Periodic: briefings and "why" answers |
| Learner | `agents/learner.py` | Periodic: `Lesson` nodes from field evidence |

ID prefixes: `M-` message, `R-` request, `F-` family, `O-` observation, `RP-` road report.

## Where code goes

| Change | Place |
|---|---|
| A graph query that an agent uses | A named function in `memory.py` |
| A shared graph write (message, road report, delivery, observation) | `field_ops.py` |
| Road state and routing | `routing.py` |
| A graph node shape | `models.py` (Pydantic) |
| Fixed lists (needs, urgency, lesson kinds) | `domain.py` |
| A setting | `config.py`, and add it to `.env.example` and the settings table in `README.md` |
| The help-form conversation | `intake_flow.py`. It has no network and no database code, so a WhatsApp adapter can reuse it. Keep it that way. |
| Telegram only | `telegram_bot.py`. It translates taps and text into `intake_flow` events. |
| Location from a pin, a landmark or a ward | `geo.py` |
| Area data (landmarks, wards, shelters, team bases, drill) | `areas/<area>.py`. See [docs/AREAS.md](docs/AREAS.md). |
| A dashboard screen | `frontend/src/pages/`, `frontend/src/components/` |
| An API call from the frontend | `frontend/src/api.ts`, with types in `frontend/src/types.ts` |

Do not put Cypher in an agent file. Put it in `memory.py`, so all agent queries are in one place.

## Traps

- **A change to `AREA` erases data.** The next start rebuilds the region graph and every organisation's graph, because teams and routes point at junction IDs.
- **A change to the region seed or the road import has the same effect.** New junction IDs make the stored team bases and routes wrong.
- **Teams come only from the seed.** `seed.py` copies `TEAM_BASES` (or `DEFAULT_TEAMS`) into an organisation's graph once. No API creates or edits a team yet.
- **The phone number has two kinds.** `phone` with `phone_kind = "own"` can identify a household. `alt_phone` and a neighbour's number are only for contact. Never use them to match households.
- **Far pins.** A pin more than 8 km from the area is snapped into the area only when `DEMO_SNAP_PINS` allows it. By default that is only the fictional `ganga_nagar`. On a real area, such a pin is a real place outside the operation.
- **Demo timings.** `LEASE_MS=8000` and `DISPATCH_WORK_MS=2000` are short on purpose, for the crash demo. Do not treat them as production values.
- **Tests use the active area.** Road names and junctions in `test_graph.py` come from `AREA`. Do not write a Patna road name into a test that must run on every area.
- **Do not commit OSM download caches.** The importer's `--cache` file is local only.

## Code style

- Match the style of the file you change: names, idioms and comment density.
- Comment only non-obvious logic: the reason for a decision, a caveat or a workaround. Do not write comments that repeat the code or describe your edit.
- Every module starts with a short docstring that explains its job. Keep that pattern for new modules.
- Use type hints. Backend modules with logic start with `from __future__ import annotations`.
- Use Pydantic models for graph nodes and for structured model output.
- Async all the way: the API, the agents and the graph calls are `async`.

## Writing style

Write documentation, README text, docstrings and user-facing messages in ASD-STE100 Simplified Technical English:

- Use short sentences: 20 words or fewer for instructions, 25 words or fewer for descriptions.
- Write one instruction in each sentence, in the imperative.
- Use the active voice.
- Use one term for one thing. For example, the docs say "household" and "family" for the `Family` node, "team" for a `Team`, and "organisation" (British spelling) for a tenant.
- Keep code, identifiers and error messages as they are.

When you add a setting, a command or a feature, update the matching part of `README.md` or `docs/` in the same change.

## Git

- Write commit subjects as `<area>: <what changed>`, in lower case. Examples: `map: fix blank deck.gl layers`, `intake: help-form conversation engine and phone parser`.
- Do not commit or push unless the person you work for asks you to.
- Do not commit `.env`, keys or tokens. Use `.env.example` for new settings, with an empty value and a comment.
