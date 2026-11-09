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
