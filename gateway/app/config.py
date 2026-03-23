"""Application configuration from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-fallback-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://ips_user:dev@localhost:9041/ips_db"
    )
    OAUTH_BASE_URL = os.environ.get("OAUTH_BASE_URL", "https://sso.pdhc.se")
    API_KEY_SECRET = os.environ.get("API_KEY_SECRET", "")
    BOOTSTRAP_SU_USERNAME = os.environ.get("BOOTSTRAP_SU_USERNAME", "")
    BOOTSTRAP_SU_PASSWORD = os.environ.get("BOOTSTRAP_SU_PASSWORD", "")
    CORS_ORIGINS = [
        o.strip()
        for o in os.environ.get("CORS_ORIGINS", "http://localhost:9042").split(",")
        if o.strip()
    ]
    AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "false").lower() == "true"
    APP_PORT = int(os.environ.get("APP_PORT", "9040"))
    ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "9042"))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    AUTH_DISABLED = True


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
