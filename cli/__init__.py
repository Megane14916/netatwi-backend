"""Compatibility alias for app.cli; no processing bodies live here."""

from importlib import import_module
import sys

_target = import_module("app.cli")
sys.modules[__name__ + ".process_contests"] = import_module("app.cli.process_contests")
sys.modules[__name__ + ".user_stats"] = import_module("app.cli.user_stats")
sys.modules[__name__] = _target
