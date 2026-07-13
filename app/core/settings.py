from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    WEBAPP_BASE_URL: str = "http://localhost:8000"
    API_BASE_URL: str = "http://localhost:8000"
    WEBHOOK_URL: str = "http://localhost:8000/api/telegram/webhook"
    BASE_URL: str = "http://localhost:8000"
    BUILD_VERSION: str = "dev"
    INTERNAL_API_SECRET: str = ""

    # Gemini (receipt OCR)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # PostgreSQL
    POSTGRES_USER: str = "nomix"
    POSTGRES_PASSWORD: str = "nomix"
    POSTGRES_DB: str = "numix"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = ""

    # Auth
    JWT_SECRET: str = "change_me_in_production"
    JWT_EXP_MIN: int = 60

    # App
    DATABASE_MAX_RETRIES: int = 10
    DATABASE_RETRY_DELAY: int = 5
    TMP_DIR: str = "/app/static/tmp"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def build_database_url(cls, value: str) -> str:
        if value:
            return value
        return ""

    def resolved_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()

try:
    from urllib.parse import urlparse
    import re

    parsed = urlparse(settings.resolved_database_url())
    masked_netloc = re.sub(r":([^@]+)@", ":****@", parsed.netloc)
    safe_url = settings.resolved_database_url().replace(parsed.netloc, masked_netloc)
    print(f"Database URL: {safe_url}")
except Exception:
    pass
