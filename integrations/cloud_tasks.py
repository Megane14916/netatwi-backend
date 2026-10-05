"""Compatibility alias; implementation lives in app.integrations.cloud_tasks."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("app.integrations.cloud_tasks")
