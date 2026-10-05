"""Independently compare issue #49 bodies, routes, registry and entry module."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "5708ab6431b63a541aa256cb5feb980d2aa167ec"
TEST_BASELINE = "36e46765c16d3dc18a37f18237a55cb61d299fef"
MOVED = ("get_current_user", "logout", "withdraw_user", "index")


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def current(path):
    return (ROOT / path).read_text(encoding="utf-8")


def dump(node):
    return ast.dump(node, include_attributes=False)


def statements(source):
    return ast.parse(source).body


def functions(tree):
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def body_source(source, nodes):
    return textwrap.dedent("\n".join(source.splitlines()[nodes[0].lineno - 1:nodes[-1].end_lineno]))


class UnwrapHttp(ast.NodeTransformer):
    def visit_Return(self, node):
        assert isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2
        call = node.value.elts[0]
        assert isinstance(call, ast.Call) and call.func.id == "jsonify" and len(call.args) == 1 and not call.keywords
        node.value.elts[0] = call.args[0]
        return node


def verify_services():
    entry, directory = original("app.py"), original("blueprints/users.py")
    withdraw = functions(ast.parse(entry))["withdraw_user"]
    listing = functions(ast.parse(directory))["get_users_list"]
    source = current("services/users.py")
    tree = ast.parse(source)
    services = functions(tree)
    specs = [("get_directory_dependencies", "", directory, listing.body[:2], "return User, UserStats, asc"),
             ("get_users_list", "search_query, page, User, UserStats, asc", directory, listing.body[4:], ""),
             ("withdraw_user", "user_id", entry, withdraw.body[2:6], "\nreturn None")]
    expected_functions = []
    for name, args, old_source, nodes, suffix in specs:
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = [UnwrapHttp().visit(deepcopy(n)) for n in nodes]
        expected_source = body_source(old_source, nodes).replace("jsonify(", "(")
        if suffix:
            expected.body += statements(suffix)
            expected_source += "\n" + suffix
        assert dump(services[name]) == dump(expected), f"{name}: AST differs"
        assert body_source(source, services[name].body) == expected_source, f"{name}: source differs"
        expected_functions.append(expected)
        print(f"{name}: source and AST match with declared dependency/return adapters")
    header = statements('''
"""User directory queries and withdrawal with original dependency timing."""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import joinedload
from models import User, db
''')
    assert dump(tree) == dump(ast.Module(body=header + expected_functions, type_ignores=[]))
    print("Service imports, SQL, lazy dependencies, paging, datetime and commit preserved")


def blueprint_function(node):
    node = deepcopy(node)
    assert len(node.decorator_list) == 1 and node.decorator_list[0].func.value.id == "app"
    node.decorator_list[0].func.value.id = "bp"
    return node


def verify_routes():
    entry = ast.parse(original("app.py"))
    old = functions(entry)
    account = [blueprint_function(old[n]) for n in MOVED[:3]]
    withdraw = account[2]
    withdraw.body = withdraw.body[:2] + statements('''
error = user_service.withdraw_user(user_id)
if error is not None:
    return jsonify(error[0]), error[1]
''') + withdraw.body[6:]
    header = statements('''
"""Current session, logout and withdrawal routes."""
import os
from flask import jsonify, session
from services import users as user_service
from .legacy import LegacyEndpointBlueprint
bp = LegacyEndpointBlueprint("account", __name__)
''')
    assert dump(ast.parse(current("blueprints/account.py"))) == dump(ast.Module(body=header + account, type_ignores=[]))
    for expected in account[:2]:
        source = original("app.py")
        actual = functions(ast.parse(current("blueprints/account.py")))[expected.name]
        assert body_source(current("blueprints/account.py"), actual.body) == body_source(source, old[expected.name].body)
    core_header = statements('''
"""Basic backend entry route."""
from .legacy import LegacyEndpointBlueprint
bp = LegacyEndpointBlueprint("core", __name__)
''')
    assert dump(ast.parse(current("blueprints/core.py"))) == dump(ast.Module(body=core_header + [blueprint_function(old["index"])], type_ignores=[]))
    directory = ast.parse(original("blueprints/users.py"))
    listing = functions(directory)["get_users_list"]
    listing.body = statements("User, UserStats, asc = user_service.get_directory_dependencies()") + listing.body[2:4] + statements('''
payload, status = user_service.get_users_list(search_query, page, User, UserStats, asc)
return jsonify(payload), status
''')
    directory.body = [n for n in directory.body if not (isinstance(n, ast.ImportFrom) and n.module == "sqlalchemy.orm")]
    for i, n in enumerate(directory.body):
        if isinstance(n, ast.ImportFrom) and n.module == "models":
            directory.body[i:i + 1] = statements("from services import users as user_service")
    assert dump(ast.parse(current("blueprints/users.py"))) == dump(directory)
    print("Account/core/directory route modules match; me/logout bodies, auth, inputs, session and JSON order retained")


def verify_entry_and_registry():
    entry = ast.parse(original("app.py"))
    entry.body = [n for n in entry.body if not (isinstance(n, ast.FunctionDef) and n.name in MOVED)]
    index = next(i for i, n in enumerate(entry.body) if isinstance(n, ast.ImportFrom) and n.module == "blueprints")
    entry.body[index + 1:index + 1] = statements("from blueprints.account import get_current_user, logout, withdraw_user\nfrom blueprints.core import index")
    assert dump(ast.parse(current("app.py"))) == dump(entry)
    registry = ast.parse(original("blueprints/__init__.py"))
    registry.body[1:1] = statements("from .account import bp as account_bp\nfrom .core import bp as core_bp")
    assignment = next(n for n in registry.body if isinstance(n, ast.Assign))
    assignment.value.elts[:0] = [ast.Name(id="account_bp", ctx=ast.Load()), ast.Name(id="core_bp", ctx=ast.Load())]
    assert dump(ast.parse(current("blueprints/__init__.py"))) == dump(registry)
    print("Entire app/registry AST matches: compatibility aliases added, four definitions removed, original factory/CLI/helpers/main retained")


def verify_scope():
    fixture = original("tests/conftest.py").replace("from services import posts as post_service  # noqa: E402\n", "from services import posts as post_service  # noqa: E402\nfrom services import users as user_service  # noqa: E402\n")
    fixture = fixture.replace('        monkeypatch.setattr(app_module, "datetime", FixedDateTime)\n', '        monkeypatch.setattr(app_module, "datetime", FixedDateTime)\n        monkeypatch.setattr(user_service, "datetime", FixedDateTime)\n')
    assert current("tests/conftest.py") == fixture
    path = "tests/test_user_account_service_contract.py"
    expected_test = original(path, TEST_BASELINE).replace("import app as account_routes", "from blueprints import account as account_routes")
    expected_test = expected_test.replace("import app as withdrawal_module", "from services import users as withdrawal_module")
    assert current(path) == expected_test
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in paths:
        if path.endswith(".py") and path not in {"app.py", "blueprints/users.py", "blueprints/__init__.py", "tests/conftest.py"}:
            assert current(path) == original(path), path
    print("Only fake/import connections change; test bodies/expectations and all other existing Python files match")


if __name__ == "__main__":
    verify_services()
    verify_routes()
    verify_entry_and_registry()
    verify_scope()
