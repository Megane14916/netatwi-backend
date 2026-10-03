"""Compare voting extraction against master immediately before issue #14."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "8160b94"


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


def adapt_returns(nodes):
    tree = ast.Module(body=deepcopy(nodes), type_ignores=[])
    for node in ast.walk(tree):
        if isinstance(node, ast.Return):
            assert isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2
            call = node.value.elts[0]
            assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "jsonify"
            assert len(call.args) == 1 and not call.keywords
            node.value.elts[0] = call.args[0]
    return tree.body


def verify():
    before_source = original("blueprints/voting.py")
    before_tree = ast.parse(before_source)
    before = functions(before_tree)["submit_votes"]
    route_tree = ast.parse(current("blueprints/voting.py"))
    routes = functions(route_tree)
    service_source = current("services/voting.py")
    service_tree = ast.parse(service_source)
    services = functions(service_tree)
    main_try = next(n for n in before.body if isinstance(n, ast.Try))
    validation_index = next(i for i, n in enumerate(before.body)
                            if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "content")
    try_index = before.body.index(main_try)
    validation = before.body[validation_index:try_index]
    business = main_try.body[3:]

    expected_services = []
    for name, args, nodes, suffix in (
        ("validate_votes", "content, votes_to_submit", validation, "return None"),
        ("submit_votes", "id, user_id, votes_to_submit, judge_award, is_judge, is_judge_voting_now, start_time",
         business, ""),
    ):
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = adapt_returns(nodes) + statements(suffix)
        assert dump(services[name]) == dump(expected), name
        expected_services.append(expected)

        # Check copied source, including comments, with only jsonify removal and
        # the explicit successful validation return allowed.
        copied_source = textwrap.dedent("\n".join(before_source.splitlines()[nodes[0].lineno - 1:nodes[-1].end_lineno]))
        copied_source = copied_source.replace("jsonify(", "(")
        if suffix:
            copied_source += "\n\n" + suffix
        actual = services[name]
        actual_source = textwrap.dedent("\n".join(service_source.splitlines()[actual.body[0].lineno - 1:actual.end_lineno]))
        assert copied_source == actual_source, name
        print(f"{name}: copied source and AST match with explicit return adapters only")

    assert set(services) == {"validate_votes", "submit_votes"}
    assert ast.get_docstring(service_tree) is not None
    expected_service_tree = ast.Module(body=[service_tree.body[0]] + statements('''
import time
from datetime import datetime, timezone
from blueprints.dependencies import calculate_weighted_length, route_logger as logger
from models import Contest, Post, Vote, db
''') + expected_services, type_ignores=[])
    assert dump(service_tree) == dump(expected_service_tree)

    expected_route = deepcopy(before)
    adapted_try = deepcopy(main_try)
    adapted_try.body = deepcopy(main_try.body[:3]) + statements('''
result, status = voting_service.submit_votes(
    id, user_id, votes_to_submit, judge_award, is_judge, is_judge_voting_now, start_time
)
return jsonify(result), status
''')
    expected_route.body = deepcopy(before.body[:validation_index]) + statements('''
error = voting_service.validate_votes(content, votes_to_submit)
if error is not None:
    return jsonify(error[0]), error[1]
''') + [adapted_try]
    assert set(routes) == {"submit_votes"}
    assert dump(routes["submit_votes"]) == dump(expected_route)

    expected_tree = deepcopy(before_tree)
    adapted_body = []
    for node in expected_tree.body:
        if isinstance(node, ast.FunctionDef):
            adapted_body.append(expected_route)
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            continue
        elif isinstance(node, ast.ImportFrom) and node.module == "models":
            adapted_body += statements("from models import db\nfrom services import voting as voting_service")
        elif isinstance(node, ast.ImportFrom) and node.module == "dependencies":
            node.names = [n for n in node.names if n.name != "calculate_weighted_length"]
            adapted_body.append(node)
        else:
            adapted_body.append(node)
    expected_tree.body = adapted_body
    assert dump(route_tree) == dump(expected_tree)
    print("Route signature, decorator, JSON/form/session reads, responses, logs and exception handler match")

    assert dump(ast.parse(original("app.py"))) == dump(ast.parse(current("app.py")))
    before_fixture = original("tests/conftest.py").replace(
        "from blueprints import voting as voting_routes", "from services import voting as voting_service"
    ).replace('monkeypatch.setattr(voting_routes, "datetime", FixedDateTime)',
              'monkeypatch.setattr(voting_service, "datetime", FixedDateTime)')
    assert dump(ast.parse(before_fixture)) == dump(ast.parse(current("tests/conftest.py")))
    print("app.py is unchanged; fixture changes only the voting clock replacement target")


if __name__ == "__main__":
    verify()
