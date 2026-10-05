"""Compatibility alias; implementation lives in app.services.user_stats."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.services.user_stats")
