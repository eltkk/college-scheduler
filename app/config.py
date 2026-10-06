from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://scheduler:scheduler@db:5432/scheduler"
    secure_cookies: bool = True
    allowed_hosts: str = "localhost,127.0.0.1"
    data_dir: Path = Path("data")
    session_hours: int = 12
    upload_limit_mb: int = 10
    solver_seconds: int = Field(default=30, ge=1, le=120)
    solver_workers: int = Field(default=2, ge=1, le=4)
    history_versions: int = Field(default=200, ge=20, le=1000)


settings = Settings()
