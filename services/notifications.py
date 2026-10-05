"""Compatibility alias; implementation lives in app.services.notifications."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.services.notifications")
