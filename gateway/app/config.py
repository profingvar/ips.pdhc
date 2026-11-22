"""Application configuration from environment variables."""

import os
from dotenv import load_dotenv

from app.services.env_names import env_flag, env_value

load_dotenv()


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-fallback-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://ips_user:dev@localhost:9041/ips_db"
    )
    OAUTH_BASE_URL = os.environ.get("OAUTH_BASE_URL", "https://sso.pdhc.se")
    SSO_CLIENT_ID = os.environ.get("SSO_CLIENT_ID", "")
    SSO_CLIENT_SECRET = os.environ.get("SSO_CLIENT_SECRET", "")
    # #1017: the pair sso.pdhc registers for the eps.pdhc.se callback. Used
    # only for requests that arrive on eps.pdhc.se, and only when BOTH are
    # set; otherwise the pair above (app/services/service_identity.py).
    SSO_CLIENT_ID_EPS = os.environ.get("SSO_CLIENT_ID_EPS", "")
    SSO_CLIENT_SECRET_EPS = os.environ.get("SSO_CLIENT_SECRET_EPS", "")
    # API_KEY_SECRET (#349 §4.3 / #392) — removed 2026-07-03.
    # Was reserved for Fernet-encrypting push-destination credentials
    # (readme.md §5.d, ticket #6), never implemented. Deleted to avoid
    # a stale placeholder confusing future readers. If push-cred
    # encryption ever ships, add the config fresh alongside the
    # feature — don't design for hypothetical future requirements.
    BOOTSTRAP_SU_USERNAME = os.environ.get("BOOTSTRAP_SU_USERNAME", "")
    BOOTSTRAP_SU_PASSWORD = os.environ.get("BOOTSTRAP_SU_PASSWORD", "")
    CORS_ORIGINS = [
        o.strip()
        for o in os.environ.get("CORS_ORIGINS", "http://localhost:9042").split(",")
        if o.strip()
    ]
    AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "false").lower() == "true"
    # #1049: POST /api/v1/patients/self-register refuses a personnummer with a
    # VALID check digit (it may be a real person's) while this is true. The
    # pilot holds synthetic people only, and sso applies the same rule
    # (PATIENT_REGISTRATION_SYNTHETIC_ONLY); this is eps's own floor, so an
    # sso misconfiguration cannot put a real number here. Only "false" turns
    # it off.
    SELF_REGISTER_SYNTHETIC_ONLY = os.environ.get(
        "SELF_REGISTER_SYNTHETIC_ONLY", "true").strip().lower() != "false"
    APP_PORT = int(os.environ.get("APP_PORT", "9040"))
    ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "9042"))

    # Ticket #202 — block-state webhooks.
    # IPS_WEBHOOK_SECRET: shared HMAC-SHA256 signing secret. Empty -> the
    #   dispatcher logs a warning and skips delivery (the sweep + state
    #   transitions still run; only the outbound notification is muted).
    # IPS_WEBHOOK_TARGETS: comma-separated subscriber URLs. Each receives
    #   the same signed payload.
    #
    # #1017: each of this service's own IPS_<NAME> variables is read as
    # EPS_<NAME> first, IPS_<NAME> as fallback (app/services/env_names.py).
    # The config KEYS keep their IPS_ names; only the env names gain an alias.
    IPS_WEBHOOK_SECRET = env_value("WEBHOOK_SECRET", "")
    IPS_WEBHOOK_TARGETS = [
        u.strip()
        for u in env_value("WEBHOOK_TARGETS", "").split(",")
        if u.strip()
    ]
    IPS_WEBHOOK_TIMEOUT = float(
        env_value("WEBHOOK_TIMEOUT", "5"),
    )

    # #902's flag. Until #1017 NO code copied it from the environment into
    # config, so setting IPS_ADMIN_REQUIRE_ANALYSIS_PHASE in .env did nothing
    # (admin.py reads current_app.config). Now read from EPS_/IPS_ env as a
    # strict boolean (1/true/yes/on); unset is False, exactly as before.
    IPS_ADMIN_REQUIRE_ANALYSIS_PHASE = env_flag("ADMIN_REQUIRE_ANALYSIS_PHASE")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    AUTH_DISABLED = True


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
