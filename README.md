# ReliefNet

ReliefNet is a team of AI agents that coordinate flood relief through one shared memory graph in FalkorDB.

During a flood, help requests arrive as messy messages from many channels. Volunteers cannot see who already got help. One family gets three teams, and the next street gets none. In ReliefNet, every request is read, merged, prioritised, dispatched and remembered in the graph. The agents never message each other. They read and write the same graph.

Built for Graph Hacks (WeMakeDevs × FalkorDB), Track 02: agent memory and coordination.

## Quick start (Docker)

1. Install Docker Desktop.
2. Optional: copy `.env.example` to `.env` and add your `ANTHROPIC_API_KEY`. Without a key, ReliefNet uses its offline rule-based agents.
3. Start the stack:

   ```sh
   docker compose up -d --build
   ```

4. Open http://localhost:8080 and choose "Shift Coordinator" under Red Cross Ganga Nagar.
5. Click **Flood drill**, then click **Start the drill**.

The first build takes some minutes, because it downloads the multilingual embedding model into the image.

| Address | What it is |
|---|---|
| http://localhost:8080 | ReliefNet web app (operations chart, field app, help form) |
| http://localhost:8080/help | Public help form (no sign-in) |
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

These steps follow the seven moments of the demo video.

1. **Messages pour in.** Click **Flood drill**, then **Start the drill**. Messy Hinglish and English messages arrive, and households appear on the chart.
2. **Duplicates merge.** The drill sends "pls help 5 ppl stuck near Shiv mandir ward 12…" and then "R. Kumar family, ward 12 near temple…". The Dedupe agent merges them into one household. Open the household to see the evidence (meaning, distance, ward, people count).
3. **A bridge floods.** About one minute into the drill, two field teams report NH-12 Bridge flooded. One report marks the bridge "reported". The second report confirms it, the bridge turns magenta, and every affected route goes back to Dispatch for a new route. You can also click any road and mark it flooded yourself.
4. **An agent crashes.** Open the **Agents** tab and click **Stop** on a Dispatch agent while it is working. Its lease runs out after 8 seconds, and another Dispatch copy reclaims the request. The log shows "Dispatch-1 reclaimed R-… after Dispatch-2's lease expired". The cartouche counts "Requests reclaimed after a crash".
5. **Shift change.** Click **Shift handover**, then **Write a briefing now**. The Shift Coordinator also writes one automatically at each time in `SHIFT_TIMES`.
6. **Ask why.** Type "Why hasn't the Das family been served?" in the bar at the bottom of the chart. The answer follows the household's path through the graph, agent by agent, with the reasons each agent recorded.
7. **The numbers.** The cartouche shows households reached, households sent two teams (always 0), duplicates merged, messages per minute, reclaims, reroutes and merge accuracy against the drill's ground truth. For a load test, open **Flood drill** and send 300 or more messages at once.

To show tenancy, sign in as the Sahyog Local NGO coordinator in a second browser. That organisation sees none of the Red Cross households, but it sees the same flooded roads.

## How it works

### The agents

Every request moves through five statuses. Each agent watches one status, does one job, writes the result into the graph, and moves the request forward.

| Agent | Moves | What it does | Uses |
|---|---|---|---|
| Intake | Message → `NEW` | Reads raw messages in any language mix. Extracts people, needs, location and urgency. Geocodes landmarks with the town's own gazetteer. | Claude Haiku with a strict JSON schema; rule-based Hinglish parser offline |
| Dedupe | `NEW` → `RESOLVED` or `MERGED` | Finds the same household in other words. Scores meaning, distance, ward, landmark, names and household makeup. Asks Claude on close calls. | FalkorDB vector index; Claude Sonnet |
| Triage | `RESOLVED` → `TRIAGED` | Scores priority with reasons (medical, elderly, children, water entering, waiting time). Lifts whole clusters of unserved households. | `algo.labelPropagation` community detection; area lessons |
| Dispatch | `TRIAGED` → `ASSIGNED` | Picks a team by supplies, route time, load and team lessons. Routes around flooded roads. Hands off to the team's field agent. | `algo.SPpaths` on the shared road graph; road lessons |
| Field | `ASSIGNED` → `DELIVERED` | Chat for volunteers on the web or Telegram. Records deliveries, road reports, new needs and observations. | Claude Haiku with seven tools; rule-based intents offline |
| Shift Coordinator | — | Writes handover briefings. Answers "why" questions from the household's path. | Path queries; Claude Sonnet |
| Learner | — | Turns field evidence into typed lessons, for example "NH-12 Bridge floods after 4 pm". Lessons gain confidence with new evidence and decay without it. | Claude Sonnet plus rules; procedural memory |

