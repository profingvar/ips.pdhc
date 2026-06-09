"""Flask application factory for IPS Server."""

import os
import logging

from flask import Flask, redirect, url_for
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

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

    # Trust proxy headers from nginx (X-Forwarded-For, X-Forwarded-Proto, etc.)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Extensions
    db.init_app(app)
    CORS(app, origins=app.config.get("CORS_ORIGINS", []))

    # Always rollback before removing — prevents PendingRollbackError on next request
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db.session.rollback()
        db.session.remove()

    # Register blueprints
    from app.api.health import bp as health_bp
    from app.api.ips_routes import bp as ips_bp
    from app.api.push_routes import bp as push_bp
    from app.api.auth_routes import bp as auth_bp
    from app.api.audit_routes import bp as audit_bp
    from app.api.clinic_routes import bp as clinic_bp
    from app.api.patient_routes import bp as patient_bp
    from app.api.blocks_routes import bp as blocks_bp
    from app.api.consents_routes import bp as consents_bp
    from app.fhir.fhir_routes import bp as fhir_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(ips_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(clinic_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(blocks_bp)
    app.register_blueprint(consents_bp)
    app.register_blueprint(fhir_bp)

    # SSO login/callback/logout
    from app.api.sso_routes import bp as sso_bp
    app.register_blueprint(sso_bp)

    # Register admin UI blueprint
    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    # Root URL → admin dashboard
    @app.route("/")
    def index():
        return redirect(url_for("admin.dashboard"))

    # Create tables and bootstrap — guarded for concurrent gunicorn workers
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            logging.getLogger(__name__).info(
                "db.create_all() handled by another worker — skipping"
            )

        from app.services.bootstrap_service import bootstrap_superuser
        bootstrap_superuser(
            app.config.get("BOOTSTRAP_SU_USERNAME", ""),
            app.config.get("BOOTSTRAP_SU_PASSWORD", ""),
        )

    return app
