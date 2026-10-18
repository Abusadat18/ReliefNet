# ReliefNet

ReliefNet is a team of AI agents that coordinate flood relief through one shared memory graph in FalkorDB.

During a flood, help requests arrive as messy messages from many channels. Volunteers cannot see who already got help. One family gets three teams, and the next street gets none. In ReliefNet, every request is read, merged, prioritised, dispatched and remembered in the graph. The agents never message each other. They read and write the same graph.

Built for Graph Hacks (WeMakeDevs × FalkorDB), Track 02: agent memory and coordination.

## Hackathon submission

| | |
|---|---|
| Event | Graph Hacks: Context for AI Agents (WeMakeDevs × FalkorDB), 15–18 October 2026 |
| Track | **Track 02: Agent Memory and Coordination** |
| Demo video | *(add the link)* |
| Live deployment | *(add the link, or use the [Quick start](#quick-start-docker): one `docker compose up -d --build`)* |
| Graph data model | [Graph data model](#graph-data-model) |
| Cypher and graph algorithms | [Key Cypher queries](#key-cypher-queries) |
| AI tools | See [AI tools used](#ai-tools-used) |
| Summary for language models | [llms.txt](llms.txt), also served by the web app at `/llms.txt` |

FalkorDB is the only memory and the only way the agents share state. No agent calls another agent. Each agent claims work in the graph, does one job and writes the result back with its reason.

How ReliefNet covers the Track 02 focus points:

| Track 02 focus | In ReliefNet | Where to look |
|---|---|---|
| Episodic memory | Every message, step and delivery is a node or an edge with a time and a reason (`BECAME`, `PROCESSED_BY`, `DUPLICATE_OF`, `HANDED_OFF`, `REROUTED`, `SERVED`). | Queue receipts, Live log, **Ask why** |
| Semantic memory | What is true now: households (`Family`), their `Need`s, teams, and the shared region graph of roads, landmarks, neighbourhoods and shelters. | The map, `memory.py`, `seed.py` |
| Procedural memory | The Learner writes `Lesson` nodes from field evidence (`DERIVED_FROM`). Triage and Dispatch use them, and each use is a `USED_LESSON` edge. Confidence changes as evidence comes in. | **Lessons** tab, `agents/learner.py` |
| Remember across sessions | The graph persists (append-only file). The next shift gets a briefing written from the graph. **Ask why** reads a household's full path. Field chat history is kept in FalkorDB. | **Shift handover**, `agents/coordinator.py` |
| Shared state and handoffs | An agent watches one request status, claims a request with a lease, and moves it to the next status in the same guarded write. That status change is the handoff. | `agents/base.py`, `memory.claim_next`, `memory.finish_step` |
| High-concurrency reads and writes | A claim is one atomic Cypher write on the node. 30 parallel claims never get the same request (`test_parallel_claims_never_overlap`). A crashed agent's lease expires, and another copy reclaims the work. | **Agents** tab, `tests/test_graph.py` |
| Separate memory per tenant | Each organisation has its own graph (`org_<slug>`) in one FalkorDB instance. The server takes the organisation from the verified sign-in, never from the request. | `auth.py`, `db.org_graph_name` |
| Show the path behind an answer | Every receipt, lesson and answer shows the edges and the Cypher behind it. The **Memory** layer draws a household's graph on the map. | Queue receipts, **Graph query** tab, **Memory** |

## Quick start (Docker)

1. Install Docker Desktop.
2. Optional: copy `.env.example` to `.env` and add a model key, for example `ANTHROPIC_API_KEY`. Without a key, ReliefNet uses its offline rule-based agents. See [Language models](#language-models) to use another provider.
3. Start the stack:

   ```sh
   docker compose up -d --build
   ```

4. Open http://localhost:8080. On the front page, click **Open the ops room**, then choose "Shift Coordinator" under Red Cross Patna.
5. Click **Flood drill**, then click **Start the drill**.

The first build takes some minutes, because it downloads the multilingual embedding model into the image.

The map shows real streets of Rajendra Nagar and Kankarbagh in Patna. To show a Google map under the layers, add `GOOGLE_MAPS_API_KEY` to `.env` (see [docs/GOOGLE_MAPS.md](docs/GOOGLE_MAPS.md)). For production, also add a vector Map ID as `GOOGLE_MAPS_MAP_ID`. Without a key, ReliefNet draws its own chart.

| Address | What it is |
|---|---|
| http://localhost:8080 | ReliefNet front page. Signed-in people go straight to their app. |
| http://localhost:8080/login | Sign-in, then the ops room (coordinators) or the field app (volunteers) |
| http://localhost:8080/help | Public help form (no sign-in) |
| http://localhost:8080/about | The front page, also for people who are signed in |
| http://localhost:8000/docs | API documentation |
| http://localhost:3000 | FalkorDB Browser, to look at the raw graphs |

To use the Telegram bot, add the token to `.env`, then run `docker compose --profile telegram up -d`.

To stop everything, run `docker compose down`. To also erase the graph data, run `docker compose down -v`.

## Local development (without Docker for the app)

You need Python 3.12, Node 20 or later, and a FalkorDB instance.

1. Start FalkorDB:

   ```sh
   docker run -d -p 6379:6379 -p 3000:3000 -e REDIS_ARGS="--appendonly yes" falkordb/falkordb:latest
   ```

2. Start the API (terminal 1):

   ```sh
   cd backend
   python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
   pip install -e ".[embed,dev]"
   uvicorn reliefnet.api:app --reload --port 8000
   ```

3. Start the agents (terminal 2, same folder and virtual environment):

   ```sh
   python -m reliefnet.workers
   ```

4. Start the web app (terminal 3):

   ```sh
   cd frontend
   npm install
   npm run dev
   ```

5. Open http://localhost:5173.

Run the tests with `pytest` in `backend/`. The graph tests need FalkorDB on the configured port. They skip when FalkorDB is not reachable.

## The demo, step by step

### What the flood drill does

The flood drill only **writes raw, messy messages** into the inbox, as real people would send them. Some households write twice, in different words. The drill does **not** structure, merge or route anything. The agents do all of that:

1. **Intake** reads each message and pulls out the facts.
2. **Dedupe** merges messages from the same household.
3. **Triage** scores the priority.
4. **Dispatch** picks a team and a route.

The drill can also simulate field teams. When "Simulate field teams delivering help" is on, the drill marks each assignment delivered after its ETA, so deliveries happen with nobody clicking. Turn this option off to deliver by hand from the field app.

### The seven demo moments

These steps follow the seven moments of the demo video.

1. **Messages pour in.** Click **Flood drill**, then **Start the drill**. Messy Hinglish and English messages arrive, and households appear on the chart.
2. **Duplicates merge.** The drill sends "pls help 5 ppl stuck near Shiv mandir ward 11 Kankarbagh…" and then "R. Kumar family, ward 11 near temple…". The Dedupe agent merges them into one household. Open the household to see the evidence (meaning, distance, ward, people count).
3. **A road floods.** About one minute into the drill, two field teams report Malahi Pakdi Road flooded. It is the main road south through Kankarbagh, and it was under water in 2019. One report marks the road "reported". The second report confirms it, the road turns magenta, and every affected route goes back to Dispatch for a detour through the side lanes. You can also click any road and mark it flooded yourself.
4. **An agent crashes.** Open the **Agents** tab and click **Stop** on a Dispatch agent while it is working. Its lease runs out after 8 seconds, and another Dispatch copy reclaims the request. The log shows "Dispatch-1 reclaimed R-… after Dispatch-2's lease expired". The **Shift status** card on the map counts "Reclaimed after a crash".
5. **Shift change.** Click **Shift handover**, then **Write a briefing now**. The Shift Coordinator also writes one automatically at each time in `SHIFT_TIMES`.
6. **Ask why.** Type "Why hasn't the Das family been served?" in the bar at the bottom of the chart. The answer follows the household's path through the graph, agent by agent, with the reasons each agent recorded.
7. **The numbers.** The **Shift status** card shows households reached, households sent two teams (always 0), duplicates merged, messages per minute, reclaims, reroutes and merge accuracy against the drill's ground truth. For a load test, open **Flood drill** and send 300 or more messages at once.

To show tenancy, sign in as the Sahyog Local NGO coordinator in a second browser. That organisation sees none of the Red Cross households, but it sees the same flooded roads.

## How it works

### How one message flows

The agents work like an assembly line, not one item at a time. Every stage runs at the same time: while Dispatch routes one request, Intake already reads the next message. Each stage only looks for items in its own status.

```
message arrives        M-1001  (raw text, status RAW)
  Intake          ->   R-101   (structured request, NEW)          M-1001 -[BECAME]-> R-101
  Dedupe          ->   F-201   (household, R-101 is RESOLVED)    R-101 -[FOR]-> F-201
                       or MERGED into an existing household       R-102 -[DUPLICATE_OF]-> R-101
  Triage          ->   R-101 TRIAGED, priority 75 with reasons
  Dispatch        ->   R-101 ASSIGNED to Team B, with a route     R-101 -[ASSIGNED_TO]-> Team B
  Field (volunteer)->  D-1 delivery, R-101 DELIVERED              Team B -[MADE]-> D-1 -[SERVED]-> F-201
```

Every step also adds a `PROCESSED_BY` edge with the agent's reason. The "Ask why" feature reads these edges back.

### IDs you will see

Every node has a short, readable ID. The live log and the queue show them.

| Prefix | Example | What it is | Created by |
|---|---|---|---|
| `M-` | `M-1001` | A raw **message**, exactly as it arrived | Flood drill, help form, Telegram, "Add message", field chat |
| `R-` | `R-101` | A structured **request**, extracted from one message | Intake agent |
| `F-` | `F-201` | A **family** (household). Several requests can point to one family. | Dedupe agent |
| `D-` | `D-1` | A **delivery** record | Field app, Telegram, or the drill's simulated teams |
| `O-` | `O-1` | A field **observation** (each volunteer chat message or photo) | Field agent, Telegram |
| `RP-` | `RP-1` | A **road report** (flooded or open) | Field agent, Intake, a coordinator |
| `B-` | `B-1` | A shift **briefing** | Shift Coordinator |

Example: two messages about the Kumar family arrive as `M-1001` and `M-1002`. Intake makes `R-101` and `R-102`. Dedupe links both to one family, `F-201`, and marks `R-102` as `MERGED`.

### The agents

Every request moves through five statuses. Each agent watches one status, does one job, writes the result into the graph, and moves the request forward.

| Agent | Moves | What it does | Uses |
|---|---|---|---|
| Intake | Message → `NEW` | Reads raw messages in any language mix. Extracts people, needs, location and urgency. Geocodes landmarks with the area's own gazetteer. | Fast model with structured output; rule-based Hinglish parser offline |
| Dedupe | `NEW` → `RESOLVED` or `MERGED` | Finds the same household in other words. Scores meaning, distance, ward, landmark, names and household makeup. Asks the smart model on close calls. | FalkorDB vector index; smart model |
| Triage | `RESOLVED` → `TRIAGED` | Scores priority with reasons (medical, elderly, children, water entering, waiting time). Lifts whole clusters of unserved households. | `algo.labelPropagation` community detection; area lessons |
| Dispatch | `TRIAGED` → `ASSIGNED` | Picks a team by supplies, route time, load and team lessons. Routes around flooded roads. Hands off to the team's field agent. | `algo.SPpaths` on the shared road graph; road lessons |
| Field | `ASSIGNED` → `DELIVERED` | Chat for volunteers on the web or Telegram. Records deliveries, road reports, new needs and observations. | Fast model with seven tools (LangChain agent on LangGraph); rule-based intents offline |
| Shift Coordinator | — | Writes handover briefings. Answers "why" questions from the household's path. | Path queries; smart model |
| Learner | — | Turns field evidence into typed lessons, for example "Malahi Pakdi Road floods after 4 pm". Lessons gain confidence with new evidence and decay without it. Triage and Dispatch use a lesson at 50% confidence or more. A coordinator can apply a weaker lesson or dismiss any lesson in the **Lessons** tab. | Smart model plus rules; procedural memory |

Several copies of an agent can run at once, in one process or on many machines. An agent claims an item with a lease in one atomic query, renews the lease while it works, and writes its result only while it still holds the lease. If an agent dies, its lease expires and another copy takes the item. No request is handled twice.

The default fleet (`python -m reliefnet.workers`) runs these copies:

| Agent | Copies | Names in the Agents tab |
|---|---|---|
| Intake | 2 | `Intake-1`, `Intake-2` |
| Dedupe | 1 | `Dedupe` |
| Triage | 1 | `Triage` |
| Dispatch | 4 | `Dispatch-1` to `Dispatch-4` |
| Learner | 1 (on a timer) | `Learner` |
| Shift Coordinator | 1 (on a timer) | `Coordinator` |

Dispatch has the most copies, because it is the slowest stage: it routes every team for every request. Several copies also make the crash demo possible. To change the counts, pass flags, for example `python -m reliefnet.workers --dispatch 6 --intake 3`.

```cypher
MATCH (r:Request {status:$status})
WHERE (r.claimed_by IS NULL OR r.lease_until < $now) AND coalesce(r.not_before, 0) <= $now
WITH r ORDER BY r.priority DESC, r.created_at ASC LIMIT 1
SET r.claimed_by = $me, r.lease_until = $now + $lease
RETURN r
```

### The memory

| Memory | Where it lives |
|---|---|
| Episodic: what happened | `Message`, `Delivery`, `Observation`, `Report` nodes with timestamps; `PROCESSED_BY`, `HANDED_OFF`, `REROUTED` edges with reasons |
| Semantic: what is true | `Family`, `Need`, `Team`, plus `Road`, `Landmark`, `Shelter` in the shared region graph |
| Procedural: what works | `Lesson` nodes with `DERIVED_FROM` evidence edges; `USED_LESSON` edges show where a lesson changed a decision |
| Coordination: who does what | Request status, leases, `ASSIGNED_TO`, `HANDED_OFF` |

Each organisation has its own graph (`org_<slug>`). Roads, landmarks and shelters live in one shared `region` graph, because a flooded road is flooded for everyone. A road becomes impassable after two different teams report it, or after one coordinator confirms it.

FalkorDB also holds the plain Redis data: the live event stream, counters and chat history. ReliefNet needs no other database.

### Demo data

The seed step (`seed.py`) creates demo data the first time ReliefNet starts:

- **The region graph:** Rajendra Nagar and Kankarbagh in Patna, with real roads from OpenStreetMap: about 2,350 junctions, 3,500 road pieces, 48 bridges and flyovers, the drains and the railway. On top of the roads, ReliefNet adds:
  - 41 hand-written landmarks with the names people type (for example "Nalanda Medical College Hospital", also called "nmch" or "sarkari aspatal");
  - about 220 more named places from OpenStreetMap (hospitals, temples, schools, parks, banks);
  - 16 wards (simple zones, not the official ward map);
  - 4 simulated shelters at real stadiums and schools.
- **Two demo organisations**, each with teams. Every team has a home base on the map (the black squares) and its own supplies:
  - Red Cross Patna: Team A, B, C and D.
  - Sahyog Local NGO: Team Alpha, Beta and Gamma.
- **One demo volunteer per demo team**, for example Asha Devi and Imran Khan. In `AUTH_MODE=dev` they appear on the sign-in screen.

A new organisation starts with no teams. The operations screen then shows "No teams yet. Add your first team." Requests wait in `TRIAGED` until a team is on duty.

Dispatch assigns work to a **team**, not to one person. Every volunteer in the team sees the assignment in the field app, and in Telegram if linked.

To test with your own messages instead of the drill:

1. Sign in as Org Admin, open **Flood drill**, and click **Erase this organisation's memory**. Do not start the drill.
2. Send messages through the help form (http://localhost:8080/help), **Add message**, or Telegram.
3. In a second browser, sign in as a volunteer and do the field work yourself, for example "done R-101, gave water".

### Teams

Open **Teams** on the operations screen to see each team's supplies, load, members and duty status.

- An admin adds a team: a name, its supplies, its capacity and a base (a landmark or a shelter). The base moves to the nearest road junction.
- An admin edits the supplies, the capacity or the base. The name of a team cannot change, because assignments, lessons and "why" answers use it.
- A coordinator or an admin puts a team off duty. Dispatch then gives the team's active assignments to other teams, and gives it no new requests.
- You cannot delete a team. Put it off duty instead, so its history stays.

| Endpoint | Role |
|---|---|
| `GET /api/ops/teams` | Any signed-in user |
| `POST /api/ops/teams` | Admin |
| `PATCH /api/ops/teams/{name}` | Admin |
| `POST /api/ops/teams/{name}/duty` | Coordinator or admin |

### Lessons

Open **Lessons** on the operations screen to see what the Learner found. Triage and Dispatch use a lesson when its confidence is 50% or more.

- Click **Apply now** to use a weaker lesson at once.
- Click **Dismiss** to stop Triage and Dispatch from using a lesson.
- Click **Clear** or **Restore** to give the decision back to the lesson's confidence.

The override is the `override` property of the `Lesson` node. The Learner still updates the confidence, and the Live log shows who changed the lesson.

`GET /api/ops/lessons` also returns `evidence_nodes` (the `DERIVED_FROM` evidence, with label and name) and `used_by` (the requests that used the lesson, newest first).

| Endpoint | Role |
|---|---|
| `GET /api/ops/lessons` | Coordinator or admin |
| `POST /api/ops/lessons/{key}/override` with `{"override": "on" \| "off" \| null}` | Coordinator or admin |

### Places and local names

Intake finds the place of a message from four clues: a landmark, a neighbourhood, a road and a ward number. It matches the names against the region graph, so the names on the map are the names that Intake knows. The names have these sources:

- **Hand-written landmarks** in `LANDMARKS` in the area file. They win over an OpenStreetMap place at the same spot.
- **Named places and neighbourhoods from OpenStreetMap** in `areas/<area>_places.json`, made by `python -m reliefnet.areas.import_osm <area> --places`. A neighbourhood keeps its outline when OpenStreetMap has one.
- **Real road names** from the road import. Names that the importer made, such as "Lane near Kali Mandir", are not clues.
- **Places and local names that coordinators add** in the dashboard (**Places**). ReliefNet keeps them per area in Redis, so they stay after a region rebuild. A local name can go on a landmark or on a neighbourhood.

The landmark gives the point. A named road near the landmark moves the point onto the road. The neighbourhood and the ward narrow the area and must agree. Each clue that agrees raises `geo_confidence`, and a clue that does not agree lowers it. The Request keeps the matched `neighbourhood` and `road`, and the Intake reason lists the clues, so **Ask why** can explain the location. See the scoring table in [docs/AREAS.md](docs/AREAS.md#location-clues-in-a-help-request).

The rule-based Intake and the model Intake use the same exact name match for neighbourhoods and roads, so the result is the same with no model key.

A new local name reaches Intake on the next message. Landmarks and neighbourhoods are in the shared region graph, so a name helps every organisation.

| Endpoint | Role |
|---|---|
| `GET /api/region/landmarks` (landmarks and neighbourhoods) | Coordinator or admin |
| `POST /api/region/landmarks` | Coordinator or admin |
| `POST /api/region/landmarks/{id}/aliases` (a landmark ID or a neighbourhood ID) | Coordinator or admin |

`GET /api/ops/region` returns `neighbourhoods` as a list of `{id, name, aliases, ward, lat, lon, polygon}`. `polygon` is a list of `[lat, lon]`, or `null` when OpenStreetMap has only a centre.

### Map and area

The `AREA` setting selects the place that the shared region graph describes:

- `patna` (default): real roads from OpenStreetMap, stored in `backend/reliefnet/areas/patna.json`.
- `ganga_nagar`: the original fictional grid town. It needs no downloaded data.

The road data comes from OpenStreetMap, not from Google, for two reasons:
- Google's terms do not allow you to copy Google's roads into your own database.
- Google's routing cannot avoid a road that you choose, such as a flooded one.

Dispatch routes with `algo.SPpaths` on the roads in FalkorDB. Routes follow the real shape of each road.

The dashboard draws the same layers in two ways:
- **Google Maps** under the layers, when `GOOGLE_MAPS_API_KEY` is set. It has a satellite view. A vector Map ID (`GOOGLE_MAPS_MAP_ID`) keeps the layers smooth when you zoom. See [docs/GOOGLE_MAPS.md](docs/GOOGLE_MAPS.md).
- **The built-in chart**, with no key or when Google refuses the key. It works offline.

The **Layers** button on the map shows or hides each ReliefNet layer, and each browser remembers the choice. With `GOOGLE_MAPS_MAP_ID_DETAILED` set, a **Clean / All** switch also selects the map style. Google's map labels are in English. An **EN / हिं** label switch is ready but hidden for now; set `LANG_SWITCH` to `true` in `frontend/src/components/GoogleMap.tsx` to show it.

The map shows no Google labels. ReliefNet draws the names of neighbourhoods, roads and landmarks from its own data, so a name on the map is a name that Intake can match. To turn off Google's labels, import `docs/google-map-style-no-labels.json` into the Map Style of `GOOGLE_MAPS_MAP_ID`. See [docs/GOOGLE_MAPS.md](docs/GOOGLE_MAPS.md).

The map keeps the operation area in focus. It dims the world outside the area and draws a line around it. Households that sit close together on the screen become one bubble with a count; click the bubble to zoom in. A household with priority 70 or more shows its score on a pill. Each team shows its name and its number of jobs. The route of the selected household is bold, and the other routes are faint.

The dashboard shows where each decision comes from in the graph:

- **Queue:** each row has a graph receipt, for example `ASSIGNED_TO · Team 2 North`. Click it to read the household's edges in time order, each with its recorded reason, for example `(R-111)-[:DUPLICATE_OF {score:1.0}]->(R-101)`.
- **Live log:** each event shows the edge that it wrote. The header counts the edges in the organisation's graph and the edges with a reason.
- **Agents:** a working agent shows its lease on the request node, with a bar that counts down. A stopped agent shows the `reclaimed` edge that another copy wrote.
- **Lessons:** **View evidence** shows the `Lesson` node, its `DERIVED_FROM` evidence and the requests that used it (`USED_LESSON`).
- **Ask why:** the **Graph query** tab shows the read-only Cypher behind the answer, the counts of each edge type and the read time.
- **Memory:** turn on **Memory** next to **Layers**, then click a household. The map dims the other layers and draws the household's messages, requests, Triage score, lessons and team around it. A card tells the same path in one sentence.

To add another real flood area, see [docs/AREAS.md](docs/AREAS.md).

### Sign-in and tenancy

- `AUTH_MODE=dev` shows a list of demo people on the sign-in screen. Use it for local demos only.
- `AUTH_MODE=clerk` uses Clerk accounts and Clerk Organizations. The active organisation selects the FalkorDB graph. The role selects the screens: `org:admin` is an admin, a custom `org:coordinator` role (paid add-on) is a coordinator, and any other member is a volunteer.

The server always takes the organisation from the verified identity, never from the request body.

The Clerk free plan works. On it, invite coordinators as **Admin** and volunteers as **Member**. Admins invite people from the organisation menu in the top bar (**Manage organization > Members**).

For the full setup, the free-plan limits, invitations and troubleshooting, see [docs/CLERK.md](docs/CLERK.md).

### Language models

ReliefNet does not depend on one model provider. All model calls go through `backend/reliefnet/llm.py`, which uses LangChain:

- Intake, Dedupe and the Learner use structured output (`with_structured_output`) with Pydantic classes.
- Briefings and "why" answers use plain text calls.
- The Field agent uses LangChain's `create_agent`, which runs on LangGraph. Its seven tools are plain Python functions with the `@tool` decorator.

To change provider, set `MODEL_FAST` and `MODEL_SMART` and the matching key:

| Provider | Example | Install |
|---|---|---|
| Anthropic (default) | `anthropic:claude-sonnet-5-5` | included |
| OpenAI | `openai:gpt-5-mini` | `pip install ".[openai]"` |
| Google | `google_genai:gemini-2.5-flash` | `pip install ".[google]"` |
| Ollama (local, free) | `ollama:llama3.1` | `pip install ".[ollama]"` |

The Docker image includes Anthropic, OpenAI and Ollama. The prompts were written for Claude, so smaller models can extract Hinglish less reliably.

**FalkorDB is the only memory.** LangChain and LangGraph only talk to the model. ReliefNet uses no LangGraph checkpointer, no LangGraph store and no LangChain memory classes. Each agent run starts fresh, and every fact it learns is written to the graph through the tools.

### Telegram

The Telegram bot has two kinds of users:

- **The public** sends `/start` and answers a few short questions with buttons: location, the family's phone number, how many people and what they need. Each finished form becomes an `M-` message, and the bot replies with its reference number. Plain text without `/start` is still accepted. Public requests go to the organisation in `TELEGRAM_DEFAULT_ORG`. Send `/org redcross` to choose another one for one chat.
- **Volunteers** link their account once. Then they chat with the Field agent (deliveries, road reports, photos, locations) and receive a message for each new assignment to their team.

To set it up:

1. Create a bot with @BotFather.
2. Put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME` in `.env`.
3. Start the bot with `python -m reliefnet.telegram_bot` or the Docker `telegram` profile.

The bot uses long polling, so it needs no public URL. A volunteer opens the field app, taps **Link Telegram**, and sends `/link CODE` to the bot. After that, the volunteer's messages go to the Field agent, and new assignments arrive in Telegram. Anyone else who writes to the bot creates a public help request.

For the full setup steps, commands and a two-phone test, see [docs/TELEGRAM.md](docs/TELEGRAM.md).

## Graph data model

ReliefNet uses one FalkorDB instance with two kinds of graph:

- `org_<slug>`: one graph for each organisation. It holds that organisation's households, requests, teams and lessons.
- `region`: one shared graph for the area. It holds the roads, landmarks, neighbourhoods, wards and shelters, because a flooded road is flooded for everyone.

### Organisation graph (`org_<slug>`)

| Node | Key properties |
|---|---|
| `Message` | `id` (`M-`), `text`, `channel`, `sender`, `received_at`, `status` |
| `Request` | `id` (`R-`), `status` (`NEW` → `RESOLVED` / `MERGED` → `TRIAGED` → `ASSIGNED` → `DELIVERED`), `priority`, `needs`, `people`, `ward`, `landmark`, `road`, `neighbourhood`, `lat`, `lon`, `embedding` (vector index), `claimed_by`, `lease_until` |
| `Family` | `id` (`F-`), `name`, `people`, `elderly`, `children`, `needs`, `status` (`UNSERVED` / `ASSIGNED` / `SERVED`) |
| `Need` | `name` (food, water, medicine, evacuation, …) |
| `Agent` | `name` (for example `Dispatch-2`), `kind` |
| `Team` | `name`, `supplies`, `capacity`, `base`, `status` |
| `Volunteer` | `id`, `name`, `role` |
| `Delivery` | `id` (`D-`), `items`, `notes`, `at` |
| `Observation`, `Report` | Field notes, photos and road reports (`O-`, `RP-`) |
| `Lesson` | `key`, `kind`, `text`, `confidence`, `seen`, `override` |
| `Briefing` | `id` (`B-`), `shift`, `text` |

| Edge | Meaning |
|---|---|
| `(Message)-[:BECAME]->(Request)` | Intake turned a message into a request. |
| `(Request)-[:FOR]->(Family)` | The request belongs to this household. |
| `(Request)-[:PROCESSED_BY {at, action, from, to, reason}]->(Agent)` | One pipeline step, with the agent's reason. |
| `(Request)-[:DUPLICATE_OF {score, evidence, reason, decided_by}]->(Request)` | Dedupe found the same household. |
| `(Request)-[:ASSIGNED_TO {eta_min, roads, active}]->(Team)` | Dispatch sent this team, on this route. |
| `(Request)-[:REROUTED {road, reason}]->(Team)` | A flooded road or an off-duty team sent the request back. |
| `(Agent)-[:HANDED_OFF {request, reason}]->(Agent)` | Dispatch handed a job to a team's Field agent. |
| `(Team)-[:MADE]->(Delivery)-[:SERVED]->(Family)` | A team delivered help. |
| `(Family)-[:NEEDS {open}]->(Need)` | What the household still needs. |
| `(Lesson)-[:DERIVED_FROM]->(Family \| Delivery \| Report)` | The evidence behind a lesson. |
| `(Request)-[:USED_LESSON {by}]->(Lesson)` | A lesson changed this decision. |
| `(Agent)-[:WORKS_FOR]->(Team)`, `(Volunteer)-[:MEMBER_OF]->(Team)` | Who belongs to which team. |
| `(Volunteer)-[:SAID]->(Observation)`, `(Volunteer)-[:REPORTED]->(Report)` | What volunteers reported from the field. |

### Region graph (`region`)

| Node or edge | Meaning |
|---|---|
| `(Junction)-[:ROAD {name, kind, length_m, cost, status, low_lying, geom}]->(Junction)` | The road network from OpenStreetMap, one edge in each direction. `cost` goes up when a road floods. |
| `Landmark` | `name`, `aliases` (local names), `ward`, `kind`, `source` (`hand`, `app`, `osm`) |
| `Neighbourhood` | `name`, `aliases`, `ward`, `polygon` |
| `Ward`, `Shelter` | Zones and shelters, with capacity and occupancy |

## Key Cypher queries

All agent queries are named functions in `backend/reliefnet/memory.py`. These are the ones the product depends on.

**Claim the next request with a lease** (`memory.claim_next`). One atomic write, so parallel agents never take the same request, and a request with an expired lease is free again:

```cypher
MATCH (r:Request {status:$status})
WHERE (r.claimed_by IS NULL OR r.lease_until < $now) AND coalesce(r.not_before, 0) <= $now
WITH r ORDER BY r.priority DESC LIMIT 1
WITH r, r.claimed_by AS prev
SET r.claimed_by = $me, r.lease_until = $now + $lease, r.attempts = coalesce(r.attempts, 0) + 1
RETURN properties(r) AS item, prev
```

**Finish a step only while holding the lease** (`memory.finish_step`). The handoff to the next agent and the reason are written in the same query. If the lease is lost, nothing is written:

```cypher
MATCH (r:Request {id:$id}) WHERE r.claimed_by = $me
SET r += $props, r.status = $next, r.claimed_by = NULL, r.lease_until = NULL, r.updated_at = $now
WITH r MERGE (a:Agent {name:$me}) ON CREATE SET a.kind = $kind
CREATE (r)-[:PROCESSED_BY {at:$now, action:$kind, from:$from, to:$next, reason:$reason}]->(a)
RETURN r.id AS id
```

**Find similar earlier requests** (`memory.similar_requests`). This uses the vector index on `Request.embedding`, then follows each request to its household:

```cypher
MATCH (me:Request {id:$id})
CALL db.idx.vector.queryNodes('Request', 'embedding', $k, me.embedding) YIELD node, score
WITH node, score WHERE node.id <> $id
MATCH (node)-[:FOR]->(f:Family)
RETURN node.id AS id, f.id AS family, 1.0 - score AS similarity
```

**Merge a duplicate into the household** (`memory.merge_into_family`, inside the guarded finish). It keeps the evidence on the edge:

```cypher
MATCH (f:Family {id:$fid}), (c:Request {id:$cid})
CREATE (r)-[:FOR]->(f)
CREATE (r)-[:DUPLICATE_OF {at:$now, score:$score, evidence:$ev, reason:$why, decided_by:$by}]->(c)
SET f.requests = f.requests + 1, f.needs = f.needs + [n IN r.needs WHERE NOT n IN f.needs]
```

**Route around flooded roads** (`routing.route`). This uses FalkorDB's shortest-path algorithm on the region graph:

```cypher
MATCH (a:Junction {id:$src}), (b:Junction {id:$dst})
CALL algo.SPpaths({sourceNode:a, targetNode:b, relTypes:['ROAD'], weightProp:'cost', pathCount:$k})
YIELD path, pathWeight
RETURN pathWeight AS weight, [r IN relationships(path) | r.name] AS names
```

**Lessons to act on** (`memory.active_lessons`). A coordinator's override wins over the confidence:

```cypher
MATCH (l:Lesson)
WHERE l.kind IN $kinds AND coalesce(l.override, '') <> 'off'
  AND (l.override = 'on' OR l.confidence >= $min)
RETURN properties(l) AS l
```

**A household's full path, for Ask why** (`memory.household_history`). It is read-only, and the **Graph query** tab shows it:

```cypher
MATCH (r:Request)-[:FOR]->(:Family {id:$id})
OPTIONAL MATCH (m:Message)-[:BECAME]->(r)
RETURN r.id, r.status, r.priority, m.id, m.text;

MATCH (r:Request)-[p:PROCESSED_BY]->(a:Agent) WHERE r.id IN $ids
RETURN r.id, a.name, p.at, p.action, p.reason
// and the same for DUPLICATE_OF, ASSIGNED_TO, HANDED_OFF, REROUTED, USED_LESSON, MADE → SERVED
```

To look at the live graph, open the FalkorDB Browser at http://localhost:3000. Select your organisation's graph, run a query, and run it again to see new writes. For example:

```cypher
MATCH (r:Request)-[:FOR]->(f:Family)
WHERE r.status <> 'MERGED' AND r.status <> 'DELIVERED'
OPTIONAL MATCH (r)-[a:ASSIGNED_TO {active:true}]->(t:Team)
OPTIONAL MATCH (r)-[p:PROCESSED_BY]->(ag:Agent)
RETURN r, f, a, t, p, ag
```

## AI tools used

We used Claude Code (Anthropic) as a coding assistant during the event. We used it for code, tests, the UI and the documentation. We designed the architecture, the graph model and the agent rules, and we reviewed and tested the result. We can explain every part of it.

## Configuration

All settings are environment variables. `.env.example` lists them with comments. The most important are:

| Variable | Default | Meaning |
|---|---|---|
| `MODEL_FAST` / `MODEL_SMART` | `anthropic:claude-haiku-5-5` / `anthropic:claude-sonnet-5-5` | Models for high-volume and reasoning work, as `provider:model` |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` | empty | Key for the provider you use. No key means offline rules. |
| `LLM_MODE` | `auto` | `auto`, `live` or `mock` |
| `EMBED_MODE` | `auto` | `fastembed` (multilingual MiniLM) or `hash` |
| `AUTH_MODE` | `dev` | `dev` or `clerk` |
| `AREA` | `patna` | The place on the map: `patna` or `ganga_nagar`. A change rebuilds the region and the org graphs. |
| `GOOGLE_MAPS_API_KEY` | empty | Shows a Google map under the layers. Without it, the built-in chart shows. |
| `GOOGLE_MAPS_MAP_ID` | empty | Vector Map ID for smooth layers. Without it, the map uses Google's test id `DEMO_MAP_ID`. |
| `GOOGLE_MAPS_MAP_ID_DETAILED` | empty | Optional second vector Map ID with Google's labels and places. It enables the **Clean / All** switch on the map. |
| `FIELD_SHOW_PHONE` | `false` | `true` shows a **Call** button on the next job in the field app. It calls the contact number, or else the household's own number. Phone numbers are personal data, so turn it on only when your organisation agrees. |
| `LEASE_MS` | `8000` | Lease length. Short for the demo. |
| `DISPATCH_WORK_MS` | `2000` | Simulated planning time, so you can stop an agent mid-job |
| `TELEGRAM_DEFAULT_ORG` | first by slug | Organisation that receives public Telegram requests |
| `DEMO_SNAP_PINS` | empty | Move a shared pin from far outside the area to a random spot inside it. Empty: only for the fictional `ganga_nagar`. |

## Repository layout

```
backend/reliefnet/
  api.py            HTTP API and live event stream
  workers.py        runs the agent fleet
  agents/           one file per agent; base.py has the lease runtime shared by all
  memory.py         every graph query the agents use, as named functions
  models.py         Pydantic models for graph nodes (Message, Request, Family, Lesson, Team)
  llm.py            all model calls (LangChain); provider-independent
  field_ops.py      shared graph writes: messages, road reports, deliveries, observations, teams
  gazetteer.py      landmark writes and the local names that coordinators add
  routing.py        road state and routing on the shared region graph
  parsing.py        the offline Hinglish message parser
  areas/            the places on the map: patna (real OSM roads), ganga_nagar (fictional), the OSM importer
  sim.py            flood drill and load test
  telegram_bot.py   Telegram bot: help form, field chat, assignment alerts
  intake_flow.py    the help-form conversation, the same for every channel (no network)
  phone.py          cleans up and masks phone numbers
  auth.py           dev sign-in and Clerk tokens; picks the org graph
  seed.py           creates the graphs, indexes and demo data
backend/tests/      logic tests, graph tests, agent and auth tests
frontend/src/       React app: front page, ops room, field app, help form (Tailwind CSS and shadcn/ui)
docs/               setup guides (Clerk, Telegram, Google Maps, areas)
docker-compose.yml  FalkorDB, API, workers, web, optional Telegram bot
```

## Where to change things

| You want to change | Go to |
|---|---|
| How a message is understood | `agents/intake.py` (model prompt and schema), `parsing.py` (offline rules) |
| When two requests count as one household | `score_pair` in `agents/dedupe.py`; thresholds `DEDUPE_AUTO_MERGE`, `DEDUPE_ASK_LLM` |
| How priority is scored | `score` in `agents/triage.py` |
| How a team is chosen | `consider` in `agents/dispatch.py` |
| What volunteers can do in chat | `tools()` in `agents/field.py` (each tool is a `@tool` function) |
| What lessons are learned | `rule_lessons` and the prompt in `agents/learner.py` |
| A graph query | `memory.py` (agents), `field_ops.py`, `routing.py`, `api.py` |
| The area, hand-written landmarks, wards, demo teams or drill story | `areas/patna.py` (see [docs/AREAS.md](docs/AREAS.md)) |
| The roads of an area | `python -m reliefnet.areas.import_osm patna` |
| The named places of an area | `python -m reliefnet.areas.import_osm patna --places` (writes `areas/patna_places.json`) |
| How OpenStreetMap places merge with `LANDMARKS`, and their automatic local names | `areas/places.py` |
| Team rules (name, supplies, capacity, base) | `field_ops.py`; the supply list is `SUPPLIES` in `domain.py` |
| The demo volunteers | `seed.py` |
| Model provider or model names | `.env`: `MODEL_FAST`, `MODEL_SMART` (see [Language models](#language-models)) |
| The dashboard | `frontend/src/pages/Ops.tsx` and `frontend/src/components/` |
| The front page | `frontend/src/pages/Landing.tsx`; its photos are in `frontend/public/landing/` |
| Colours, fonts and radius of the whole app | `frontend/src/index.css` (shadcn theme tokens, light and dark) |
| Colours of the map and the built-in chart | `frontend/src/map.css` |
| A shadcn/ui component | `frontend/src/components/ui/`. Add one with `npx shadcn@latest add <name>` in `frontend/`. |

## Useful commands

Run these in `backend/` with the virtual environment active.

| Command | What it does |
|---|---|
| `python -m reliefnet.seed --reset` | Erase the demo organisations (`DEFAULT_ORGS`) and the road state, then create the demo data again |
| `python -m reliefnet.workers --dispatch 6` | Run the agent fleet with six Dispatch copies |
| `python -m reliefnet.sim --org redcross --rate 30 --minutes 5` | Run the flood drill from the command line |
| `python -m reliefnet.sim --org redcross --burst 500` | Load test: send 500 messages at once |
| `pytest` | Run the tests (graph tests need FalkorDB) |

To look at the raw graphs, open the FalkorDB Browser at http://localhost:3000 and choose a graph, for example `org_redcross` or `region`.

## Known limits

- The roads, bridges, drains, landmark positions and named places are real (OpenStreetMap). The families, messages, demo teams and shelters are simulated. The wards are simple zones, not the official ward map.
- A flood report closes every piece of a road with that name. Long roads are not split into sections.
- The drill compresses time: simulated teams arrive in seconds, not minutes.
- In offline mode, the Dedupe agent keeps close calls separate, because a wrong merge can leave a family without help. The language model resolves those close calls.
- With the lightweight `EMBED_MODE=hash`, some true duplicates stay separate. Use the default `fastembed` mode for the demo.
- A team cannot be renamed or deleted. Put a team off duty to stop its work.
- A change to `AREA` or to the road junctions erases the teams that admins added, because team bases point at junction IDs.
- A coordinator can add a place or a local name, but cannot hide a wrong OpenStreetMap place or remove a local name yet.
- A team base and a new place come from a list or from coordinates, not from a click on the map.
- Public Telegram messages go to `TELEGRAM_DEFAULT_ORG` (or the first organisation by slug) unless the sender uses `/org`.
- The bot collects the family's phone number, but Dedupe does not match on it yet.
