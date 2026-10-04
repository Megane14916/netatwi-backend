"""Compare issue #45's source, AST, cache and HTTP boundaries with baseline."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "4f6f70c05b3455f80927cbedc9979e58bda23248"
TEST_BASELINE = "a5bbf9950f4f3d055d335edb65139b8ab0490dbc"


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


class UnwrapHttpReturn(ast.NodeTransformer):
    def visit_Return(self, node):
        call = node.value
        assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "jsonify"
        assert len(call.args) == 1 and not call.keywords
        node.value = call.args[0]
        return node


def verify_services():
    public_source = original("blueprints/contests.py")
    admin_source = original("blueprints/admin.py")
    public_tree = ast.parse(public_source)
    public = functions(public_tree)
    listing, details = public["get_contests"], public["get_contest_details"]
    management = functions(ast.parse(admin_source))["get_management_contests"]
    service_source = current("services/contests.py")
    service_tree = ast.parse(service_source)
    services = functions(service_tree)
    specs = [
        ("get_cached_contests", "time", public_source, listing.body[2:3], listing.body[:1], "", ""),
        ("get_contests", "time", public_source, listing.body[-1].body, listing.body[:1], "", ""),
        ("get_contest_for_details", "id, start_time, time", public_source, details.body[-1].body[:3], [], "", "return contest"),
        ("get_contest_details", "contest, user_id, start_time, time", public_source, details.body[-1].body[4:], [], "", ""),
        ("get_management_contests", "", admin_source, management.body[-1].body, [], "", ""),
    ]
    expected_functions = []
    for name, args, source, nodes, prefix_nodes, prefix, suffix in specs:
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = deepcopy(prefix_nodes + nodes)
        assert not any(isinstance(n, ast.FunctionDef) for statement in nodes for n in ast.walk(statement))
        expected = UnwrapHttpReturn().visit(expected)
        expected_source = body_source(source, nodes).replace("jsonify(", "(")
        if prefix_nodes:
            expected_source = body_source(source, prefix_nodes) + "\n" + expected_source
        if name == "get_cached_contests":
            cache_return = expected.body[-1].body[0]
            assert isinstance(cache_return, ast.Return) and isinstance(cache_return.value, ast.Name)
            cache_return.value = ast.Tuple(elts=[ast.Constant(value=True), cache_return.value], ctx=ast.Load())
            expected.body += statements("return False, None")
            expected_source = expected_source.replace("return (_contests_cache)", "return True, _contests_cache") + "\nreturn False, None"
        if prefix:
            expected.body = statements(prefix) + expected.body
            expected_source = prefix + "\n\n" + expected_source
        if suffix:
            expected.body += statements(suffix)
            expected_source += "\n" + suffix
        assert dump(services[name]) == dump(expected), f"{name}: AST differs"
        assert body_source(service_source, services[name].body) == expected_source, f"{name}: source differs"
        expected_functions.append(expected)
        print(f"{name}: source and AST match with declared boundary adapters")
    constants = [deepcopy(n) for n in public_tree.body if isinstance(n, ast.Assign) and n.targets[0].id != "bp"]
    expected_tree = ast.Module(body=statements('''
"""Public and management contest queries with the original shared cache."""
import logging
from datetime import datetime, timedelta, timezone
from models import Contest, ContestResult
''') + constants + expected_functions, type_ignores=[])
    assert dump(service_tree) == dump(expected_tree)
    print("Service imports, logger, JST and cache initial values match; one shared cache is retained")


def verify_routes():
    public_tree = ast.parse(original("blueprints/contests.py"))
    public = functions(public_tree)
    listing, details = public["get_contests"], public["get_contest_details"]
    original_try = listing.body[-1]
    original_try.body = statements("return jsonify(contest_service.get_contests(time))")
    listing.body = listing.body[1:2] + statements('''
cache_hit, cached = contest_service.get_cached_contests(time)
if cache_hit:
    return jsonify(cached)
''') + [original_try]
    detail_try = details.body[-1]
    detail_try.body = statements("contest = contest_service.get_contest_for_details(id, start_time, time)") + detail_try.body[3:4] + statements(
        "return jsonify(contest_service.get_contest_details(contest, user_id, start_time, time))"
    )
    public_tree.body = [n for n in public_tree.body if not (
        isinstance(n, ast.Import) and any(alias.name == "logging" for alias in n.names)
        or isinstance(n, ast.ImportFrom) and n.module == "datetime"
        or isinstance(n, ast.Assign) and n.targets[0].id != "bp"
    )]
    for i, node in enumerate(public_tree.body):
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            public_tree.body[i:i + 1] = statements("from services import contests as contest_service")
    assert dump(ast.parse(current("blueprints/contests.py"))) == dump(public_tree)
    print("Public routes match: cache hit outside try, miss inside try, timing origin, session input and exception handlers")

    admin_tree = ast.parse(original("blueprints/admin.py"))
    functions(admin_tree)["get_management_contests"].body[-1].body = statements(
        "return jsonify(contest_service.get_management_contests())"
    )
    admin_tree.body = [n for n in admin_tree.body if not (
        isinstance(n, ast.ImportFrom) and n.module == "datetime"
        or isinstance(n, ast.Assign) and n.targets[0].id == "JST"
    )]
    for node in admin_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            node.names = [n for n in node.names if n.name == "db"]
    index = next(i for i, n in enumerate(admin_tree.body) if isinstance(n, ast.ImportFrom) and n.module == "services")
    admin_tree.body[index + 1:index + 1] = statements("from services import contests as contest_service")
    assert dump(ast.parse(current("blueprints/admin.py"))) == dump(admin_tree)
    print("Admin module matches: auth and JSON/exception boundary retained; create/update/delete unchanged")


def verify_scope():
    expected = original("tests/conftest.py").replace("from blueprints import admin as admin_routes  # noqa: E402\n", "")
    expected = expected.replace("from blueprints import contests as contest_routes", "from services import contests as contest_service")
    expected = expected.replace("contest_routes", "contest_service").replace('        monkeypatch.setattr(admin_routes, "datetime", FixedDateTime)\n', "")
    assert current("tests/conftest.py") == expected
    path = "tests/test_contest_query_service_contract.py"
    expected_test = original(path, TEST_BASELINE).replace("from blueprints import contests as query_module", "from services import contests as query_module")
    assert current(path) == expected_test
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in paths:
        if path.endswith(".py") and path not in {"blueprints/contests.py", "blueprints/admin.py", "tests/conftest.py"}:
            assert current(path) == original(path), path
    print("Only cache/clock fake connections change; test bodies and every other existing Python file match")


if __name__ == "__main__":
    verify_services()
    verify_routes()
    verify_scope()
