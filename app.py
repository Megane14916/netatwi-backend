"""Direct development server entry."""

import os

from app import create_app
from app.extensions import db


def main():
    application = create_app()
    with application.app_context():
        db.create_all()
        print("Database tables created (if not existed).")
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False)


if __name__ == "__main__":
    main()
