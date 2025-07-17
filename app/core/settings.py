from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    GITHUB_TOKEN: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    DATABASE_URL: str


    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

print(f"Database URL: {settings.DATABASE_URL}")  # Добавь для отладки