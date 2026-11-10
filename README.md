# FlickRaven

An explainable hybrid recommendation website for films, TV series and anime.
It recommends titles and shows where to watch them; it does not stream them.

**Live:** https://flickraven.onrender.com (Render free plan: the first visit after a restart can take up to half a
minute while the recommender loads). How it is hosted and how to update it: `docs/deploy.md`.

What a visitor can do: create an account (or browse as a guest), rate, like, dislike (with a reason), save to My
List, tune the recommendations, open "Why?" on any recommendation (what each model contributed, how much the
models agree), browse franchises ("More from John Wick", "More from Marvel"), cast and crew pages, themed rows
(Rom-Com, Crime Thriller, ...), genre and Discover pages with every title (Movies / Series / Anime tabs),
For Tonight, and the Research Lab. Search understands genre, language, year and series/anime words ("hindi comedy",
"90s action", "korean series") and suggests films, people and genres as you type. Film pages show the IMDb score,
where to watch (India first, via TMDB / JustWatch) and, for series, seasons and episodes. Home has Netflix-style
series rows (East Asian dramas, Popular K-dramas, binge-worthy, quick comedy, because you liked ..., a films-and-series
mix). The catalog has about 33,000 titles (27,000 films, 4,300 series, 1,500 anime).
Not available (no email service): email verification and password reset.

| Part | Folder | Tech |
| --- | --- | --- |
| Website | `web/` | React, TypeScript, Vite, Tailwind, React Router, TanStack Query, Framer Motion |
| API | `api/` | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg 3 |
| Database | `docker-compose.yml` | PostgreSQL 17 in Docker |
| Recommendation engine | `engine/` | Python package `cinematch_engine`, shared by the API and the pipeline |
| Offline pipeline | `pipeline/` | Builds data and trains models (Phase 2) |

Other folders: `notebooks/` (experiments), `data/` and `artifacts/` (big local files, not in git), `docs/viva/` (viva notes).

## What you need installed (once)

- Docker Desktop (with WSL 2)
- Python 3.12 (`py -3.12 --version` should work)
- Node.js 20 or newer
- Git

## First-time setup

Open PowerShell in the `cinematch` folder.

1. Create your secrets file (skip this if `.env` already exists):
   ```powershell
   Copy-Item .env.example .env
   ```
   Open `.env` and replace the `change-me` values with long random strings, and paste your TMDB key after `TMDB_API_KEY=`.
   Use the same password in `POSTGRES_PASSWORD` and inside `DATABASE_URL`.

2. Create the Python environment and install the API and engine:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".\engine[dev]" -e ".\api[dev]"
   ```

3. Install the website packages:
   ```powershell
   cd web; npm install; cd ..
   ```

If PowerShell refuses to run the scripts below, allow local scripts for your user once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Running it every day

1. **Start Docker Desktop** from the Start menu and wait until it says "Engine running".
2. **Start the database:**
   ```powershell
   .\scripts\db.ps1
   ```
3. **Create or update the tables** (safe to run any time):
   ```powershell
   .\scripts\migrate.ps1
   ```
4. **Start the API** (leave this window open):
   ```powershell
   .\scripts\api.ps1
   ```
   Check it: http://127.0.0.1:8010/api/health should show `"db": "ok"`.
   API docs: http://127.0.0.1:8010/docs
5. **Start the website** in a second PowerShell window (leave it open):
   ```powershell
   .\scripts\web.ps1
   ```
6. **Open http://localhost:5173** in your browser. The Home page should say `API: ok, DB: ok`.

To stop: press `Ctrl+C` in the API and website windows, then run `.\scripts\db.ps1 stop`.

## Building the data and the models (once, about 1-2 hours)

The website needs the catalog in the database and the trained models in `artifacts/`. With the
database running:

```powershell
.\scripts\data.ps1              # steps 1-12: download, TMDB, Wikidata, clean, ratings, splits,
                                # features, train + tune models, hybrid weights, evaluation, DB load
.\.venv\Scripts\python.exe -m pipeline.13_shilling     # optional lab experiments
.\.venv\Scripts\python.exe -m pipeline.14_taste_map
.\.venv\Scripts\python.exe -m pipeline.15_ncf
.\.venv\Scripts\python.exe -m pipeline.report_validation   # refresh docs/phase-*-results.md
.\.venv\Scripts\python.exe -m pipeline.demo_accounts       # the prepared demo account
```

If only the catalog changes (for example the metadata gate), the models do not have to be retrained:
```powershell
.\scripts\data.ps1 -Only 5; .\scripts\data.ps1 -Only 12          # new catalog cut, load it
.\.venv\Scripts\python.exe -m pipeline.extend_serving             # content rows + popularity for new films
```
Then restart the API so it reloads the catalog.

Everything downloaded is cached in `data/raw/`, so re-running never fetches twice. Keep the laptop
plugged in with the lid open during long runs (sleep pauses the jobs).

## Where things are

| What | Where |
|---|---|
| The approved spec | `docs/spec.md` |
| Results tables per phase | `docs/phase-3-results.md` ... `docs/phase-6-results.md` |
| Viva notes per phase | `docs/viva/` |
| Architecture overview | `docs/architecture.md` |
| Demo script | `docs/demo-script.md` |
| Decisions made during the build | `docs/decisions-log.md` |
| Things to check by hand at the end | `docs/final-checks.md` |
| Catalog coverage audit | `docs/catalog-audit.md` |
| Hosting on Render (step by step) | `docs/deploy.md` |
| Hosting, franchises, confidence, v2 (viva notes) | `docs/viva/phase-14-hosting-and-v2.md` |
| Research Lab (in the app) | http://localhost:5173/lab |

## Tests

With the database running:
```powershell
.\scripts\test.ps1
```
This runs the engine, pipeline and API tests (the API tests use a separate `cinematch_test` database\nthat is rebuilt on every run), the scenario tests (the 12 of spec section 16 plus More Like This and liked-film pages) (on the real catalog, with\nthrowaway users that are deleted afterwards) and the website tests.

## Ports

| What | Address |
| --- | --- |
| Website (Vite) | http://localhost:5173 |
| API (FastAPI) | http://127.0.0.1:8010 (change with `API_PORT` in `.env`) |
| PostgreSQL | localhost:5432 |