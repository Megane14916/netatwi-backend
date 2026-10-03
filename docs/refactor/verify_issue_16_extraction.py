"""Compare lifecycle services/integration and entry adapters with issue #16 baseline."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "77b88fc"
TEST_BASELINE = "cba81c8"


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


def module(nodes):
    return ast.Module(body=nodes, type_ignores=[])


def adapt_returns(nodes):
    tree = module(deepcopy(nodes))
    for node in ast.walk(tree):
        if isinstance(node, ast.Return):
            assert isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2
            call = node.value.elts[0]
            assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "jsonify"
            assert len(call.args) == 1 and not call.keywords
            node.value.elts[0] = call.args[0]
    return tree.body


def copied_body(source, nodes):
    return textwrap.dedent("\n".join(source.splitlines()[nodes[0].lineno - 1:nodes[-1].end_lineno]))


def verify_lifecycle():
    sources = {path: original(path) for path in ("blueprints/admin.py", "blueprints/tasks.py", "cli/process_contests.py")}
    trees = {path: ast.parse(source) for path, source in sources.items()}
    admin = functions(trees["blueprints/admin.py"])
    task = functions(trees["blueprints/tasks.py"])["handle_contest_task"]
    cli = functions(trees["cli/process_contests.py"])["process_contests_command"]
    service_source = current("services/contest_lifecycle.py")
    service_tree = ast.parse(service_source)
    services = functions(service_tree)
    tries = {name: next(n for n in admin[name].body if isinstance(n, ast.Try))
             for name in ("create_contest", "update_contest", "delete_contest")}
    lookup = next(n for n in admin["update_contest"].body if isinstance(n, ast.Assign)
                  and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "contest")
    expected_functions = [deepcopy(admin["schedule_contest_task"])]
    expected_get = ast.parse("def get_contest(id): pass").body[0]
    expected_get.body = [ast.Return(value=deepcopy(lookup.value))]
    expected_functions.append(expected_get)
    assert dump(services["schedule_contest_task"]) == dump(admin["schedule_contest_task"])
    assert dump(services["get_contest"]) == dump(expected_get)
    for name, args, nodes, path, http in (
        ("create_contest", "data", tries["create_contest"].body, "blueprints/admin.py", True),
        ("update_contest", "contest, data", tries["update_contest"].body, "blueprints/admin.py", True),
        ("delete_contest", "id", tries["delete_contest"].body, "blueprints/admin.py", True),
        ("handle_contest_task", "id, event_type", task.body, "blueprints/tasks.py", True),
        ("process_contests", "", cli.body, "cli/process_contests.py", False),
    ):
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = adapt_returns(nodes) if http else deepcopy(nodes)
        assert dump(services[name]) == dump(expected), name
        before_body = copied_body(sources[path], nodes)
        if http:
            before_body = before_body.replace("jsonify(", "(")
        assert before_body == copied_body(service_source, services[name].body), name
        expected_functions.append(expected)
        print(f"{name}: copied source and AST match with explicit HTTP return adapters only")
    assert set(services) == {f.name for f in expected_functions}
    assert ast.get_docstring(service_tree) is not None
    expected_service = module([service_tree.body[0]] + statements('''
from datetime import datetime, timedelta, timezone
from flask import current_app
from models import Contest, Notification, Post, User, Vote, db
from services import results as results_service
''') + expected_functions)
    assert dump(service_tree) == dump(expected_service)

    expected_admin_tree = deepcopy(trees["blueprints/admin.py"])
    for node in expected_admin_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in tries:
            main_try = next(n for n in node.body if isinstance(n, ast.Try))
            call_args = {"create_contest": "data", "update_contest": "contest, data", "delete_contest": "id"}[node.name]
            main_try.body = statements(f"result, status = contest_lifecycle.{node.name}({call_args})\nreturn jsonify(result), status")
            if node.name == "update_contest":
                found = next(n for n in node.body if isinstance(n, ast.Assign)
                             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "contest")
                found.value = ast.parse("contest_lifecycle.get_contest(id)", mode="eval").body
    index = next(i for i, n in enumerate(expected_admin_tree.body) if isinstance(n, ast.ImportFrom) and n.module == "models")
    expected_admin_tree.body[index:index + 1] = statements("from models import Contest, db\nfrom services import contest_lifecycle")
    assert dump(ast.parse(current("blueprints/admin.py"))) == dump(expected_admin_tree)
    print("Admin auth/inputs/responses/exception boundaries, management and scheduling seam match")

    expected_task_tree = deepcopy(trees["blueprints/tasks.py"])
    expected_task_tree.body = [n for n in expected_task_tree.body if not (
        isinstance(n, ast.ImportFrom) and n.module in {"datetime", "models"})]
    for node in expected_task_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "services":
            node.names = [ast.alias(name="contest_lifecycle")]
        if isinstance(node, ast.FunctionDef):
            node.body = statements("result, status = contest_lifecycle.handle_contest_task(id, event_type)\nreturn jsonify(result), status")
    assert dump(ast.parse(current("blueprints/tasks.py"))) == dump(expected_task_tree)

    expected_cli_tree = deepcopy(trees["cli/process_contests.py"])
    expected_cli_tree.body = [n for n in expected_cli_tree.body if not (
        isinstance(n, ast.ImportFrom) and n.module in {"datetime", "models"})]
    for node in expected_cli_tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "services":
            node.names = [ast.alias(name="contest_lifecycle")]
        if isinstance(node, ast.FunctionDef):
            node.body = deepcopy(node.body[:1]) + statements("return contest_lifecycle.process_contests()")
    assert dump(ast.parse(current("cli/process_contests.py"))) == dump(expected_cli_tree)
    print("Task route and CLI signatures, decorators, JSON conversion and CLI docstring match")


def verify_cloud_tasks():
    before_source = original("app.py")
    before_tree = ast.parse(before_source)
    before = functions(before_tree)["schedule_contest_task"]
    integration_source = current("integrations/cloud_tasks.py")
    integration_tree = ast.parse(integration_source)
    integration = functions(integration_tree)["schedule_contest_task"]
    assert dump(integration) == dump(before)
    assert ast.get_source_segment(integration_source, integration) == ast.get_source_segment(before_source, before)
    cache = next(n for n in before_tree.body if isinstance(n, ast.Assign)
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "_cloud_tasks_client")
    expected_integration = module([integration_tree.body[0]] + statements('''
import os
from datetime import datetime, timedelta, timezone
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
''') + [deepcopy(cache), deepcopy(before)])
    assert dump(integration_tree) == dump(expected_integration)

    expected_app = deepcopy(before_tree)
    expected_app.body = [n for n in expected_app.body if not (
        (isinstance(n, ast.ImportFrom) and n.module in {"google.cloud", "google.protobuf"}) or
        (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "_cloud_tasks_client"))]
    index = next(i for i, n in enumerate(expected_app.body) if isinstance(n, ast.ImportFrom) and n.module == "integrations")
    expected_app.body[index + 1:index + 1] = statements("from integrations import cloud_tasks")
    scheduler = functions(expected_app)["schedule_contest_task"]
    scheduler.body = statements("return cloud_tasks.schedule_contest_task(contest_id, event_type, schedule_time)")
    assert dump(ast.parse(current("app.py"))) == dump(expected_app)
    print("Cloud Tasks function source/AST and lazy cache match; app.py compatibility and other statements match")


def verify_fakes():
    expected = original("tests/conftest.py").replace(
        "from blueprints import tasks as task_routes", "from services import contest_lifecycle"
    ).replace("from cli import process_contests as contest_cli  # noqa: E402\n", "").replace(
        "from integrations import x_oauth", "from integrations import cloud_tasks, x_oauth"
    ).replace('monkeypatch.setattr(task_routes, "datetime", FixedDateTime)',
              'monkeypatch.setattr(contest_lifecycle, "datetime", FixedDateTime)').replace(
        'monkeypatch.setattr(contest_cli, "datetime", FixedDateTime)',
        'monkeypatch.setattr(cloud_tasks, "datetime", FixedDateTime)').replace(
        'monkeypatch.setattr(app_module, "_cloud_tasks_client", client)',
        'monkeypatch.setattr(cloud_tasks, "_cloud_tasks_client", client)')
    assert dump(ast.parse(current("tests/conftest.py"))) == dump(ast.parse(expected))
    path = "tests/test_contest_lifecycle_contract.py"
    expected = original(path, TEST_BASELINE).replace("import app as app_module\n",
        "import app as app_module\nfrom integrations import cloud_tasks\n", 1).replace(
        "scheduler_module = app_module", "scheduler_module = cloud_tasks")
    assert dump(ast.parse(current(path))) == dump(ast.parse(expected))
    print("Tests change only lifecycle/integration clock and cached-client fake targets")


if __name__ == "__main__":
    verify_lifecycle()
    verify_cloud_tasks()
    verify_fakes()
