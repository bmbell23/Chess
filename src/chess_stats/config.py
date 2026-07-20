from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    app_name: str = "Chess Stats"
    host: str = "0.0.0.0"
    port: int = 8011
    database_url: str = "sqlite:///./data/chess.db"
    enable_schedulers: bool = False
    tz: str = "America/Denver"

    # chess.com Published-Data API — public and read-only; no password/token exists
    chesscom_username: str = ""
    contact_email: str = ""  # goes in the User-Agent header per chess.com etiquette


@lru_cache
def get_settings() -> Settings:
    return Settings()
