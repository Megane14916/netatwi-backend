"""Basic backend entry route."""

from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("core", __name__)


# --- Mock API Endpoints ---
@bp.route("/")
def index():
    return "ネタツイ大会バックエンド"
