"""Basic backend entry route."""

from flask import Blueprint


bp = Blueprint("core", __name__)


# --- Mock API Endpoints ---
@bp.route("/")
def index():
    return "ネタツイ大会バックエンド"
