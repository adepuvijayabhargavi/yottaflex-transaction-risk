"""Local development entry point for the YottaFlex application."""

import os

from app import create_app

app = create_app(os.getenv("YTF_ENV", "development"))


if __name__ == "__main__":
    host = os.getenv("YTF_HOST", "127.0.0.1")
    port = int(os.getenv("YTF_PORT", os.getenv("PORT", "5000")))
    app.run(
        host=host,
        port=port,
        debug=app.config.get("DEBUG", False),
        use_reloader=False,
    )
