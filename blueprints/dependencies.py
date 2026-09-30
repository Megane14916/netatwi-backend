"""Call helpers retained in app.py while route groups are being moved."""

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
