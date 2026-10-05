"""Compatibility alias; implementation lives in app.integrations.images."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.integrations.images")
