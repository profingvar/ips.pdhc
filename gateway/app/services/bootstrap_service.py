"""Bootstrap superuser creation on first startup."""

import logging
from werkzeug.security import generate_password_hash

from app.models.base import db
from app.models.user import User

logger = logging.getLogger(__name__)


def bootstrap_superuser(username: str, password: str) -> None:
    """Create bootstrap superuser if no users exist and credentials are provided."""
    if not username or not password:
        logger.info("No bootstrap credentials configured — skipping SU creation")
        return

    existing_count = db.session.query(User).count()
    if existing_count > 0:
        logger.info("Users already exist — skipping bootstrap SU creation")
        return

    try:
        su = User(
            username=username,
            display_name="System Administrator",
            password_hash=generate_password_hash(password),
            role="admin",
            is_active=True,
            is_superuser=True,
        )
        db.session.add(su)
        db.session.commit()
        logger.info("Bootstrap superuser '%s' created successfully", username)
    except Exception:
        db.session.rollback()
        logger.info("Bootstrap SU already created by another worker — skipping")
