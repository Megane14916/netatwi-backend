"""Compare issue #44's source, AST, HTTP adapters and unchanged file scope."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "b471c187e74b0ae3bd6ee41ab9eb3179db02fbe9"
TEST_BASELINE = "cdc83690a69246af48dd4b619138f554c7f465ff"


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


class HttpReturnAdapter(ast.NodeTransformer):
    def __init__(self, preparation=False):
        self.preparation = preparation

    def visit_Return(self, node):
        assert isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2
        payload, status = node.value.elts
        assert isinstance(payload, ast.Call) and isinstance(payload.func, ast.Name) and payload.func.id == "jsonify"
        assert len(payload.args) == 1 and not payload.keywords
        node.value.elts[0] = payload.args[0]
        if self.preparation:
            assert isinstance(status, ast.Constant) and status.value == 403
            node.value.elts.insert(1, ast.Constant(value=None))
        return node


def verify_services():
    before_source = original("blueprints/interactions.py")
    before = functions(ast.parse(before_source))
    bookmark = before["set_bookmark"].body[-1]
    like = before["set_like"].body[-1]
    after_source = current("services/interactions.py")
    after_tree = ast.parse(after_source)
    after = functions(after_tree)
    specs = [
        ("get_bookmark_post", "post_id", bookmark.body[:2], "post"),
        ("set_bookmark", "post_id, user_id, post, is_bookmarked", bookmark.body[3:], "http"),
        ("recover_bookmark", "post_id", bookmark.handlers[0].body[1].body, "http"),
        ("prepare_like", "post_id, user_id", like.body[:6], "prepare"),
        ("set_like", "post_id, user_id, post, c, is_liked", like.body[7:], "http"),
        ("recover_like", "post_id, user_id", like.handlers[0].body[1:], "http"),
    ]
    expected_functions = []
    for name, args, nodes, adapter in specs:
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = deepcopy(nodes)
        assert not any(isinstance(n, ast.FunctionDef) for statement in nodes for n in ast.walk(statement))
        expected = HttpReturnAdapter(adapter == "prepare").visit(expected)
        expected_source = body_source(before_source, nodes).replace("jsonify(", "(")
        if adapter == "post":
            expected.body += statements("return post, 200")
            expected_source += "\nreturn post, 200"
        elif adapter == "prepare":
            expected.body += statements("return post, c, 200")
            expected_source = expected_source.replace("), 403", "), None, 403") + "\nreturn post, c, 200"
        assert dump(after[name]) == dump(expected), f"{name}: AST differs"
        assert body_source(after_source, after[name].body) == expected_source, f"{name}: source differs"
        expected_functions.append(expected)
        print(f"{name}: source and AST match with declared HTTP boundary adapters")
    expected_tree = ast.Module(body=statements('''
"""Bookmark and like queries, validation, mutations and conflict recovery."""
from datetime import datetime, timezone
from models import Bookmark, Post, Vote, db
from services import notifications as notifications_service
''') + expected_functions, type_ignores=[])
    assert dump(after_tree) == dump(expected_tree)
    print("Entire service module matches, including imports and signatures")


def verify_routes():
    expected = ast.parse(original("blueprints/interactions.py"))
    before = functions(expected)
    bookmark = before["set_bookmark"].body[-1]
    like = before["set_like"].body[-1]
    # Keep the baseline method-read nodes between preparation and mutation.
    bookmark.body = statements('''
post, status = interaction_service.get_bookmark_post(post_id)
if status != 200:
    return jsonify(post), status
''') + bookmark.body[2:3] + statements('''
result, status = interaction_service.set_bookmark(post_id, user_id, post, is_bookmarked)
return jsonify(result), status
''')
    bookmark.handlers[0].body[1].body = statements('''
recovered = interaction_service.recover_bookmark(post_id)
if recovered is not None:
    return jsonify(recovered[0]), recovered[1]
''')
    like.body = statements('''
post, c, status = interaction_service.prepare_like(post_id, user_id)
if status != 200:
    return jsonify(post), status
''') + like.body[6:7] + statements('''
result, status = interaction_service.set_like(post_id, user_id, post, c, is_liked)
return jsonify(result), status
''')
    like.handlers[0].body[1:] = statements('''
result, status = interaction_service.recover_like(post_id, user_id)
return jsonify(result), status
''')
    for node in expected.body:
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            node.names = [n for n in node.names if n.name == "db"]
        elif isinstance(node, ast.ImportFrom) and node.module == "services":
            node.names = [ast.alias(name="interactions", asname="interaction_service")]
    expected.body = [n for n in expected.body if not (isinstance(n, ast.ImportFrom) and n.module == "datetime")]
    assert dump(ast.parse(current("blueprints/interactions.py"))) == dump(expected)
    print("Entire route module matches: auth, method reads, decorators, rollback, logs and exception/JSON boundaries")


def verify_scope():
    path = "tests/conftest.py"
    expected = original(path).replace(
        "from blueprints import interactions as interaction_routes",
        "from services import interactions as interaction_service"
    ).replace('monkeypatch.setattr(interaction_routes, "datetime", FixedDateTime)',
              'monkeypatch.setattr(interaction_service, "datetime", FixedDateTime)')
    assert current(path) == expected
    path = "tests/test_interaction_service_contract.py"
    assert current(path) == original(path, TEST_BASELINE)
    tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in tracked:
        if path.endswith(".py") and path not in {"blueprints/interactions.py", "tests/conftest.py"}:
            assert current(path) == original(path), path
    print("Only interaction clock fake target changes; pre-move tests and every other existing Python file match")


if __name__ == "__main__":
    verify_services()
    verify_routes()
    verify_scope()
