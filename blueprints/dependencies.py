"""Call helpers retained in app.py while route groups are being moved."""

from flask import current_app


def _call(name, *args):
    return current_app.extensions["legacy_route_helpers"][name](*args)


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