Several copies of an agent can run at once, in one process or on many machines. An agent claims an item with a lease in one atomic query, renews the lease while it works, and writes its result only while it still holds the lease. If an agent dies, its lease expires and another copy takes the item. No request is handled twice.

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

### Sign-in and tenancy

- `AUTH_MODE=dev` shows a list of demo people on the sign-in screen. Use it for local demos only.
- `AUTH_MODE=clerk` uses Clerk accounts and Clerk Organizations. The active organisation's slug selects the FalkorDB graph. The role selects the screens: `org:admin` is an admin, a custom `org:coordinator` role is a coordinator, and any other member is a volunteer.

The server always takes the organisation from the verified identity, never from the request body.

To turn on Clerk:

1. Create a Clerk application and turn on Organizations.
2. Add a custom role with the key `org:coordinator`.
3. Put `CLERK_JWKS_URL`, `CLERK_ISSUER` and `AUTH_MODE=clerk` in `.env`.
4. Put `VITE_CLERK_PUBLISHABLE_KEY` in `.env` (for Docker) and in `frontend/.env` (for `npm run dev`).
5. Rebuild the web image.

### Telegram

1. Create a bot with @BotFather.
2. Put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME` in `.env`.
3. Start the bot with `python -m reliefnet.telegram_bot` or the Docker `telegram` profile.

The bot uses long polling, so it needs no public URL. A volunteer opens the field app, taps **Link Telegram**, and sends `/link CODE` to the bot. After that, the volunteer's messages go to the Field agent, and new assignments arrive in Telegram. Anyone else who writes to the bot creates a public help request.

## Configuration

All settings are environment variables. `.env.example` lists them with comments. The most important are:

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Claude key. Empty means offline rules. |
| `LLM_MODE` | `auto` | `auto`, `claude` or `mock` |
| `MODEL_FAST` / `MODEL_SMART` | `claude-haiku-5-5` / `claude-sonnet-5-5` | Models for high-volume and reasoning work |
| `EMBED_MODE` | `auto` | `fastembed` (multilingual MiniLM) or `hash` |
| `AUTH_MODE` | `dev` | `dev` or `clerk` |
| `LEASE_MS` | `8000` | Lease length. Short for the demo. |
| `DISPATCH_WORK_MS` | `2000` | Simulated planning time, so you can stop an agent mid-job |

## Repository layout

```
backend/reliefnet/
  api.py            HTTP API and live event stream
  workers.py        runs the agent fleet
  agents/           intake, dedupe, triage, dispatch, field, coordinator, learner, base (leases)
  field_ops.py      shared graph writes: messages, road reports, deliveries
  routing.py        road state and routing on the shared region graph
  region_data.py    the fictional town of Ganga Nagar
  sim.py            flood drill and load test
  telegram_bot.py   Telegram field bot
  seed.py           creates the graphs and indexes
backend/tests/      logic tests and graph tests
frontend/src/       React app: operations chart, field app, help form
docker-compose.yml  FalkorDB, API, workers, web, optional Telegram bot
```

## Known limits

- Ganga Nagar is a fictional town. All sample data is illustrative.
- The drill compresses time: simulated teams arrive in seconds, not minutes.
- In offline mode, the Dedupe agent keeps close calls separate, because a wrong merge can leave a family without help. Claude resolves those close calls.
