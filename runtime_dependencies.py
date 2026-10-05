"""Compatibility alias; implementation lives in app.runtime_dependencies."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.runtime_dependencies")
