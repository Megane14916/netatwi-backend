"""Independently check issue #46's source, AST, adapters and unchanged scope."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "be9957eaaf83721ab65db013724949cf4a1937fb"
TEST_BASELINE = "96fc9365070215e20d3cc39aa70dc59a572e81e5"


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


def verify_services():
    source = original("blueprints/posts.py")
    tree = ast.parse(source)
    block = functions(tree)["get_posts_for_contest"].body[-1]
    service_source = current("services/contest_posts.py")
    service_tree = ast.parse(service_source)
    services = functions(service_tree)
    specs = [("get_posts_for_listing", "id, start_time, time", block.body[:6]),
             ("get_posts_for_contest", "id, c, posts, user_id, t2, start_time, time", block.body[7:])]
    expected_functions = []
    for name, args, nodes in specs:
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = deepcopy(nodes)
        expected_source = body_source(source, nodes)
        if name == "get_posts_for_listing":
            expected.body += statements("return c, posts, t2")
            expected_source += "\nreturn c, posts, t2"
        else:
            ret = expected.body[-1]
            assert isinstance(ret, ast.Return)
            assert isinstance(ret.value, ast.Call) and ret.value.func.id == "jsonify"
            assert len(ret.value.args) == 1 and not ret.value.keywords
            ret.value = ret.value.args[0]
            expected_source = expected_source.replace("return jsonify(", "return (", 1)
        assert dump(services[name]) == dump(expected), f"{name}: AST differs"
        assert body_source(service_source, services[name].body) == expected_source, f"{name}: source differs"
        expected_functions.append(expected)
        print(f"{name}: original source and AST match with declared return adapters")
    constants = [deepcopy(n) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id in ("logger", "JST")]
    header = statements('''
"""Contest post queries and viewer display data with original read ordering."""
import logging
from datetime import timedelta, timezone
from models import Contest, Post, Vote
''')
    assert dump(service_tree) == dump(ast.Module(body=header + constants + expected_functions, type_ignores=[]))
    # Keep even the original comment after the final return, which AST omits.
    trailing = "\n".join(source.splitlines()[block.body[-1].end_lineno:block.handlers[0].lineno - 1])
    assert trailing.strip() == "# --- ▲▲▲ ここまで ▲▲▲ ---"
    assert service_source.endswith(textwrap.indent(textwrap.dedent(trailing), "    ") + "\n")
    print("Service imports, lazy Comment import, logger, JST and trailing comment preserved")


def verify_routes():
    tree = ast.parse(original("blueprints/posts.py"))
    block = functions(tree)["get_posts_for_contest"].body[-1]
    block.body = statements("c, posts, t2 = contest_post_service.get_posts_for_listing(id, start_time, time)") + block.body[6:7] + statements(
        "return jsonify(contest_post_service.get_posts_for_contest(id, c, posts, user_id, t2, start_time, time))"
    )
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.Import) and any(a.name == "logging" for a in n.names)
        or isinstance(n, ast.Assign) and n.targets[0].id == "logger"
    )]
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            node.names = [a for a in node.names if a.name == "db"]
    index = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.ImportFrom) and n.module == "services")
    tree.body[index + 1:index + 1] = statements("from services import contest_posts as contest_post_service")
    assert dump(ast.parse(current("blueprints/posts.py"))) == dump(tree)
    print("Whole route module matches: timing origin, session position, JSON, decorators, except and CRUD preserved")


def verify_scope():
    path = "tests/test_contest_post_query_service_contract.py"
    expected_test = original(path, TEST_BASELINE).replace("from blueprints import posts as query_module", "from services import contest_posts as query_module")
    assert current(path) == expected_test
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in paths:
        if path.endswith(".py") and path != "blueprints/posts.py":
            assert current(path) == original(path), path
    print("Test expectations unchanged; every other existing Python file, including CRUD service and fixtures, matches")


if __name__ == "__main__":
    verify_services()
    verify_routes()
    verify_scope()
