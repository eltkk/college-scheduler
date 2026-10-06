from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://scheduler:scheduler@db:5432/scheduler"
    secure_cookies: bool = True
    allowed_hosts: str = "localhost,127.0.0.1"
    data_dir: Path = Path("data")
    session_hours: int = 12
    upload_limit_mb: int = 10
    solver_seconds: int = 30
    solver_workers: int = 2


settings = Settings()
