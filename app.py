# -*- coding: utf-8 -*-
"""app.py - Web entry point for Auto Report.

Usage:
    python app.py          # Start web interface
    python report_generator.py  # CLI mode (unchanged)
"""

import os

from web import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "5000"))
    host = os.getenv("WEB_HOST", "0.0.0.0")
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug, threaded=True)
