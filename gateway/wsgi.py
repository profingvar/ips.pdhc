"""WSGI entry point for the IPS Server."""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=app.config.get("APP_PORT", 9040),
        debug=app.config.get("DEBUG", False),
    )
