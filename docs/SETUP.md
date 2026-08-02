# Setup guide

This guide is written for the specific reader who has never opened Google Cloud Console
before: you have a Fitbit Air paired to the **Google Health** app on your phone, and you
want the app on your own machine, showing your own data. It tells you exactly what to
click and what to type, and explains what each step is for so you're not following
instructions blindly.

You do not need to do most of this to see the app work. **Do step 2 first.**

## 1. Prerequisites

- **Docker Desktop**, installed and running. Everything else in this project runs inside
  containers — you do not need Python, Node, or PostgreSQL installed on your machine.
- A **Google Account** with the Fitbit Air paired to the **Google Health** app (not the
  old Fitbit app or Google Fit — Google Health is the current app that Fitbit devices
  sync into).
- Confirm the band has **synced recently**: open Google Health on your phone and check
  that today's steps/heart rate are showing there. Data only reaches Google's servers
  after your phone has synced with the band — if your phone hasn't opened Google Health
  in a few days, open it now and let it sync before continuing.

## 2. Try it first, without any Google credentials

This proves the whole stack works before you touch Google Cloud Console at all. It seeds
the database with synthetic (fake) data so every screen has something to show.

From the repository root:

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run python -m bioage.cli seed-demo
```

Then open **http://localhost:5173**. You should see a biological-age chart with roughly
a year of synthetic weekly points. Click around Profile and Connection too — everything
is fully functional except the "Connect Google Health" button, which needs step 3
onward.

When you're ready to leave the demo data behind, wipe it with `docker compose down -v`
(this deletes the database volume) before you seed your real profile in step 10.

## 3. Create a Google Cloud project

1. Go to **console.cloud.google.com**. Sign in with the same Google Account your Fitbit
   Air data lives in.
2. Click the **project picker** at the top of the page (it shows the current project
   name, or "Select a project" if there's none yet).
3. Click **New Project**.
4. Give it any name, e.g. `fitbit-air-bioage`. Leave the organization/location as
   default.
5. Click **Create**, and wait for the notification that the project was created, then
   select it from the project picker so it's your active project.

This project is just a container that Google uses to scope the API access and
credentials you're about to create — it doesn't cost anything for what this app does.

## 4. Enable the Google Health API

1. In the left sidebar (or the top search bar), go to **APIs & Services → Library**.
2. Search for **"Google Health API"**.
3. **This is easy to get wrong**: do not click "Google Fit API" or "Fitness API" — both
   appear in the same search results and are Google's older, deprecated wearables API.
   You want the one named exactly **Google Health API**.
4. Click into it, then click **Enable**.

This app talks to `https://health.googleapis.com/v4`, which is the Google Health API.
Nothing in this project uses the deprecated Fit API.

## 5. Configure the OAuth consent screen

This is the screen Google shows *you* when the app asks for permission to read your
health data. Since this is a personal project and not a published product, Google
requires you to explicitly allow your own account to use it.

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** as the user type (Internal is only available for Google Workspace
   organizations, which a personal Gmail account is not), then **Create**.
3. Fill in:
   - **App name**: anything, e.g. `Fitbit Air Bioage`.
   - **User support email**: your own email address.
   - **Developer contact information**: your own email address again.
4. Save and continue through the next screens without changing anything until you reach
   **Test users**.
5. Under **Test users**, click **Add users** and add **your own Google account's email
   address** — the same one paired with your Fitbit Air.

   **This step matters.** Because the app is unpublished, Google will refuse to complete
   the sign-in for any account not on this list, and the callback will come back with
   `access_denied`. Adding yourself here is what lets your own account through.
6. Save.

   **One consequence of staying in Testing worth knowing now, not when it bites:**
   Google expires refresh tokens issued by a **Testing**-status OAuth client after
   **7 days**, regardless of use. This app's scheduled and manual syncs both depend on
   that refresh token staying valid indefinitely, so on a Testing-status client, sync
   will start failing with an auth error about a week after you connect — see
   **"Sync stops working about a week after connecting"** in Troubleshooting below for
   the fix (reconnect, or move the app to **Production** status to remove the 7-day
   limit). Test users can stay on the app in Testing status indefinitely for everything
   *except* this refresh-token lifetime, so this is the one reason you might want to
   publish to Production even for a single-user personal tool.

