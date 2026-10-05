"""Compatibility alias; implementation lives in app.services.contest_lifecycle."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.services.contest_lifecycle")
