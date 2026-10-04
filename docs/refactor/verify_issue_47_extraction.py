"""Independently compare issue #47 source, AST, nested helpers and adapters."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "b523da12e4d7650329b3e21d217578122ed79221"
TEST_BASELINE = "fed9d0657709e0d56d759a0e8dd16a44d02248c5"


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


def unwrap(call):
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "jsonify"
    assert len(call.args) == 1 and not call.keywords
    return call.args[0]


def verify_services():
    source = original("blueprints/profile.py")
    tree = ast.parse(source)
    block = functions(tree)["get_user_profile_updated"].body[0]
    service_source = current("services/profile.py")
    service_tree = ast.parse(service_source)
    services = functions(service_tree)
    expected_functions = []
    specs = [("prepare_profile_timing", "time", block.body[1:4]),
             ("get_user_profile", "screen_name, viewer_id, log_step", block.body[5:])]
    for name, args, nodes in specs:
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = deepcopy(nodes)
        expected_source = body_source(source, nodes)
        if name == "prepare_profile_timing":
            expected.body += statements("return log_step")
            expected_source += "\nreturn log_step"
        else:
            # Adapt only the two original HTTP returns, never nested helper returns.
            not_found = expected.body[2]
            assert isinstance(not_found, ast.If) and len(not_found.body) == 1
            ret = not_found.body[0]
            assert isinstance(ret, ast.Return) and isinstance(ret.value, ast.Tuple)
            assert ret.value.elts[1].value == 404
            ret.value.elts[0] = unwrap(ret.value.elts[0])
            final = expected.body[-1]
            assert isinstance(final, ast.Return)
            final.value = ast.Tuple(elts=[unwrap(final.value), ast.Constant(value=200)], ctx=ast.Load())
            expected_source = expected_source.replace('return jsonify({"error": "Not found"}), 404', 'return ({"error": "Not found"}), 404')
            expected_source = expected_source.replace("return jsonify(res_json)", "return res_json, 200")
        assert dump(services[name]) == dump(expected), f"{name}: AST differs"
        assert body_source(service_source, services[name].body) == expected_source, f"{name}: source differs"
        expected_functions.append(expected)
        print(f"{name}: original source and AST match with declared boundary adapters")
    header = statements('"""Profile queries, visibility and presentation with original result reuse."""')
    imports = [deepcopy(n) for n in tree.body if isinstance(n, ast.ImportFrom) and n.module in (
        "datetime", "sqlalchemy.orm", "models", "services")]
    constants = [deepcopy(n) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "JST"]
    assert dump(service_tree) == dump(ast.Module(body=header + imports + constants + expected_functions, type_ignores=[]))
    print("Imports, JST, SQL, results-service resolution and all nested helper bodies match")


def verify_routes():
    tree = ast.parse(original("blueprints/profile.py"))
    block = functions(tree)["get_user_profile_updated"].body[0]
    block.body = block.body[:1] + statements("log_step = profile_service.prepare_profile_timing(time)") + block.body[4:5] + statements('''
payload, status = profile_service.get_user_profile(screen_name, viewer_id, log_step)
return jsonify(payload), status
''')
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.ImportFrom) and n.module in ("datetime", "sqlalchemy.orm", "models")
        or isinstance(n, ast.Assign) and n.targets[0].id == "JST"
    )]
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.ImportFrom) and node.module == "services":
            tree.body[i:i + 1] = statements("from services import profile as profile_service")
    assert dump(ast.parse(current("blueprints/profile.py"))) == dump(tree)
    print("Whole route matches: original time import/try, timing before session, JSON/status, decorator and except/traceback")


def verify_scope():
    fixture = original("tests/conftest.py").replace("from blueprints import profile as profile_routes", "from services import profile as profile_service")
    fixture = fixture.replace("profile_routes", "profile_service")
    assert current("tests/conftest.py") == fixture
    path = "tests/test_profile_service_contract.py"
    expected_test = original(path, TEST_BASELINE).replace("from blueprints import profile as query_module", "from services import profile as query_module")
    assert current(path) == expected_test
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in paths:
        if path.endswith(".py") and path not in {"blueprints/profile.py", "tests/conftest.py"}:
            assert current(path) == original(path), path
    print("Only datetime fake/import connections change; expectations and all other existing Python files match")


if __name__ == "__main__":
    verify_services()
    verify_routes()
    verify_scope()
