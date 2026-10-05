"""Reproduce issue #49 from fixed AST line ranges and original source.

Default compares generated whole files. --write is only for reproducing
this extraction, not for overwriting subsequent refactors.
"""

import argparse
import ast
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "5708ab6431b63a541aa256cb5feb980d2aa167ec"
TEST_BASELINE = "36e46765c16d3dc18a37f18237a55cb61d299fef"


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def functions(source):
    return {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}


def copy(source, nodes):
    return textwrap.dedent("\n".join(source.splitlines()[nodes[0].lineno - 1:nodes[-1].end_lineno])) + "\n"


def replace(source, nodes, body, indent):
    lines = source.splitlines(keepends=True)
    lines[nodes[0].lineno - 1:nodes[-1].end_lineno] = [textwrap.indent(body, " " * indent)]
    return "".join(lines)


def function(name, args, body):
    return f"def {name}({args}):\n" + textwrap.indent(body, "    ")


def moved_route(source, node):
    start = min(n.lineno for n in node.decorator_list) - 1
    lines = source.splitlines(keepends=True)
    return "".join(lines[start:node.end_lineno]).replace("@app.route(", "@bp.route(", 1)


def generate():
    entry = original("app.py")
    directory = original("blueprints/users.py")
    routes = functions(entry)
    listing = functions(directory)["get_users_list"]
    withdrawal = routes["withdraw_user"]
    assert [n.module for n in listing.body[:2]] == ["models", "sqlalchemy"]
    assert ast.get_source_segment(entry, withdrawal.body[6]) == "session.clear()"
    service = '''"""User directory queries and withdrawal with original dependency timing."""

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import joinedload
from models import User, db


'''
    service += function("get_directory_dependencies", "", copy(directory, listing.body[:2]) + "return User, UserStats, asc\n")
    service += "\n\n" + function("get_users_list", "search_query, page, User, UserStats, asc",
                                copy(directory, listing.body[4:]).replace("jsonify(", "("))
    service += "\n\n" + function("withdraw_user", "user_id",
                                copy(entry, withdrawal.body[2:6]).replace("jsonify(", "(") + "\nreturn None\n")
    adapter = "User, UserStats, asc = user_service.get_directory_dependencies()\n\n"
    adapter += copy(directory, listing.body[2:4])
    adapter += '''payload, status = user_service.get_users_list(search_query, page, User, UserStats, asc)
return jsonify(payload), status
'''
    directory = replace(directory, listing.body, adapter, 4)
    directory = directory.replace("from sqlalchemy.orm import joinedload\n", "")
    directory = directory.replace("from models import db", "from services import users as user_service")
    account = '''"""Current session, logout and withdrawal routes."""

import os

from flask import jsonify, session
from services import users as user_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("account", __name__)


'''
    account += moved_route(entry, routes["get_current_user"]) + "\n\n"
    account += moved_route(entry, routes["logout"]) + "\n\n"
    withdrawal_source = replace(entry, withdrawal.body[2:6], '''error = user_service.withdraw_user(user_id)
if error is not None:
    return jsonify(error[0]), error[1]
''', 4)
    account += moved_route(withdrawal_source, functions(withdrawal_source)["withdraw_user"])
    core = '''"""Basic backend entry route."""

from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("core", __name__)


# --- Mock API Endpoints ---
''' + moved_route(entry, routes["index"])
    lines = entry.splitlines(keepends=True)
    for node in sorted([routes[n] for n in ("get_current_user", "logout", "withdraw_user", "index")], key=lambda n: n.lineno, reverse=True):
        start = min(n.lineno for n in node.decorator_list) - 1
        del lines[start:node.end_lineno]
    entry = "".join(lines).replace("# --- Mock API Endpoints ---\n", "")
    entry = entry.replace("from blueprints import BLUEPRINTS\n", "from blueprints import BLUEPRINTS\nfrom blueprints.account import get_current_user, logout, withdraw_user\nfrom blueprints.core import index\n")
    registry = original("blueprints/__init__.py").replace("from .admin import bp as admin_bp", "from .account import bp as account_bp\nfrom .core import bp as core_bp\nfrom .admin import bp as admin_bp")
    registry = registry.replace("BLUEPRINTS = (\n", "BLUEPRINTS = (\n    account_bp,\n    core_bp,\n")
    fixture = original("tests/conftest.py").replace("from services import posts as post_service  # noqa: E402\n", "from services import posts as post_service  # noqa: E402\nfrom services import users as user_service  # noqa: E402\n")
    fixture = fixture.replace('        monkeypatch.setattr(app_module, "datetime", FixedDateTime)\n', '        monkeypatch.setattr(app_module, "datetime", FixedDateTime)\n        monkeypatch.setattr(user_service, "datetime", FixedDateTime)\n')
    test = original("tests/test_user_account_service_contract.py", TEST_BASELINE)
    test = test.replace("import app as account_routes", "from blueprints import account as account_routes")
    test = test.replace("import app as withdrawal_module", "from services import users as withdrawal_module")
    return {"services/users.py": service, "blueprints/users.py": directory,
            "blueprints/account.py": account, "blueprints/core.py": core,
            "app.py": entry, "blueprints/__init__.py": registry,
            "tests/conftest.py": fixture, "tests/test_user_account_service_contract.py": test}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    for path, source in generate().items():
        ast.parse(source)
        if args.write:
            with (ROOT / path).open("w", encoding="utf-8", newline="\n") as output:
                output.write(source)
        else:
            assert (ROOT / path).read_text(encoding="utf-8") == source, path
        print(f"{path}: {'written from baseline slices' if args.write else 'whole source matches'}")
