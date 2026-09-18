"""Central settings. SQLite default so `pytest`/local run works with zero deps."""
from __future__ import annotations
import os
import logging
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    JWT_SECRET: str = "change-me-dev-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720
    DATABASE_URL: str = "sqlite:///./codesense.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_EAGER: bool = False
    REPO_STORAGE_DIR: str = "./data/repos"
    DOC_OUTPUT_DIR: str = "./data/docs"
    LLM_PROVIDER: str = "offline"  # anthropic | openai | offline
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = ""
    EMBEDDING_BACKEND: str = "tfidf"
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_CALLBACK: str = "http://localhost:8000/auth/github/callback"
    CREDENTIAL_FERNET_KEY: str = ""
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }


settings = Settings()
os.makedirs(settings.REPO_STORAGE_DIR, exist_ok=True)
os.makedirs(settings.DOC_OUTPUT_DIR, exist_ok=True)

logger = logging.getLogger("codesense.security")
INSECURE_DEV_SECRET = "change-me-dev-secret"


def validate_security_settings():
    if os.getenv("ENV") == "production":
        if settings.JWT_SECRET == INSECURE_DEV_SECRET or not settings.JWT_SECRET:
            raise ValueError(
                "CRITICAL SECURITY FAILURE: JWT_SECRET must be configured with a secure random secret in production!"
            )
        if len(settings.JWT_SECRET) < 32:
            raise ValueError(
                "CRITICAL SECURITY FAILURE: JWT_SECRET must be at least 32 characters long in production!"
            )
        if "localhost" in settings.FRONTEND_ORIGIN:
            logger.warning(
                "PRODUCTION CONFIG WARNING: FRONTEND_ORIGIN contains 'localhost' in production mode (%s).",
                settings.FRONTEND_ORIGIN,
            )
    else:
        if settings.JWT_SECRET == INSECURE_DEV_SECRET:
            logger.warning(
                "SECURITY WARNING: Running with default development JWT_SECRET. "
                "For production environments, set a strong random JWT_SECRET in .env."
            )
