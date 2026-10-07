"""HTTP input errors and JSON object parsing shared by validated endpoints."""

from flask import request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType


class InputError(ValueError):
    pass


def json_object():
    try:
        data = request.get_json()
    except (BadRequest, UnsupportedMediaType) as error:
        raise InputError("Expected a JSON object") from error
    if not isinstance(data, dict):
        raise InputError("Expected a JSON object")
    return data


def positive_id(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise InputError("Invalid ID")
    number = int(value)
    if not 0 < number < 2**31:
        raise InputError("Invalid ID")
    return number