## 6. Add the OAuth scopes

Still on the OAuth consent screen configuration, find **Data Access** (or **Scopes**,
depending on the current Console layout) and click **Add or Remove Scopes**. A panel
opens with a manual entry field — paste in each of these three scopes exactly as
written, one at a time, and add them:

```
https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly
https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly
https://www.googleapis.com/auth/googlehealth.sleep.readonly
```

These are read-only scopes: this app never writes anything back to Google Health. They
cover, respectively, heart rate/HRV/SpO2/temperature, steps/VO2max/active minutes, and
sleep. Click **Update**, then **Save and continue**.

## 7. Create the OAuth client

This is the actual credential pair the app uses to identify itself to Google.

1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. **Application type**: choose **Web application** (not "Desktop app" — the app runs a
   local web server to receive the callback, so it needs to be registered as a web
   client).
4. Give it any name, e.g. `bioage-local`.
5. Under **Authorized redirect URIs**, click **Add URI** and enter exactly:

   ```
   http://localhost:8000/api/auth/google/callback
   ```

   This must match **character for character** — including `http` (not `https`) and the
   port `8000`. Google rejects the callback with `redirect_uri_mismatch` if it doesn't
   match exactly what's registered here.
6. Click **Create**. A dialog shows your **Client ID** and **Client secret** — copy both
   somewhere safe (or just keep the tab open for the next step).

## 8. Fill in `.env`

Open the `.env` file you created in step 2 (in the repository root) and set:

```
GOOGLE_CLIENT_ID=<the Client ID from step 7>
GOOGLE_CLIENT_SECRET=<the Client secret from step 7>
```

Leave `OAUTH_REDIRECT_URI` as its default (`http://localhost:8000/api/auth/google/callback`)
— it must match what you entered in Cloud Console in step 7.

Then restart the backend so it picks up the new values:

```bash
docker compose restart backend
```

## 9. Connect and sync

1. Open **http://localhost:5173/connection**.
2. Click **Connect Google Health**. You'll be sent to Google's sign-in and consent
   screen.
3. Google will show a warning that **"Google hasn't verified this app."** This is
   expected — it's *your own* app, registered to *your own* project, and it's never been
   submitted for Google's public-app verification review (which is unnecessary for a
   single-user personal tool). Click **Advanced**, then **Go to (your app name)
   (unsafe)**, then approve the requested scopes.
4. You'll be redirected back to the Connection page showing "Connected to Google
   Health."
5. Click **Sync now**. This pulls your historical data (up to `BACKFILL_DAYS`, 90 days
   by default) from Google Health and computes weekly scores from whatever is there.

## 10. Enter your profile

Open **http://localhost:5173/profile** and fill in:

- **Sex** and **birthdate** — used directly by the age estimators.
- **Height** and **weight** — added as dated measurements.
- **Waist circumference** — also added as a dated measurement. **Measure this yourself
  with a tape measure, at the navel**, standing relaxed (not sucked in). Nothing on your
  wrist can measure this, and the non-exercise fitness-age equation (from NTNU) requires
  it as an input — without it, that estimator can't run.

Each measurement is dated, so if you re-measure your waist in six months, old weekly
scores keep using whatever value was current for them at the time — they don't silently
change.

## 11. Optional: automatic daily sync

By default the app only syncs when you click "Sync now." To have it pull new data
automatically every day, set in `.env`:

```
SYNC_SCHEDULE_ENABLED=true
```

(`SYNC_SCHEDULE_CRON` controls the time, `0 5 * * *` — 5am — by default.) Then:

```bash
docker compose restart backend
```

---

## Troubleshooting

