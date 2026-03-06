from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Listify API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "https://listify.app"]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://listify:listify@localhost:5432/listify"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Auth
    SECRET_KEY: str = secrets.token_hex(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24        # 24h
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # S3 / Storage
    S3_BUCKET: str = "listify-receipts"
    S3_REGION: str = "eu-central-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    USE_LOCAL_STORAGE: bool = True          # dev mode — save to disk
    LOCAL_STORAGE_PATH: str = "/tmp/listify"

    # OCR
    GOOGLE_VISION_API_KEY: str = ""
    USE_GOOGLE_VISION: bool = False         # fallback to Tesseract if False
    OCR_CONFIDENCE_THRESHOLD: float = 0.75

    # Apple / Google OAuth
    APPLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_ID: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
