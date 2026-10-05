"""Compatibility alias for app.routes; no processing bodies live here."""

from importlib import import_module
import sys

_target = import_module("app.routes")
sys.modules[__name__ + ".account"] = import_module("app.routes.account")
sys.modules[__name__ + ".admin"] = import_module("app.routes.admin")
sys.modules[__name__ + ".auth"] = import_module("app.routes.auth")
sys.modules[__name__ + ".comments"] = import_module("app.routes.comments")
sys.modules[__name__ + ".contests"] = import_module("app.routes.contests")
sys.modules[__name__ + ".core"] = import_module("app.routes.core")
sys.modules[__name__ + ".dependencies"] = import_module("app.routes.dependencies")
sys.modules[__name__ + ".interactions"] = import_module("app.routes.interactions")
sys.modules[__name__ + ".legacy"] = import_module("app.routes.legacy")
sys.modules[__name__ + ".news"] = import_module("app.routes.news")
sys.modules[__name__ + ".notifications"] = import_module("app.routes.notifications")
sys.modules[__name__ + ".posts"] = import_module("app.routes.posts")
sys.modules[__name__ + ".profile"] = import_module("app.routes.profile")
sys.modules[__name__ + ".results"] = import_module("app.routes.results")
sys.modules[__name__ + ".tasks"] = import_module("app.routes.tasks")
sys.modules[__name__ + ".users"] = import_module("app.routes.users")
sys.modules[__name__ + ".voting"] = import_module("app.routes.voting")
sys.modules[__name__] = _target
