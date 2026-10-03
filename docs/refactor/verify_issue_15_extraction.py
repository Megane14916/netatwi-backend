"""Compare result services and caller bindings with pre-issue-15 master."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "bd07352"
HELPERS = ("generate_contest_results", "get_cached_contest_results")


def original(path):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT).decode("utf-8")


def current(path):
    return (ROOT / path).read_text(encoding="utf-8")


def dump(node):
    return ast.dump(node, include_attributes=False)


def statements(source):
    return ast.parse(source).body


def functions(tree):
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def jsonify_call(value):
    assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "jsonify"
    assert len(value.args) == 1 and not value.keywords
    return value.args[0]


def adapt_returns(nodes):
    tree = ast.Module(body=deepcopy(nodes), type_ignores=[])
    for node in ast.walk(tree):
        if isinstance(node, ast.Return):
            if isinstance(node.value, ast.Tuple):
                assert len(node.value.elts) == 2
                node.value.elts[0] = jsonify_call(node.value.elts[0])
            else:
                node.value = ast.Tuple(elts=[jsonify_call(node.value), ast.Constant(value=200)], ctx=ast.Load())
    return tree.body


def verify_services_and_app():
    app_source = original("app.py")
    app_tree = ast.parse(app_source)
    before = functions(app_tree)
    route_source = original("blueprints/results.py")
    route_tree = ast.parse(route_source)
    route = functions(route_tree)["get_contest_results"]
    service_source = current("services/results.py")
    service_tree = ast.parse(service_source)
    services = functions(service_tree)
    assert set(services) == set(HELPERS) | {"get_contest_results"}

    for name in HELPERS:
        assert dump(services[name]) == dump(before[name]), name
        assert ast.get_source_segment(service_source, services[name]) == ast.get_source_segment(app_source, before[name]), name
        print(f"{name}: complete function source and AST match")

    nodes = route.body[0].body[1:]
    expected_get = ast.parse("def get_contest_results(id, user_id): pass").body[0]
    expected_get.body = adapt_returns(nodes)
    assert dump(services["get_contest_results"]) == dump(expected_get)
    lines = route_source.splitlines(keepends=True)
    copied = lines[nodes[0].lineno - 1:nodes[-1].end_lineno].copy()
    returns = sorted((n for n in ast.walk(ast.Module(body=nodes, type_ignores=[])) if isinstance(n, ast.Return)),
                     key=lambda n: n.lineno, reverse=True)
    for node in returns:
        replacement = "".join(lines[node.lineno - 1:node.end_lineno]).replace("jsonify(", "(", 1)
        if isinstance(node.value, ast.Call):
            replacement = replacement.rstrip() + ", 200\n"
        start = nodes[0].lineno
        copied[node.lineno - start:node.end_lineno - start + 1] = [replacement]
    actual = services["get_contest_results"]
    actual_source = "".join(service_source.splitlines(keepends=True)[actual.body[0].lineno - 1:actual.end_lineno])
    assert textwrap.dedent("".join(copied)) == textwrap.dedent(actual_source)
    print("get_contest_results: body source and AST match with explicit HTTP return adapters only")

    assert ast.get_docstring(service_tree) is not None
    expected_service = ast.Module(body=[service_tree.body[0]] + statements('''
from datetime import datetime, timedelta, timezone
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import joinedload
from models import Bookmark, Comment, Contest, ContestResult, Post, User, Vote, db
JST = timezone(timedelta(hours=9), "JST")
''') + [deepcopy(before[name]) for name in HELPERS] + [expected_get], type_ignores=[])
    assert dump(service_tree) == dump(expected_service)
    old_jst = next(n for n in route_tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "JST")
    new_jst = next(n for n in service_tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "JST")
    assert dump(old_jst) == dump(new_jst)

    current_app_tree = ast.parse(current("app.py"))
    current_app_functions = functions(current_app_tree)
    for name in HELPERS:
        expected = deepcopy(before[name])
        expected.body = deepcopy(before[name].body[:1]) + statements(f"return results_service.{name}(contest_id)")
        assert dump(current_app_functions[name]) == dump(expected), name
    expected_app = deepcopy(app_tree)
    expected_app.body = [current_app_functions[n.name] if isinstance(n, ast.FunctionDef) and n.name in HELPERS else n
                         for n in expected_app.body]
    expected_app.body = [n for n in expected_app.body if not (isinstance(n, ast.ImportFrom) and n.module == "sqlalchemy")]
    index = next(i for i, n in enumerate(expected_app.body) if isinstance(n, ast.ImportFrom) and n.module == "app_factory")
    expected_app.body[index + 1:index + 1] = statements("from services import results as results_service")
    assert dump(current_app_tree) == dump(expected_app)
    print("app.py compatibility wrappers, all other statements and initialization order match")

    expected_route = deepcopy(route)
    expected_route.body[0].body = deepcopy(route.body[0].body[:1]) + statements('''
result, status = results_service.get_contest_results(id, user_id)
return jsonify(result), status
''')
    expected_route_tree = deepcopy(route_tree)
    adapted = []
    for node in expected_route_tree.body:
        if isinstance(node, ast.FunctionDef):
            adapted.append(expected_route)
        elif isinstance(node, ast.ImportFrom) and node.module in {"datetime", "sqlalchemy.orm", "dependencies"}:
            continue
        elif isinstance(node, ast.ImportFrom) and node.module == "models":
            adapted += statements("from services import results as results_service")
        elif isinstance(node, ast.Assign) and node.targets[0].id == "JST":
            continue
        else:
            adapted.append(node)
    expected_route_tree.body = adapted
    assert dump(ast.parse(current("blueprints/results.py"))) == dump(expected_route_tree)
    print("Result route signature, decorator, session input, JSON conversion and exception handler match")


def verify_callers_and_fakes():
    class QualifyServiceCalls(ast.NodeTransformer):
        def __init__(self, name):
            self.name = name

        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == self.name:
                node.func = ast.Attribute(value=ast.Name(id="results_service", ctx=ast.Load()), attr=self.name, ctx=ast.Load())
            return node

    for path, module, name in (
        ("blueprints/tasks.py", "dependencies", "generate_contest_results"),
        ("cli/process_contests.py", "blueprints.dependencies", "generate_contest_results"),
        ("blueprints/profile.py", "dependencies", "get_cached_contest_results"),
    ):
        expected = ast.parse(original(path))
        index = next(i for i, n in enumerate(expected.body) if isinstance(n, ast.ImportFrom) and n.module == module)
        expected.body[index:index + 1] = statements("from services import results as results_service")
        expected = QualifyServiceCalls(name).visit(expected)
        assert dump(ast.parse(current(path))) == dump(expected), path
        print(f"{path}: only import and shared-service call binding changed")

    expected_fixture = original("tests/conftest.py").replace(
        "from blueprints import results as result_routes", "from services import results as results_service"
    ).replace('monkeypatch.setattr(result_routes, "datetime", FixedDateTime)',
              'monkeypatch.setattr(results_service, "datetime", FixedDateTime)')
    assert dump(ast.parse(current("tests/conftest.py"))) == dump(ast.parse(expected_fixture))
    expected_contract = original("tests/test_tasks_cli_contract.py").replace(
        "import app as app_module\n", "import app as app_module\nfrom services import results as results_service\n", 1
    ).replace('wrap(app_module, "generate_contest_results", "generate")',
              'wrap(results_service, "generate_contest_results", "generate")'
    ).replace('monkeypatch.setattr(app_module, "generate_contest_results", fail_generation)',
              'monkeypatch.setattr(results_service, "generate_contest_results", fail_generation)')
    assert dump(ast.parse(current("tests/test_tasks_cli_contract.py"))) == dump(ast.parse(expected_contract))
    print("Existing tests change only the clock and generation fake targets")


if __name__ == "__main__":
    verify_services_and_app()
    verify_callers_and_fakes()
