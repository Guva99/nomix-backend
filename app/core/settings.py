from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    GITHUB_TOKEN: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    DATABASE_URL: str

    JWT_SECRET: str = Field(..., env="JWT_SECRET")
    JWT_EXP_MIN: int = Field(60, env="JWT_EXP_MIN")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

# ⚠️ Для прод лучше убрать вообще; если нужен лог — маскируем пароль:
try:
    from urllib.parse import urlparse
    import re
    parsed = urlparse(settings.DATABASE_URL)
    masked_netloc = re.sub(r":([^@]+)@", ":****@", parsed.netloc)
    safe_url = settings.DATABASE_URL.replace(parsed.netloc, masked_netloc)
    print(f"Database URL: {safe_url}")
except Exception:
    pass
