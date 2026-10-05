"""Application-scoped helper callbacks shared by services and routes."""

from flask import current_app
from werkzeug.local import LocalProxy


def _call(name, *args):
    return current_app.extensions["legacy_route_helpers"][name](*args)


# Resolve the original logger at request time, including when app.py runs as
# __main__ or an integration replaces app.logger.
route_logger = LocalProxy(lambda: _call("get_route_logger"))


def allowed_file(filename):
    return _call("allowed_file", filename)


def calculate_weighted_length(text):
    return _call("calculate_weighted_length", text)


def save_file(file):
    return _call("save_file", file)


def delete_file(file_url):
    return _call("delete_file", file_url)


def get_cached_contest_results(contest_id):
    return _call("get_cached_contest_results", contest_id)


def generate_contest_results(contest_id):
    return _call("generate_contest_results", contest_id)


def schedule_contest_task(*args):
    return current_app.extensions["schedule_contest_task"](*args)


def register_helper_bindings(application, namespace):
    # Keep the original app globals live, including the __main__ namespace.
    application.extensions["schedule_contest_task"] = (
        lambda *args: namespace["schedule_contest_task"](*args)
    )
    application.extensions["legacy_route_helpers"] = {
        "get_route_logger": lambda: namespace["logger"],
        "allowed_file": lambda *args: namespace["allowed_file"](*args),
        "calculate_weighted_length": lambda *args: namespace["calculate_weighted_length"](*args),
        "save_file": lambda *args: namespace["save_file"](*args),
        "delete_file": lambda *args: namespace["delete_file"](*args),
        "get_cached_contest_results": lambda *args: namespace["get_cached_contest_results"](*args),
        "generate_contest_results": lambda *args: namespace["generate_contest_results"](*args),
    }
