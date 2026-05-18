from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost/wb_agent"

    # Telegram
    telegram_bot_token: str
    admin_user_id: int

    # Gemini API
    gemini_api_key: str

    # WB API
    wb_token: str = ""

    # Sentry (опционально)
    sentry_dsn: str = ""

    # Railway (проставляется автоматически при деплое)
    railway_public_domain: str = ""

    @property
    def webhook_url(self) -> str:
        return f"https://{self.railway_public_domain}/webhook"

    @property
    def webhook_path(self) -> str:
        return "/webhook"


settings = Settings()
