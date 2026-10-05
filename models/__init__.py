"""Compatibility alias for app.models; no processing bodies live here."""

from importlib import import_module
import sys

_target = import_module("app.models")
sys.modules[__name__ + ".base"] = import_module("app.models.base")
sys.modules[__name__ + ".bookmark"] = import_module("app.models.bookmark")
sys.modules[__name__ + ".comment"] = import_module("app.models.comment")
sys.modules[__name__ + ".contest"] = import_module("app.models.contest")
sys.modules[__name__ + ".contest_result"] = import_module("app.models.contest_result")
sys.modules[__name__ + ".news"] = import_module("app.models.news")
sys.modules[__name__ + ".notification"] = import_module("app.models.notification")
sys.modules[__name__ + ".post"] = import_module("app.models.post")
sys.modules[__name__ + ".user"] = import_module("app.models.user")
sys.modules[__name__ + ".user_stats"] = import_module("app.models.user_stats")
sys.modules[__name__ + ".vote"] = import_module("app.models.vote")
sys.modules[__name__] = _target
