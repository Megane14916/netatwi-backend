"""Independently compare issue #48 source, AST, auth/input and transactions."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "52f1ad79ea8d67d717fbdbe6d4f486794d4448da"
TEST_BASELINE = "5304acdd8cc9700e2425ae043b2b7ef21a88f62e"


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
        assert isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2
        call, status = node.value.elts
        assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "jsonify"
        assert len(call.args) == 1 and not call.keywords
        assert isinstance(status, ast.Constant) and status.value in (200, 201, 400, 404)
        node.value.elts[0] = call.args[0]
        return node


def verify_services():
    source = original("blueprints/news.py")
    tree = ast.parse(source)
    routes = functions(tree)
    service_source = current("services/news.py")
    service_tree = ast.parse(service_source)
    services = functions(service_tree)
    expected_functions = []
    specs = [("get_news", "", 0), ("get_admin_news", "", 0),
             ("add_news", "tweet_id", 2), ("delete_news", "id", 0)]
    for name, args, start in specs:
        block = next(n for n in routes[name].body if isinstance(n, ast.Try))
        nodes = block.body[start:]
        assert not any(isinstance(n, ast.FunctionDef) for statement in nodes for n in ast.walk(statement))
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = [UnwrapHttpReturn().visit(deepcopy(n)) for n in nodes]
        assert dump(services[name]) == dump(expected), f"{name}: AST differs"
        expected_source = body_source(source, nodes).replace("jsonify(", "(")
        assert body_source(service_source, services[name].body) == expected_source, f"{name}: source differs"
        expected_functions.append(expected)
        print(f"{name}: original source and AST match with only HTTP return adaptation")
    header = statements('"""News queries, tweet ID parsing and database writes with original boundaries."""')
    imports = [deepcopy(n) for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "models"]
    assert dump(service_tree) == dump(ast.Module(body=header + imports + expected_functions, type_ignores=[]))
    print("Service imports, lazy regex import, limits, ordering, validation, add/delete/commit and statuses match")


def verify_routes():
    tree = ast.parse(original("blueprints/news.py"))
    for name, function in functions(tree).items():
        block = next(n for n in function.body if isinstance(n, ast.Try))
        if name == "add_news":
            prefix, args = block.body[:2], "tweet_id"
        else:
            prefix, args = [], "id" if name == "delete_news" else ""
        block.body = prefix + statements(f"payload, status = news_service.{name}({args})\nreturn jsonify(payload), status")
    index = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.ImportFrom) and n.module == "models")
    tree.body[index:index + 1] = statements("from models import db\nfrom services import news as news_service")
    assert dump(ast.parse(current("blueprints/news.py"))) == dump(tree)
    print("Whole route module matches: auth, request.json/data.get, decorators, JSON, try/except/rollback and print")


def verify_scope():
    path = "tests/test_news_service_contract.py"
    assert current(path) == original(path, TEST_BASELINE)
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in paths:
        if path.endswith(".py") and path != "blueprints/news.py":
            assert current(path) == original(path), path
    print("All test bodies/expectations and every other existing Python file, including fixtures, are unchanged")


if __name__ == "__main__":
    verify_services()
    verify_routes()
    verify_scope()
