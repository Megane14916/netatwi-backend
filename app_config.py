"""Compatibility alias; implementation lives in app.config."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.config")
