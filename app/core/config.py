from pydantic_settings import BaseSettings
from typing import List, Optional
import secrets
import os


class Settings(BaseSettings):
    APP_NAME: str = "Listify API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "https://listify.app"]
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://listify:listify@localhost:5432/listify")
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    SECRET_KEY: str = secrets.token_hex(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    S3_BUCKET: str = "listify-receipts"
    S3_REGION: str = "eu-central-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    USE_LOCAL_STORAGE: bool = True
    LOCAL_STORAGE_PATH: str = "/tmp/listify"
    GOOGLE_VISION_API_KEY: str = ""
    USE_GOOGLE_VISION: bool = False
    OCR_CONFIDENCE_THRESHOLD: float = 0.75
    APPLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_ID: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
