# -*- coding: utf-8 -*-
"""web/__init__.py - Flask application factory."""

import os
from pathlib import Path

from flask import Flask

from web.db import init_db, close_db

_BASE_DIR = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
        instance_path=str(_BASE_DIR / "instance"),
    )

    app.config["SECRET_KEY"] = os.getenv(
        "FLASK_SECRET_KEY", "change-me-in-production-please"
    )
    app.config["DATABASE"] = os.path.join(app.instance_path, "auto_report.db")

    os.makedirs(app.instance_path, exist_ok=True)

    init_db(app)
    app.teardown_appcontext(close_db)

    from web.auth import auth_bp
    from web.routes import main_bp
    from web.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # Register status callback for SSE real-time updates
    from core.status import register_status_callback
    from web.api import broadcast_event

    def _on_status_change(client_name: str, status_msg: str):
        broadcast_event("status_change", {"client": client_name, "status": status_msg})

    register_status_callback(_on_status_change)

    return app
