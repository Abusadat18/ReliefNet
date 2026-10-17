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
   TELEGRAM_DEFAULT_ORG=redcross
   ```

   `TELEGRAM_DEFAULT_ORG` is the slug of the organisation that receives help requests from the public. If you leave it out, requests go to the first organisation by slug.

5. Start the bot with the rest of the stack:

   ```
   docker compose -p reliefnet --profile telegram up -d --build
   ```

   This also restarts the API, so the field app can show a one-tap link to your bot.

To run the bot without Docker, use `python -m reliefnet.telegram_bot` in `backend/`.

The bot uses **long polling**: it asks Telegram for new messages itself. It needs no public URL and works on a laptop.

> **Caution:** Run only **one** bot process per token. If the Docker bot and a local `python -m reliefnet.telegram_bot` run at the same time, Telegram rejects one of them with a conflict error.

## 2. Use it as a member of the public

Send `/start`. The bot asks a few short questions and shows buttons, in English or Hindi:

| Question | Answer |
|---|---|
| Who needs help? | "Me / my family" or "Someone else" |
| Where? | Telegram's **Share my location** button, or choose a ward and a landmark, or type a description |
| Phone number | The family's own mobile number. Type it, or tap **Share my number**. Or tap "No phone / lost phone" and give a number that can reach them, such as a neighbour's. |
| How many people? | 1 to 5, or type a number |
| What do they need? | Tick everything that applies: evacuation, rescue, food, water, medicine, baby food, blankets, shelter |
| Anything from this list? | Elderly person, children, sick or disabled, water entering the house, trapped, life in danger |

At the end the bot shows a summary. Tap **Send**, and it replies with a reference number, for example "Your reference is M-1043". The request then goes through Intake, Dedupe, Triage and Dispatch like every other message.

Rules that keep the form from getting in the way of real help:

- Every question has **Skip**, and any text you type is accepted and kept as a note.
- A phone number that does not look valid gets one retry. After that it is kept as "unverified" and the form moves on.
- If someone stops answering, the form is **sent as it is after 10 minutes**, as long as it has a location or some text.
- Typing `start`, `hi` or `/start` in the middle of a form asks "Continue, or start a new one?". Nothing is lost by accident.
- If the person is reporting for someone else and is not a linked volunteer, the bot asks whether the number is the family's own or a neighbour's. A neighbour's number is kept only for contact. It never identifies a household.

**Plain text still works.** A message that does not start with `/start`, for example

> Hum 4 log hain, eidgah ke paas ward 13, khana chahiye

is accepted right away, and the reply suggests `/start` for faster help.

**Which organisation receives the request:** the one in `TELEGRAM_DEFAULT_ORG`. To send one chat to another organisation, send `/org <slug>` once, for example `/org redcross`.

**Location pins:** Ganga Nagar is a fictional town. A pin that is more than 8 km from the town (for example, a phone testing from another city) is moved to a random spot inside a ward, so the demo works from any phone. The request is marked `pin_snapped` with low location confidence, and Triage asks for a call back. Set `DEMO_SNAP_PINS=false` for a real town. Then such a pin is ignored and the ward and landmark are used.

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

### Report for a family

Send `/report`. The bot asks the same questions as for the public, but a linked volunteer is always reporting for someone else. Give the **family's** phone number, not your own. The request is marked as reported by a volunteer. If the family lost their phone, tap "No phone / lost phone" and choose the ward and landmark by hand.

## 4. Bot commands

| Command | Use |
|---|---|
| `/start` | Public: start the help form. Volunteers: show the help text. `/start <code>` also links a volunteer (the field app's link uses this). |
| `/report` | Fill in the help form for a family (volunteers). |
| `/cancel` | Stop the form you are filling in. |
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

- The phone number is stored on the request, but Dedupe does not use it yet. Households are still matched by meaning, distance, ward, landmark, name and makeup.
- If the person skips the needs question, Intake still assumes food and water.
- The bot has no check yet for "you already have an open request".
- The Hindi wording has not been reviewed by a native speaker.
- WhatsApp is not supported yet. The form logic (`intake_flow.py`) does not depend on Telegram, so a WhatsApp adapter can reuse it.
- There is no `/unlink` command. Linking again with a new code replaces the old link.
- A volunteer's team comes from their web account. A volunteer without a team gets no assignment alerts.
