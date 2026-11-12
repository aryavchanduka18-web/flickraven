# Once a month: add new releases to the catalog, rebuild the local database and models bundle, and
# upload them to the live site. Takes about 15 to 30 minutes. Run from the cinematch folder:
#   scripts\monthly_refresh.ps1
# Needs: Docker Desktop running, the local database started (scripts\db.ps1), TMDB_API_KEY and
# NEON_DATABASE_URL in .env. Afterwards: Render, flickraven service, Manual Deploy > Deploy latest commit (a restart does not pick up new code).
. "$PSScriptRoot\_common.ps1"

$url = Get-EnvValue "NEON_DATABASE_URL"
if (-not $url) { throw "NEON_DATABASE_URL is missing from .env (the Neon connection URL of the live site)." }

function Step([string]$Title, [string[]]$PyArgs) {
    Write-Host "`n== $Title ==" -ForegroundColor Cyan
    & $Python @PyArgs
    if ($LASTEXITCODE -ne 0) { throw "Stopped at: $Title. Nothing was uploaded; fix the error and run this again." }
}

Push-Location $Root
try {
    Write-Host "== 0. Back up the live database first ==" -ForegroundColor Cyan
    & "$PSScriptRoot\backup.ps1"
    Step "1. Find new releases on TMDB" @("-m", "pipeline.new_releases")
    Step "1b. Widen the catalog (Indian, Hollywood, Korean and Japanese films)" @("-m", "pipeline.widen_catalog")
    Step "1c. Series and anime (TMDB)" @("-m", "pipeline.series")
    Step "2. Rebuild the catalog (step 5)" @("-m", "pipeline.run_all", "--only", "5")
    Step "3. Load it into the local database (step 12)" @("-m", "pipeline.run_all", "--only", "12")
    Step "3b. Where to watch (TMDB / JustWatch, India first)" @("-m", "pipeline.watch_providers")
    Step "3c. IMDb ratings (IMDb's dataset, display only)" @("-m", "pipeline.imdb_ratings")
    Step "4. Give new films content features" @("-m", "pipeline.extend_serving")
    Step "4b. More Like This neighbours for the new titles" @("-m", "pipeline.similar_titles")
    Step "5. Export catalog and models" @("scripts\deploy_data.py", "export")
    $env:TARGET_DATABASE_URL = $url
    try { Step "6. Upload to the live site" @("scripts\deploy_data.py", "upload", "--refresh-catalog") }
    finally { Remove-Item Env:TARGET_DATABASE_URL -ErrorAction SilentlyContinue }
    $report = Get-Content (Join-Path $Root "data\processed\new_releases_report.json") | ConvertFrom-Json
    Write-Host "`nDone. New films this month: $($report.new_this_run)." -ForegroundColor Green
    Write-Host "Last step: Render > flickraven > Manual Deploy > Deploy latest commit (a restart does not pick up new code)." -ForegroundColor Yellow
} finally { Pop-Location }
