"""Compatibility alias; implementation lives in app.integrations.x_oauth."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.integrations.x_oauth")
