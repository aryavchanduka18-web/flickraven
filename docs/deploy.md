# Putting FlickRaven online with Render

This guide takes FlickRaven from your laptop to a public web address. You do every step yourself in
your browser and one terminal window. Nothing here costs money on the free plans, and nothing in the
repository contains a password or key.

## What gets hosted

| Piece | Where it runs on Render | Where it comes from |
|---|---|---|
| Website and API | One **web service** built from the `Dockerfile` | Your GitHub repository (`main` branch) |
| Database | One **PostgreSQL** database on **Neon** (not Render) | Created empty on Neon, URL pasted into Render |
| Film catalog (14,292 films, people, credits, keywords, awards) | Inside the database | Uploaded from your laptop (`catalog.dump`, about 14 MB) |
| Demo account (`demo@cinematch.local`, same password as on your laptop) | Inside the database | Uploaded from your laptop (`demo_user.json`) |
| Trained models and the Research Lab numbers | Inside the database, unpacked by the server at start | Uploaded from your laptop (`artifacts.tar.gz`, about 38 MB) |

Why the models travel through the database: the GitHub repository is public, and the models are built
from MovieLens ratings, which may not be redistributed. The database is private to your Render account,
so the models never become public.

Memory: with the same 512 MB limit as Render's free plan, the container peaked at about 380 MB while
serving the home page, film pages, search and the Research Lab (measured in Docker on the laptop). The
free plan fits. The database uses about 240 MB of the free plan's 1 GB.

## Before you start

- A Render account (you have one), signed in with GitHub so Render can see the repository.
- Docker Desktop running on the laptop (the upload uses it), and the local database started:
  `scripts\db.ps1 start`.
- All pull requests merged into `main` on GitHub. Render deploys `main`.

## Step 1: create the service and the database

