# Clerk setup: accounts, organisations and invitations

With `AUTH_MODE=clerk`, people sign in with Clerk accounts. Each Clerk **Organization** is one relief organisation in ReliefNet, with its own private FalkorDB graph.

## Does the free plan work?

Yes. The Clerk free (Hobby) plan covers a hackathon:

| Need | Free plan |
|---|---|
| Users | 50,000 monthly users |
| Organisations | 100 active organisations |
| Members per organisation | Up to 20 |
| Email invitations | Included |
| Custom roles (for example a "coordinator" role) | Not included. Needs the Enhanced B2B add-on. |
| Verified domains and auto-join | Not included. Needs the Enhanced B2B add-on. |

Check [clerk.com/pricing](https://clerk.com/pricing) for current limits.

On the free plan there are only two roles. ReliefNet maps them like this:

| Clerk role | ReliefNet role | What the person sees |
|---|---|---|
| **Admin** (`org:admin`) | Admin | Operations chart, member management, demo-data reset |
| **Member** (`org:member`) | Volunteer | Field app |

So on the free plan, **invite coordinators as Admin** and **volunteers as Member**. If you buy the add-on later, create a custom role with the key `coordinator`. ReliefNet then gives that role the operations chart without admin rights.

## 1. Create the Clerk application

1. Sign in to the [Clerk Dashboard](https://dashboard.clerk.com) and create an application.
2. Choose the sign-in methods, for example email and Google.
3. Open **Organizations settings** and turn Organizations **on**.
   Keep the membership mode **Membership required**, so every user works inside an organisation.

## 2. Put the keys in `.env`

In the Clerk Dashboard, open **API keys** and copy:

- the **Publishable key** (`pk_test_...`)
- the **Frontend API URL** (for example `https://your-app-12.clerk.accounts.dev`)

Then set these values in `.env` in the repository root:

```
AUTH_MODE=clerk
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_ISSUER=https://your-app-12.clerk.accounts.dev
CLERK_JWKS_URL=https://your-app-12.clerk.accounts.dev/.well-known/jwks.json
CLERK_AUTHORIZED_PARTIES=http://localhost:8080,http://localhost:5173
```

For `npm run dev`, also put `VITE_CLERK_PUBLISHABLE_KEY` in `frontend/.env`.

Rebuild, because the web image includes the publishable key:

```
docker compose -p reliefnet up -d --build
```

## 3. Create your organisation (first admin)

1. Open http://localhost:8080 and sign up.
2. Create your organisation, for example "Red Cross Ganga Nagar". You become its **Admin**.

ReliefNet creates the organisation's graph the first time you open it. The graph has no teams. Open **Teams** on the operations screen and add your first team.

## 4. Stop strangers from creating organisations

Do this **after** you created your own organisation.

In the Clerk Dashboard, open **Organizations settings** and turn **off** the setting that lets users create organizations. From now on, a new person can only join through an invitation. Without this step, anyone who signs up creates a separate, empty organisation.

## 5. Invite people from inside ReliefNet

1. Sign in as an Admin. The operations chart opens.
2. Click the **organisation menu** in the top bar, then **Manage organization**.
3. Open **Members** and click **Invite**.
4. Type one or more email addresses and choose the role:
   - **Admin** for coordinators
   - **Member** for volunteers
5. Send the invitations.

The invited person:

1. Receives an email from Clerk.
2. Signs in (or signs up) with **that** email address.
3. Accepts the invitation. ReliefNet then opens the operations chart for Admins, or the field app for Members.

A volunteer chooses their team the first time the field app opens.

## 6. Switch organisations

A person can belong to more than one organisation. Use the organisation menu in the top bar to switch. ReliefNet reloads and shows only that organisation's data.

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| A new user gets their own organisation instead of yours | Users can still create organisations. Do step 4, and invite them instead. |
| "select an organisation first" | The user is signed in but has not chosen or accepted an organisation. Accept the invitation, or pick an organisation in the menu. |
| "invalid session token" | `CLERK_ISSUER` or `CLERK_JWKS_URL` does not match the Clerk application. Copy them again from **API keys**. |
| "token was issued for another origin" | The app's address is missing from `CLERK_AUTHORIZED_PARTIES`. |
| The sign-in page asks for a publishable key | `VITE_CLERK_PUBLISHABLE_KEY` is missing at build time. Add it to `.env` and rebuild. |
| An invited coordinator only sees the field app | They were invited as Member. Change their role to Admin in **Manage organization > Members**. |
| You deleted an organisation in Clerk | Its graph stays in FalkorDB but is no longer used. |
