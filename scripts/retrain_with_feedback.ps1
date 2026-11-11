# Retrain the models with the ratings people made on the live site, and check it did no harm.
# Run it about once a month, after scripts\monthly_refresh.ps1. Takes about 20 to 40 minutes. From the cinematch folder:
#   scripts\retrain_with_feedback.ps1
# Needs: Docker not required; NEON_DATABASE_URL in .env (read only: it only copies ratings out).
# It does NOT upload anything. If the check says "Safe to ship", run:
#   .venv\Scripts\python.exe scripts\deploy_data.py export
#   (then the upload step from docs\deploy.md) and Render > Manual Deploy > Deploy latest commit.
# If it says "Keep the old models", restore the copy it saved in artifacts\_before_feedback (instructions printed).
. "$PSScriptRoot\_common.ps1"
$url = Get-EnvValue "NEON_DATABASE_URL"
if (-not $url) { throw "NEON_DATABASE_URL is missing from .env." }

function Step([string]$Title, [string[]]$PyArgs) {
    Write-Host "`n== $Title ==" -ForegroundColor Cyan
    & $Python @PyArgs
    if ($LASTEXITCODE -ne 0) { throw "Stopped at: $Title. The old models are still in artifacts\_before_feedback." }
}

Push-Location $Root
try {
    $env:PYTHONUTF8 = "1"
    $keep = Join-Path $Root "artifacts\_before_feedback"
    if (Test-Path $keep) { Remove-Item $keep -Recurse -Force }
    New-Item -ItemType Directory -Path $keep | Out-Null
    Copy-Item "artifacts\models" (Join-Path $keep "models") -Recurse
    Copy-Item "artifacts\metrics" (Join-Path $keep "metrics") -Recurse
    Write-Host "Saved the current models and metrics to $keep" -ForegroundColor Green

    $env:DATABASE_URL = $url
    try { Step "1. Copy the site's ratings out of the live database (read only)" @("-m", "pipeline.export_site_feedback") }
    finally { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }

    $env:FLICKRAVEN_SITE_FEEDBACK = "1"
    try {
        Step "2. Retrain the models with site ratings added to training" @("-m", "pipeline.run_all", "--only", "9")
        Step "3. Re-tune the hybrid weights" @("-m", "pipeline.10_tune_hybrid")
        Step "4. Measure again on the same MovieLens test ratings" @("-m", "pipeline.11_evaluate")
    } finally { Remove-Item Env:FLICKRAVEN_SITE_FEEDBACK -ErrorAction SilentlyContinue }

    Write-Host "`n== 5. Did it do any harm? ==" -ForegroundColor Cyan
    & $Python -m pipeline.compare_feedback_retrain (Join-Path $keep "metrics\test_comparison.json") "artifacts\metrics\test_comparison.json"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`nSafe to ship. Nothing was uploaded: export and upload as in docs\deploy.md, then Manual Deploy." -ForegroundColor Green
    } else {
        Write-Host "`nKeep the old models. To go back: copy $keep\models over artifacts\models and $keep\metrics over artifacts\metrics." -ForegroundColor Yellow
    }
} finally { Pop-Location }