**`503` from `/api/auth/google/start`**
`GOOGLE_CLIENT_ID` and/or `GOOGLE_CLIENT_SECRET` are not set in `.env`, or the backend
container hasn't picked up a recent change. Confirm both are filled in, then
`docker compose restart backend`.

**`access_denied` after approving on Google's consent screen**
Your Google account isn't in the OAuth consent screen's **Test users** list (step 5).
Add it there and try connecting again.

**`redirect_uri_mismatch`**
The redirect URI registered in Cloud Console (step 7) differs — even by a trailing
slash, `http` vs `https`, or the port — from `OAUTH_REDIRECT_URI` in `.env` (default
`http://localhost:8000/api/auth/google/callback`). Make the two match exactly.

**`403 insufficient scope`**
One of the three scopes wasn't actually added/saved on the consent screen (step 6), or
you approved an older consent before adding a scope. Revoke the app's access at
**myaccount.google.com/permissions** (find it in the list and remove access), then
reconnect from the Connection page — Google will re-prompt for consent with the current
scopes.

**Sync stops working about a week after connecting**
Cause: your OAuth client is in **Testing** publishing status (the default — see step 5),
and Google expires refresh tokens issued by a Testing-status client after **7 days**,
regardless of how often the app is used. This app's sync depends on that refresh token
staying valid, so this is the expected, not a rare, failure mode for a Testing-status
client. Symptom: sync (scheduled or manual) starts failing with an auth error roughly a
week after you completed the "Connect Google Health" flow — the client refresh loop in
`bioage/ingest/client.py` retries a `401` exactly once against a forced token refresh,
and that refresh itself fails once the refresh token is expired, so the sync report
shows an error rather than retrying forever. Fix, either of:
- **Reconnect**: go to the Connection page and click "Connect Google Health" again. This
  is a two-minute fix but you'll need to repeat it roughly weekly.
- **Publish the OAuth app to Production**: in Cloud Console, go to **APIs & Services →
  OAuth consent screen** and click **Publish App**. This removes the 7-day refresh-token
  expiry. Since this app requests read-only health scopes that Google classifies as
  sensitive, publishing may prompt a verification notice — for a single-user app not
  distributed to anyone else, you can leave it published-but-unverified; Google does not
  require verification to complete for your own account to keep using it, only the
  "unverified app" warning at sign-in (already covered in step 9) to reappear if you
  ever have to reconnect.

**"Google did not return a refresh token"**
Google only issues a refresh token on the *first* consent for a given app/account pair;
subsequent approvals (e.g. after you'd already connected once) don't include one, and
without it the app can't refresh its access after the short-lived token expires. Fix:
revoke the app's access at **myaccount.google.com/permissions**, then reconnect — that
forces Google to treat the next approval as a first consent and issue a fresh refresh
token.

**`daily-vo2-max` is empty in the coverage table**
This is expected, not an error. The Fitbit Air only derives VO2max from GPS-tracked
outdoor runs; without those, Google Health never populates this data type. The
Connection page's coverage table notes this directly.

**Few or no weekly points on the chart**
The first biological-age point needs roughly **14 days** of synced data in a rolling
window; weeks with 14–20 days are computed but flagged low-confidence in the API
response. If you just connected, sync again in a week or two once more history has
accumulated, and make sure your phone is syncing with the band regularly (step 1).

**`429` in the sync logs**
Google Health API rate limiting. The client already retries these automatically with
exponential backoff (honoring `Retry-After` when Google supplies it) — no action needed,
just let the sync finish; it isn't a failure.

**Dependencies changed but the backend still behaves like the old code**
The `backend` service bind-mounts `./backend` into the container but keeps `/app/.venv`
as a separate, *anonymous* Docker volume so your host filesystem doesn't need a Python
environment. That volume is **not** recreated by a normal `docker compose down` /
`docker compose up --build` cycle — it persists across it. If you (or a future update)
change `pyproject.toml` and the container still runs old dependencies, the stale volume
is why. Fix: `docker compose down -v` (this also wipes the Postgres data — reseed or
re-sync afterward) and rebuild.
