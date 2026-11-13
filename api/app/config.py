from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repository root (cinematch/.env)
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    database_url: str
    jwt_secret: str = ""
    tmdb_api_key: str = ""
    web_origin: str = "http://localhost:5173"
    # Hosting over HTTPS: COOKIE_SECURE=true so the session cookie is only sent over HTTPS.
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    # Hosting: build the recommender at start-up instead of on the first request.
    preload_engine: bool = False
    # Hosting: delete idle guests and old recommendation logs every 12 hours (app/services/cleanup.py).
    run_cleanup: bool = False
    # Emails allowed to open the private /stats page, comma-separated (e.g. ADMIN_EMAILS=you@gmail.com).
    admin_emails: str = ""
    # Show IMDb ratings (IMDb's dataset is licensed for non-commercial use; see docs/decisions-log.md).
    # IMDB_RATINGS=false hides them everywhere at the next restart, without touching the data.
    imdb_ratings: bool = True
    # AI assistant (Google Gemini). The key lives only in this environment variable, never in the repository.
    # ASSISTANT_ENABLED=false switches the assistant off at the next restart. Caps are messages per person per day.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_models: str = "gemini-2.5-flash,gemini-flash-latest"   # tried in order when a model id returns 404
    assistant_enabled: bool = True
    # Mixed films, series and anime in the Home hero and first Top Picks (services/mixed_home_plan.py). Off until the offline replay passes.
    mixed_home: bool = False
    ai_similar_daily_cap: int = 300      # Gemini calls per day for "More Like This" on series (cached, so one per title per week)
    assistant_daily_cap: int = 30
    assistant_guest_cap: int = 8
    # Model bundle from a private file host instead of the database (docs/deploy.md, "Model bundle outside the
    # database"). Each start of the free web service otherwise pulls ~52 MB from Neon, which used up Neon's free
    # 5 GB monthly transfer in November 2026. The database still says which bundle is current (its checksum);
    # the bytes come from this URL, and from the database only if the download fails or does not match.
    artifact_bundle_url: str = ""
    artifact_bundle_token: str = ""      # read-only token for a private GitHub repo; sent only to that host

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, url: str) -> str:
        # Render (and most hosts) hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    app_version: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
