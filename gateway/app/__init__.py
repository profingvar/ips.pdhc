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
    from app.api.admin_blocks_routes import bp as admin_blocks_bp
    from app.api.consents_routes import bp as consents_bp
    from app.api.care_access_routes import bp as care_access_bp  # D3 #406
    from app.api.patient_blocks_routes import bp as patient_blocks_bp
    from app.api.patient_consents_routes import bp as patient_consents_bp
    from app.api.copy_routes import bp as copy_bp
    from app.patient_portal import bp as patient_portal_bp
    from app.fhir.fhir_routes import bp as fhir_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(ips_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(clinic_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(blocks_bp)
    app.register_blueprint(admin_blocks_bp)
    app.register_blueprint(consents_bp)
    app.register_blueprint(care_access_bp)  # D3 #406
    app.register_blueprint(patient_blocks_bp)
    app.register_blueprint(patient_consents_bp)
    app.register_blueprint(copy_bp)
    app.register_blueprint(patient_portal_bp)
    app.register_blueprint(fhir_bp)

    # SSO login/callback/logout
    from app.api.sso_routes import bp as sso_bp
    app.register_blueprint(sso_bp)

    # Register admin UI blueprint. Import side-modules that attach
    # additional routes to the same blueprint BEFORE register; Flask
    # locks the blueprint at register time so late attachment fails
    # silently.
    from app.admin import bp as admin_bp
    from app import admin_block_lift as _admin_block_lift_module  # noqa: F401 — registers /admin/blocks/<g>/lift*
    app.register_blueprint(admin_bp)

    # Root URL → admin dashboard
    @app.route("/")
    def index():
        return redirect(url_for("admin.dashboard"))

    # Ticket #202 — `flask sweep-blocks` CLI.
    from app.services.block_expiry_service import sweep as _sweep_blocks

    @app.cli.command("sweep-blocks")
    def _sweep_blocks_cli():  # noqa: D401
        """Expire past-deadline blocks and re-impose timed-out
        indispensable_care lifts. Run hourly from cron."""
        import click as _click
        out = _sweep_blocks()
        _click.echo(
            f"sweep-blocks expired={out['expired']['expired']} "
            f"re_imposed={out['re_imposed']['re_imposed']}"
        )

    # #789 — `flask check-personnummer`, read-only.
    #
    # The decision on the pre-existing rows is FIX FORWARD: they are synthetic
    # and restamping would have to rewrite both PatientIndex.identifier_value
    # and the identifier inside each Patient resource_json, which is a
    # migration rather than an update. The same fill-forward choice #781 took
    # for patient_org_guid. This command is the other half of that decision --
    # leaving legacy rows is only defensible if their number is known and
    # visible rather than quietly assumed.

    @app.cli.command("check-personnummer")
    def _check_personnummer_cli():  # noqa: D401
        """Report how many patient identifiers are valid Swedish personnummer.

        Read-only. Counts by failure reason, and separates FOREIGN identifier
        systems (10 live patients carry US SSNs from the Synthea import) from
        BROKEN Swedish ones -- a foreign identifier is not a defect, and
        lumping the two together would overstate the problem.
        """
        import click as _click
        from collections import Counter
        from app.models.patient_index import PatientIndex
        from app.services import personnummer as pnr

        rows = db.session.query(PatientIndex).all()
        valid = 0
        foreign: Counter = Counter()
        reasons: Counter = Counter()
        no_identifier = 0
        for p in rows:
            if not p.identifier_value:
                no_identifier += 1
                continue
            if p.identifier_system != pnr.PERSONNUMMER_SYSTEM:
                foreign[p.identifier_system or "(no system)"] += 1
                continue
            why = pnr.describe_invalid(p.identifier_value, birth=p.birth_date)
            if why is None:
                valid += 1
            else:
                # Collapse to a class rather than the per-row message, so the
                # output is a summary and not 140 lines.
                if "check digit" in why:
                    reasons["invalid check digit"] += 1
                elif "not a personnummer" in why:
                    reasons["malformed (wrong length or shape)"] += 1
                elif "contradicts" in why or "says" in why:
                    reasons["disagrees with the patient's birth_date"] += 1
                elif "impossible date" in why:
                    reasons["impossible date"] += 1
                else:
                    reasons["other"] += 1

        _click.echo(f"patients: {len(rows)}")
        _click.echo(f"  valid Swedish personnummer : {valid}")
        _click.echo(f"  no identifier at all       : {no_identifier}")
        for sysname, n in foreign.most_common():
            _click.echo(f"  foreign identifier system  : {n}  ({sysname})")
        if reasons:
            _click.echo("  BROKEN Swedish personnummer:")
            for reason, n in reasons.most_common():
                _click.echo(f"      {n:>4}  {reason}")
        else:
            _click.echo("  BROKEN Swedish personnummer: 0")
        _click.echo("")
        _click.echo("Pre-existing rows are left as they are (#789: fix forward).")
        _click.echo("Newly generated patients are built by "
                    "app.services.personnummer.build and are valid.")

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
