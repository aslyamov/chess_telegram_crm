from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    telegram_bot_token: str = ""
    admin_telegram_id: int = 0
    google_application_credentials: str = "data/serviceAccountKey.json"
    lichess_api_token: Optional[str] = None
    lichess_team_id: str = "j7rco75Y"
    webhook_url: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
