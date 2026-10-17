# Telegram setup and use

ReliefNet's Telegram bot serves two kinds of users:

- **The public** writes to the bot to ask for help.
- **Volunteers** link their account once. Then they chat with the Field agent and receive new assignments.

The bot is in `backend/reliefnet/telegram_bot.py`. It only needs a bot token.

## 1. Set up the bot (one time)

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Choose a name and a username, for example `ReliefNetGangaBot`.
3. Copy the token that BotFather gives you (it looks like `123456:ABC-...`). Keep it secret.
4. Add both values to `.env` in the repository root:

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-...
   TELEGRAM_BOT_USERNAME=ReliefNetGangaBot
   ```

5. Start the bot with the rest of the stack:

   ```
   docker compose -p reliefnet --profile telegram up -d --build
   ```

   This also restarts the API, so the field app can show a one-tap link to your bot.

To run the bot without Docker, use `python -m reliefnet.telegram_bot` in `backend/`.

The bot uses **long polling**: it asks Telegram for new messages itself. It needs no public URL and works on a laptop.

> **Caution:** Run only **one** bot process per token. If the Docker bot and a local `python -m reliefnet.telegram_bot` run at the same time, Telegram rejects one of them with a conflict error.

## 2. Use it as a member of the public

Anyone can open the bot and write a help request, for example:

> Hum 4 log hain, eidgah ke paas ward 13, khana chahiye

The bot replies with a reference number, for example "Received. Your reference is M-1043". The message then goes through the same pipeline as every other message: Intake, Dedupe, Triage and Dispatch. It appears on the operations chart.

**Which organisation receives the request:** by default, the first organisation in alphabetical order of its slug. With the demo data, that is **Sahyog Local NGO** (`local_ngo`), not Red Cross. To send requests to another organisation, send `/org <slug>` once, for example `/org redcross`.

## 3. Use it as a volunteer

### Link your account (one time)

1. Sign in to the web app as a volunteer, for example Imran Khan in Team B.
2. Tap **Link Telegram** at the top of the field app.
3. Tap the link that the app shows. Or send the code to the bot yourself, for example `/link 482913`.
4. The bot confirms, for example: "Linked. You are Imran Khan in Team B".

The code works one time and expires after 15 minutes.

### What you can send

| You send | What happens |
|---|---|
| `tasks` or `/tasks` | You get your team's open assignments, highest priority first. |
| `done R-123 gave BP tablets and water` | The delivery is recorded. The household turns green on the chart. |
| `NH-12 bridge flooded` | A road report. A report from a second team confirms the flood and reroutes every affected team. |
| `7 people on a roof near the school, ward 10` | A new request from the field. |
| A photo, with or without a caption | It is saved as an observation, with the photo, for coordinators. |
| Your location (Telegram "share location") | It is saved as an observation with coordinates. |

Every message you send is also stored in the graph as an `Observation`. The Learner agent reads these to form lessons.

### Assignment alerts

When Dispatch assigns a request to your team, every linked volunteer in that team gets a message, for example:

> New assignment R-145: Das family, ward 14 Water Tank. 6 people, needs evacuation, medicine. ETA 9 min via Lane 3, School Road.

Work goes to a **team**, not to one person. All linked members of the team get the alert.

## 4. Bot commands

| Command | Use |
|---|---|
| `/start` | Show the help text. `/start <code>` also links a volunteer (the field app's link uses this). |
| `/help` | Show the help text. |
| `/link <code>` | Link your Telegram account to your volunteer account. |
| `/tasks` | Show your team's open assignments (volunteers only). |
| `/org <slug>` | Choose which organisation receives your help requests (public). |

## 5. Test with two Telegram accounts

Turn the flood drill off during this test, so only your own messages are on the chart.

1. **Phone A (public):** send `/org redcross`, then a help request.
2. **Dashboard:** watch the request get triaged and assigned to a team.
3. **Phone B (volunteer):** link as a volunteer in that team. Wait for the "New assignment" alert.
4. **Phone B:** reply `done R-... gave food`. The household turns green on the chart.
5. **Phone B:** send `NH-12 bridge flooded`. Then report it from a volunteer in a second team, or mark it flooded as the coordinator. Watch the routes change.

## 6. Current limits

- The default organisation for public messages is the first by slug. A `TELEGRAM_DEFAULT_ORG` setting does not exist yet.
- There is no `/unlink` command. Linking again with a new code replaces the old link.
- A volunteer's team comes from their web account. A volunteer without a team gets no assignment alerts.
