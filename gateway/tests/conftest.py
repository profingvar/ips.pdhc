"""Pytest fixtures for IPS Server tests."""

import pytest

from app import create_app
from app.models.base import db as _db


@pytest.fixture(scope="session")
def app():
    """Create application for testing."""
    app = create_app("testing")
    yield app


@pytest.fixture(scope="function")
def db(app):
    """Provide a clean database for each test."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture(scope="function")
def client(app, db):
    """Flask test client."""
    with app.test_client() as client:
        with app.app_context():
            yield client
