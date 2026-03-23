"""Flask application factory for IPS Server."""

import os
import logging

from flask import Flask
from flask_cors import CORS

from app.config import config_by_name
from app.models.base import db


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(
        __name__,
        static_folder="../static",
        template_folder="templates",
    )
    app.config.from_object(config_by_name[config_name])

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Extensions
    db.init_app(app)
    CORS(app, origins=app.config.get("CORS_ORIGINS", []))

    # Register blueprints
    from app.api.health import bp as health_bp
    from app.api.ips_routes import bp as ips_bp
    from app.api.push_routes import bp as push_bp
    from app.api.auth_routes import bp as auth_bp
    from app.api.audit_routes import bp as audit_bp
    from app.api.clinic_routes import bp as clinic_bp
    from app.fhir.fhir_routes import bp as fhir_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(ips_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(clinic_bp)
    app.register_blueprint(fhir_bp)

    # Register admin UI blueprint
    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    # Create tables and bootstrap on first request context
    with app.app_context():
        db.create_all()

        from app.services.bootstrap_service import bootstrap_superuser
        bootstrap_superuser(
            app.config.get("BOOTSTRAP_SU_USERNAME", ""),
            app.config.get("BOOTSTRAP_SU_PASSWORD", ""),
        )

    return app