1. Open <https://dashboard.render.com>, click **New**, then **Blueprint**.
2. Pick the `CINEMATCH` repository. Render finds `render.yaml` and shows the `cinematch` web service.
3. Render asks for two values: `DATABASE_URL` (the Neon URL, see "Database on Neon") and `WEB_ORIGIN`.
   Type `https://cinematch.onrender.com` for the second.
   (If Render gives the service a different address, change this value to that address in the
   service's **Environment** tab. The site works in the meantime.)
4. Click **Apply**. Render creates the database, builds the Docker image (about 5 to 10 minutes the
   first time), starts the service, and creates all the tables.
5. Wait until the web service shows **Live**. Open `https://<your address>/api/health`. You should see
   `{"status":"ok","db":"ok",...}`. The home page opens too, but has no films yet.

## Step 2: copy the catalog, demo account and models from the laptop

1. Copy the Neon URL (Neon project, **Connect**, pooling off). Treat it like a password: do not paste it into chats, files or GitHub.
2. In a terminal in the `cinematch` folder, make the three upload files:

   ```powershell
   .\.venv\Scripts\python.exe scripts\deploy_data.py export
   ```

   It prints the sizes, for example `catalog.dump 14.3 MB` and `artifacts.tar.gz 38.0 MB`. The files go
   to `deploy-out\`, which git ignores.
3. Upload them:

   ```powershell
   .\.venv\Scripts\python.exe scripts\deploy_data.py upload
   ```

   Paste the Neon URL when it asks (the text stays hidden). It takes a minute or two and
   prints `1/3 Catalog`, `2/3 Demo account`, `3/3 Model bundle`, then `Done`.
4. In Render, open the **cinematch** service, click **Manual Deploy**, then **Restart service**.
5. Open the site. The home page now shows the hero and the rails. The first visit after a restart can
   take about 10 seconds while the recommender loads.

The model bundle goes up in parts of 2 MB (`part 1/19 done` and so on); each part is saved on its own, so a
dropped connection only costs that part, and the script reconnects and carries on by itself. At the end it
checks the whole bundle against its checksum on the server.

Running `upload` again is always safe: it skips the catalog, the demo account and the bundle when they are
already there, and finishes a bundle upload that stopped half way.

## Updating the site later

- **Code changes**: merge into `main`, then in Render click **Manual Deploy > Deploy latest commit**. Auto-deploy is off on purpose (`autoDeploy: false`): on the free plan each build spends build minutes and each start spends Neon transfer. Batch several merges into one deploy. If the service was created before this change, also turn **Settings > Build & Deploy > Auto-Deploy** to **Off** in the Render dashboard.
  Database changes (Alembic migrations) run automatically when the new version starts.
- **New models**: run the pipeline on the laptop, then `deploy_data.py export` and `upload` again, then
  **Restart service**.
- **New films or catalog changes** (for example the franchise update, which added 470 films and the
  franchise names): run `export`, then

  ```powershell
  .\.venv\Scripts\python.exe scripts\deploy_data.py upload --refresh-catalog
  ```

  It updates every film by its TMDB id and adds the new ones. Nothing is deleted, so accounts, ratings and
  lists made on the site stay as they are. It also uploads the new model bundle. Then **Restart service**.

## Every month (about 30 minutes; the first full run after the series and wider-catalog update takes 1 to 2 hours)

1. Start Docker Desktop (wait until it says it is running; if it will not start, rename
   `%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` and start it again), then run
   `powershell -ExecutionPolicy Bypass -File .\scripts\db.ps1` in the `cinematch` folder.
2. Run `powershell -ExecutionPolicy Bypass -File .\scripts\monthly_refresh.ps1` (the `-ExecutionPolicy Bypass` part is
   needed on a laptop where running scripts is disabled; keep the laptop awake). It backs up the live database, finds films released in the last six
   months on TMDB (English and every catalog language), adds the ones that pass the metadata gate as
   "new & notable" films, rebuilds the catalog and the model bundle, and uploads them. Accounts and ratings
   on the site are not touched. The new films have no MovieLens ratings, so the models and the evaluation
   results stay the same; new films are recommended through "similar to" (content) scores. Steps: 1 new releases,
   1b wider catalog, 1c series and anime, 2 rebuild, 3 load, 3b where to watch, 3c IMDb ratings, 4 content features,
   5 export, 6 upload. TMDB answers are cached on the laptop, so a stopped run resumes where it left off, and a
   title TMDB refuses is skipped and asked for again next month.
3. In Render: **flickraven** service, **Manual Deploy**, **Restart service**.

If you skip a month nothing breaks; the catalog just stops getting newer.

**Optional: retrain with the ratings made on the site.** After the refresh, run
`powershell -ExecutionPolicy Bypass -File .\scripts\retrain_with_feedback.ps1` (20 to 40 minutes, no Docker needed).
It copies the site's ratings out of Neon (read only), retrains with them added to training, measures again on the same
MovieLens test ratings and prints either "Safe to ship" or "Keep the old models" (and how to go back). It never uploads.
Until many people use the site, expect "no measurable change"; that is the honest result, not a failure.

The refresh also updates **Where to watch** on film pages (step 3b): TMDB's list of streaming, rental and
purchase services for each film, data by JustWatch. India is shown; a film with nothing listed in India
shows the US instead, and a film with nothing in either says so. Only links out; the page credits JustWatch.

## Model bundle outside the database (saves Neon transfer)

Every start of the free web service unpacks the model bundle (`artifacts.tar.gz`, about 52 MB). By default
it comes from the database, and Neon's free plan allows only 5 GB of transfer a month. About 100 starts
(deploys, restarts, wake-ups) used it all in November 2026 and Neon suspended the database until Dec 1.

So keep the bundle on a free file host and let the server download it from there. The database still
stores the bundle and says which one is current (by checksum). If the download fails or is an older
bundle, the server falls back to the database copy, so the site never breaks because of this.

The repository is public and the bundle is built from MovieLens ratings, which may not be shared, so
the file host must be **private**. A private GitHub repository works and costs nothing:

1. On GitHub, create a **private** repository, for example `flickraven-artifacts` (empty is fine).
2. **Releases > Create a new release**, tag `bundle`, and attach `deploy-out\artifacts.tar.gz`. Publish.
3. Find the asset's API address. In PowerShell (replace OWNER):

   ```powershell
   (Invoke-RestMethod -Headers @{Authorization="Bearer <token>"} https://api.github.com/repos/OWNER/flickraven-artifacts/releases/tags/bundle).assets | Select-Object name, url
   ```

   The `url` looks like `https://api.github.com/repos/OWNER/flickraven-artifacts/releases/assets/123456`.
4. Make a token: GitHub **Settings > Developer settings > Fine-grained tokens > Generate**. Only the
   `flickraven-artifacts` repository, permission **Contents: Read-only**. Treat it like a password.
5. In Render, **Environment**, add `ARTIFACT_BUNDLE_URL` = the asset `url` from step 3 and
   `ARTIFACT_BUNDLE_TOKEN` = the token. Save.
6. The log line `artifact bundle fetched from ARTIFACT_BUNDLE_URL` on the next start confirms it.

**Every time you run `deploy_data.py upload` with a new bundle, upload the same `artifacts.tar.gz` to the
release again** (delete the old asset, attach the new one; the asset `url` changes, so update
`ARTIFACT_BUNDLE_URL`). Until you do, the server sees the checksum differs and uses the database copy.

## Back up and restore

`scripts\backup.ps1` saves the live database to `backups\flickraven-<date>.dump` on the laptop and keeps
the newest six. `monthly_refresh.ps1` runs it first, so a monthly refresh is also a monthly backup.
Backups contain users' emails: keep them on the laptop only.

To restore (this **replaces** everything on the live site with the backup):

```powershell
$env:TARGET = "<the Neon URL, starting postgresql://>"
docker run --rm -e TARGET -v "${PWD}\backups:/in:ro" postgres:17 sh -c 'pg_restore --clean --if-exists --no-owner --no-privileges -d "$TARGET" /in/flickraven-<date>.dump'
Remove-Item Env:TARGET
```

Then **Restart service** on Render.

## The private usage page (/stats)

In Render, **Environment**, add `ADMIN_EMAILS` = the email of your FlickRaven account (several: separate
with commas), then save (Render restarts the service). Sign in with that account and open `/stats`:
accounts, weekly active and returning people, ratings per day, the most opened films and how full the
database is. Everyone else gets "Page not found". It shows totals only, never one person's history.

## Housekeeping and limits (automatic)

- Guest sessions with no activity for 30 days are deleted, with their data. Records of which films were
  shown to whom (`recommendation_logs`) are deleted after 60 days. This runs every 12 hours while the
  service is awake (`RUN_CLEANUP=true` in the Dockerfile).
- One address can start at most 60 guest sessions an hour; one account can send at most 120 page-view
  events a minute (extra ones are dropped) and import at most 10 files an hour.

## Things to know about the free plans

- The free web service **sleeps after 15 minutes without visitors**. The next visit wakes it, which takes
  about a minute. A free uptime monitor keeps it awake (see "Keep the site awake" below).
- Render gives **750 free hours a month for all free web services together**. One service awake all month
  uses about 744, so keep only one FlickRaven service running (suspend any old one).
- Render's free database expires after 30 days and is deleted 14 days later, so the database now lives on
  **Neon** (free plan, no expiry, 1 GB per project; FlickRaven uses about 240 MB). See "Database on Neon" below.
- Sign-in lockout counters are kept in the server's memory, so a restart clears them.
- There is no email service, so the site cannot send password reset or verification emails.

## If Render says a free limit is reached

Render's free plan has two monthly limits. Check **Account > Billing / Usage** to see which one:

- **Free instance hours (750 a month for all free web services together).** One service kept awake all month uses about 720 to 744, so a second running service (for example the old `cinematch` service) pushes you over. Suspend or delete every FlickRaven service except the live one (`flickraven`). If the limit is still hit, pause the UptimeRobot monitor overnight (UptimeRobot > monitor > Pause, or a maintenance window), which lets the app sleep and saves about a quarter of the hours.
- **Build minutes.** Each deploy builds the Docker image (5 to 10 minutes). Deploy less: auto-deploy is off, so deploy by hand once after several merges.

The limits reset on the 1st. A paid web service (Starter, about $7 a month) has no hours limit and does not sleep.

## Keep the site awake (UptimeRobot)

1. Sign up free at <https://uptimerobot.com>.
2. **New monitor**: type **HTTP(s)**, URL `https://flickraven.onrender.com/api/ping`, interval **5 minutes**.
3. Save. The site no longer sleeps, so visitors never wait for it to wake up.

Use `/api/ping`, **not** `/api/health`. `/api/health` runs a database query, so pinging it every 5 minutes
would keep the Neon database awake all month and use up Neon's free compute hours. `/api/ping` never
touches the database; Neon still sleeps between real visitors.

## Other hosts that were considered

FlickRaven stays on Render. Checked 2026-11-13:

- **Vercel** cannot host the server: its Python functions are capped at 250 MB, the server's
  numpy/scipy/pandas/scikit-learn/pyarrow are larger, and the model would reload on every cold start.
- **Hugging Face Spaces**: since July 2026, Docker and Gradio Spaces on the free CPU Basic hardware
  need a PRO subscription (about $9 a month, more than Render Starter). Only static Spaces are free.

To stop the site sleeping, use the free UptimeRobot monitor above, or Render Starter (about $7 a month).

## Database on Neon

The web service stays on Render; only `DATABASE_URL` points somewhere else. To move an existing Render
database to Neon without losing accounts:

1. On <https://neon.com> create a project: Postgres **17**, region **AWS Asia Pacific (Singapore)**. Under
   **Connect**, turn connection pooling **off** and copy the connection string (the Neon URL).
2. Copy the Render database across with the `postgres:17` image (Docker Desktop running, in the `cinematch`
   folder). `Read-Host` keeps the URLs out of PowerShell's history:

   ```powershell
   mkdir deploy-out -Force
   $src = Read-Host "Paste the Render External Database URL"
   $dst = Read-Host "Paste the Neon URL"
   docker run --rm -e SRC=$src -v "${PWD}\deploy-out:/out" postgres:17 sh -c 'pg_dump "$SRC" -Fc --no-owner --no-privileges -f /out/full.dump'
   docker run --rm -e DST=$dst -v "${PWD}\deploy-out:/out" postgres:17 sh -c 'pg_restore --no-owner --no-privileges -d "$DST" /out/full.dump'
   ```

   A few warnings about extension ownership are normal. Delete `deploy-out\full.dump` afterwards: it holds
   user accounts.
3. In the Render service's **Environment** tab set `DATABASE_URL` to the Neon URL (if it is still linked to
   `cinematch-db`, delete it and add it again as a plain value), then **Manual Deploy**.
4. Check `/api/health` shows `"db":"ok"`. Later uploads (`deploy_data.py upload`) take the Neon URL.

For a brand-new setup, create the Neon project first, give its URL as `DATABASE_URL` when Render asks, and
follow Step 2 above with the Neon URL.

Neon's free compute pauses after about 5 minutes idle and wakes in under a second; `pool_pre_ping` in
`api/app/db.py` replaces connections it dropped.

## If something goes wrong

| What you see | What to do |
|---|---|
| Build fails on Render | Open the service's **Logs**. Most often a download timed out: click **Manual Deploy**, then **Deploy latest commit**. |
| `/api/health` shows `"db":"error"` | The database is still starting, or the service lost its `DATABASE_URL`. In the **Environment** tab, `DATABASE_URL` must be the Neon URL. |
| `upload` says the database has no FlickRaven tables | The service has not finished its first start. Wait for **Live**, then run `upload` again. |
| `upload` stops with "SSL connection has been closed unexpectedly" | Run the same `upload` command again. It skips what is done and continues with the missing parts. |
| `upload` cannot connect | Use the Neon URL with `sslmode=require` and check that Docker Desktop is running. |
| Home page shows no rails after the upload | Restart the service (Step 2.4). The logs should show `unpacked artifact bundle` and `recommender engine ready`. |
| Service restarts with "out of memory" | Move the web service to the paid Starter plan. Our measurement fits 512 MB, but this is the fix if real traffic needs more. |

## Trying the hosted setup on the laptop first (optional)

The same container can run locally against an empty database, which is how this setup was tested:

```powershell
docker build -t cinematch:local .
docker run --rm -p 8000:8000 --memory 512m -e DATABASE_URL=<a local test database URL> -e JWT_SECRET=<any long random text> cinematch:local
```

Then run `deploy_data.py upload` with that database's URL and open <http://localhost:8000>.
