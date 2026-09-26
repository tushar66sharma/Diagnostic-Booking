# Deploying to Render

This guide deploys the API and its PostgreSQL database to [Render](https://render.com) using the Dockerfile in this repository.

There are two ways to do it:

- **Option A: Blueprint (recommended, about 5 minutes).** [`render.yaml`](../render.yaml) creates the database and the API together, and connects them for you.
- **Option B: Manual.** You create the database and the web service yourself in the dashboard.

> **About the free plans** (check [render.com/pricing](https://render.com/pricing) for the current terms):
> - A free web service **goes to sleep after about 15 minutes without traffic**. The next request wakes it, which takes up to a minute.
> - A free Postgres database **expires after a limited period** (30 days at the time of writing).
> - Free instances have **no shell access**. That's why this project can load its demo data at startup (`SEED_ON_START`).
>
> This is fine for sharing a demo with reviewers. Use paid plans for anything long-lived.

---

## What the app does when it starts on Render

The Dockerfile's start command runs these steps in order:

1. `alembic upgrade head` creates or updates the database tables.
2. If `SEED_ON_START=true`, `python -m app.seed` loads the demo centres and tests and creates the admin user. It is safe to run on every start: nothing gets duplicated.
3. `uvicorn` starts on the port Render provides in `$PORT`.

Some configuration is handled automatically:

- **Database URL.** Render gives a URL starting with `postgresql://`. The app converts it to the psycopg 3 driver form on its own, so you can paste the URL unchanged.
- **Client IP.** With `FORWARDED_ALLOW_IPS=*`, the app reads the real client IP from Render's proxy headers. Without it, every user would appear to come from the same address and would share one login rate limit.

---

## Prerequisites

1. **The code is on GitHub** (public or private):
   ```bash
   git remote add origin https://github.com/<username>/<repo>.git
   git push -u origin main
   ```
2. **You have a Render account.** Sign up at [dashboard.render.com](https://dashboard.render.com), preferably with GitHub, so Render can see your repositories.
3. **You have chosen an admin password** for the deployed site. The seeded admin is `admin@example.com`. On a public URL, do **not** use the default `Admin@12345`.

---

## Option A: Blueprint (recommended)

1. **Start the Blueprint.** In the Render dashboard, click **New → Blueprint**.
2. **Connect the repository.** Choose your GitHub repository, giving Render access to it if asked. Render reads `render.yaml` from the root of the repository.
3. **Review what will be created.** Render lists:
   - `eve-bookings-db`: PostgreSQL, free plan
   - `eve-bookings-api`: web service (Docker), free plan
4. **Enter the admin password.** Render asks for `SEED_ADMIN_PASSWORD`. Type the password you chose. `JWT_SECRET` and `WEBHOOK_SECRET` are generated automatically as random values.
5. **Deploy.** Click **Apply**.
   - Render creates the database first. Then it builds the Docker image, which takes a few minutes the first time, and starts the service.
6. **Wait until it's live.**
   - Open the `eve-bookings-api` service. When the status shows **Live**, the URL appears at the top, e.g. `https://eve-bookings-api.onrender.com`.
   - The service's **Logs** tab should show:
     ```
     Running upgrade  -> b5643dd1aa0f, initial schema
     Seed data loaded. Admin login: admin@example.com (password from SEED_ADMIN_PASSWORD)
     Uvicorn running on http://0.0.0.0:10000
     ```
7. Continue with [Verify the deployment](#verify-the-deployment).

---

## Option B: Manual setup

### 1. Create the database

1. Click **New → Postgres**.
2. Fill in:
   - Name: `eve-bookings-db`
   - Database: `eve_bookings`
   - User: `eve`
   - Region: whichever is closest to you. Remember it; the web service must use the **same** region.
   - Plan: **Free**
3. Click **Create Database** and wait until its status is **Available**.
4. On the database page, go to **Connections** and copy the **Internal Database URL**. It looks like `postgresql://eve:...@dpg-xxxx-a/eve_bookings`.

### 2. Create the web service

1. Click **New → Web Service**, and choose your GitHub repository.
2. Fill in:
   - Name: `eve-bookings-api`
   - Region: **the same region as the database**
   - Branch: `main`
   - Language / runtime: **Docker**. Render finds the `Dockerfile` in the repository root.
   - Instance type: **Free**
3. Under **Environment Variables**, add:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the Internal Database URL from step 1 |
   | `JWT_SECRET` | a long random string (see below) |
   | `WEBHOOK_SECRET` | another long random string |
   | `FORWARDED_ALLOW_IPS` | `*` |
   | `SEED_ON_START` | `true` |
   | `SEED_ADMIN_PASSWORD` | your admin password |

   To generate a random string:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
4. Under **Advanced**, set **Health Check Path** to `/health`.
5. Click **Create Web Service**. Render builds and starts the service. When the status is **Live**, continue below.

---

## Verify the deployment

In the commands below, replace `https://eve-bookings-api.onrender.com` with your own service URL. If the service was asleep, the first request can take up to a minute.

1. **Health check.** Opening `https://eve-bookings-api.onrender.com/health` should show:
   ```json
   {"status": "ok"}
   ```
   This confirms the API is running and connected to the database.

2. **Swagger UI.** Open `https://eve-bookings-api.onrender.com/docs`. All the endpoints should be listed.

3. **Try the main flow in Swagger.** It's the same as locally; see [API.md](API.md) for request bodies.
   1. `POST /auth/signup/`, then `POST /auth/login/`. Copy the `access_token` and paste it into **Authorize**.
   2. `GET /centres/` should return the 3 seeded centres.
   3. `POST /bookings/` with a future `appointment_at`, e.g. `2026-12-05T09:30:00+05:30`.
   4. `POST /payments/` with `{"booking_id": <id>, "simulate": "success"}`. The booking should become `CONFIRMED`.

4. **Admin login.** Log in as `admin@example.com` with your `SEED_ADMIN_PASSWORD`, then try `POST /centres/`.

5. **Webhook.** Webhooks must be signed with the service's `WEBHOOK_SECRET`.
   1. Copy the secret from **Service → Environment**.
   2. Create a payment with `"simulate": "pending"` and copy its `provider_ref`.
   3. Send the webhook from your computer, using the project's virtualenv:

   ```powershell
   # PowerShell
   $env:WEBHOOK_SECRET = "<value copied from Render>"
   python -m scripts.send_webhook <provider_ref> SUCCESS --event-id evt_1 --url https://eve-bookings-api.onrender.com
   ```
   ```bash
   # bash
   WEBHOOK_SECRET="<value copied from Render>" python -m scripts.send_webhook <provider_ref> SUCCESS \
     --event-id evt_1 --url https://eve-bookings-api.onrender.com
   ```

   The first run should return `"result": "applied"`. Running the same command again should return `"duplicate"`.

---

## Updating the deployment

- **Automatic deploys.** Every `git push` to `main` makes Render rebuild and redeploy the service. Migrations run automatically on start.
- **Manual deploy.** Use **Manual Deploy → Deploy latest commit** on the service page.
- **Changing an environment variable.** Save the change in the dashboard; Render restarts the service.

---

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Build fails at `pip install` | Check the build log. Usually a temporary network error; use **Manual Deploy → Clear build cache & deploy**. |
| `connection refused` or timeouts to the database in the logs | The web service and the database are in **different regions**, or you used the **External** URL. Use the **Internal Database URL**, in the same region. |
| `password authentication failed` | `DATABASE_URL` was copied incompletely. Copy it again from the database's **Connections** page. |
| Health check fails and the deploy is rolled back | Open the logs. A failing `alembic upgrade head` (wrong `DATABASE_URL`) is the usual cause. |
| First request takes about 50 seconds | Normal on the free plan: the service was asleep and is waking up. |
| Every login gets `429` quickly, for every user | `FORWARDED_ALLOW_IPS` is not set to `*`, so all users look like the same IP. |
| The admin login fails | The admin is created only on the **first** seed. Changing `SEED_ADMIN_PASSWORD` later doesn't update an existing admin. To reset it, recreate the database, or update the row through Render's **PSQL command** on the database page. |
| Webhook returns `401 Invalid webhook signature` | The `WEBHOOK_SECRET` on your computer doesn't match the one on Render. |
| The database disappeared after some weeks | Free Render Postgres databases expire. Create a new one and point `DATABASE_URL` at it; the app recreates the tables on start. |

---

## Environment variables reference

| Variable | Required on Render | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Postgres connection string (`postgresql://…` is accepted as is) |
| `JWT_SECRET` | yes | Key for signing JWTs. Keep it secret and long. |
| `WEBHOOK_SECRET` | yes | Shared secret for webhook HMAC signatures |
| `FORWARDED_ALLOW_IPS` | yes (`*`) | Trust Render's proxy headers, so rate limiting sees real client IPs |
| `SEED_ON_START` | optional | `true` loads the demo data on every start (idempotent) |
| `SEED_ADMIN_PASSWORD` | if seeding | Password for `admin@example.com`. Never printed in the logs. |
| `SEED_ADMIN_EMAIL` | optional | Change the seeded admin's email |
| `JWT_EXPIRE_MINUTES` | optional | Token lifetime (default 60) |
| `PAYMENT_SUCCESS_RATE` | optional | Chance a mock payment succeeds when `simulate` is omitted (default 0.8) |
| `LOGIN_RATE_LIMIT` | optional | Default `5/minute` |
| `LOG_LEVEL` | optional | Default `INFO` |
| `PORT` | set by Render | The app listens on it automatically |
