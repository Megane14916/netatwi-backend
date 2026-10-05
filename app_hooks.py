"""Compatibility alias; implementation lives in app.hooks."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.hooks")
