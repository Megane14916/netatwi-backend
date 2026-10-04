"""Check issue #43's copied source, AST, adapters and unchanged file scope."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "5b93a8680467b375d26f209fd85d65f71bcb3282"
TEST_BASELINE = "980f00257c5299ee47b5ca6ece8bc9f20b2ac4ba"


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def current(path):
    return (ROOT / path).read_text(encoding="utf-8")


def dump(node):
    return ast.dump(node, include_attributes=False)


def statements(source):
    return ast.parse(source).body


def functions(tree):
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def body_source(source, nodes):
    return textwrap.dedent("\n".join(source.splitlines()[nodes[0].lineno - 1:nodes[-1].end_lineno]))


class UnwrapHttpReturns(ast.NodeTransformer):
    def visit_Return(self, node):
        # Do not rewrite any other call, expression or nested helper.
        value = node.value
        if isinstance(value, ast.Tuple):
            value = value.elts[0]
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "jsonify":
            assert len(value.args) == 1 and not value.keywords
            if isinstance(node.value, ast.Tuple):
                node.value.elts[0] = value.args[0]
            else:
                node.value = value.args[0]
        return node


def verify_services():
    before_source = original("blueprints/comments.py")
    before_tree = ast.parse(before_source)
    before = functions(before_tree)
    after_source = current("services/comments.py")
    after_tree = ast.parse(after_source)
    after = functions(after_tree)
    add = before["add_comment"].body
    modify = before["modify_comment"].body
    specs = [
        ("get_comments", "post_id", before["get_comments"].body, "http"),
        ("get_multiple_comments", "post_ids", before["get_multiple_comments"].body[3:], "http"),
        ("get_post", "post_id", add[2:3], "lookup"),
        ("add_comment", "post_id, user_id, post, raw_content, judge_contests", add[6:], "http"),
        ("get_comment_for_modification", "comment_id, user_id", modify[2:4], "owner"),
        ("delete_comment", "comment", modify[4].body, "status"),
        ("update_comment", "comment, raw_content", modify[7:], "status"),
    ]
    expected_functions = []
    for name, args, nodes, adapter in specs:
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = deepcopy(nodes)
        assert not any(isinstance(node, ast.FunctionDef) for statement in nodes for node in ast.walk(statement))
        expected = UnwrapHttpReturns().visit(expected)
        expected_source = body_source(before_source, nodes).replace("jsonify(", "(")
        if adapter == "lookup":
            assert isinstance(expected.body[0], ast.Assign)
            expected.body[0] = ast.Return(value=expected.body[0].value)
            expected_source = expected_source.replace("post = ", "return ", 1)
        elif adapter == "owner":
            expected.body += statements("return comment, 200")
            expected_source += "\nreturn comment, 200"
        elif adapter == "status":
            assert isinstance(expected.body[-1], ast.Return)
            expected.body[-1].value = ast.Tuple(
                elts=[expected.body[-1].value, ast.Constant(value=200)], ctx=ast.Load()
            )
            expected_source += ", 200"
        assert dump(after[name]) == dump(expected), f"{name}: AST differs"
        assert body_source(after_source, after[name].body) == expected_source, f"{name}: source differs"
        expected_functions.append(expected)
        print(f"{name}: original source and AST match with declared boundary adapters")
    expected_tree = ast.Module(body=statements('''
"""Comment queries, validation and mutations with the original write order."""
from datetime import timedelta, timezone
from models import Comment, Post, db
from services import notifications as notifications_service
JST = timezone(timedelta(hours=9), "JST")
''') + expected_functions, type_ignores=[])
    assert dump(after_tree) == dump(expected_tree), "service module differs"
    print("Service imports, JST constant, signatures and all statements match")


def verify_routes():
    expected = ast.parse(original("blueprints/comments.py"))
    routes = functions(expected)
    # Auth/session and request input statements come directly from the baseline.
    routes["get_comments"].body = statements("return jsonify(comments_service.get_comments(post_id))")
    routes["get_multiple_comments"].body = routes["get_multiple_comments"].body[:3] + statements(
        "return jsonify(comments_service.get_multiple_comments(post_ids))"
    )
    add = routes["add_comment"].body
    routes["add_comment"].body = add[:2] + statements("post = comments_service.get_post(post_id)") + add[3:6] + statements('''
result, status = comments_service.add_comment(post_id, user_id, post, raw_content, judge_contests)
return jsonify(result), status
''')
    modify = routes["modify_comment"].body
    routes["modify_comment"].body = modify[:2] + statements('''
comment, status = comments_service.get_comment_for_modification(comment_id, user_id)
if status != 200:
    return jsonify(comment), status
if request.method == "DELETE":
    result, status = comments_service.delete_comment(comment)
    return jsonify(result), status
''') + modify[5:7] + statements('''
result, status = comments_service.update_comment(comment, raw_content)
return jsonify(result), status
''')
    expected.body = [node for node in expected.body if not (
        isinstance(node, ast.ImportFrom) and node.module == "datetime"
        or isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "JST"
    )]
    imports = [i for i, node in enumerate(expected.body)
               if isinstance(node, ast.ImportFrom) and node.module in ("models", "services")]
    assert len(imports) == 2 and imports[1] == imports[0] + 1
    expected.body[imports[0]:imports[1] + 1] = statements("from services import comments as comments_service")
    assert dump(ast.parse(current("blueprints/comments.py"))) == dump(expected)
    print("Entire route module matches: HTTP inputs, auth, lookup/input order, decorators and adapters")


def verify_scope():
    path = "tests/test_comment_service_contract.py"
    assert current(path) == original(path, TEST_BASELINE), "pre-extraction characterization tests changed"
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in paths:
        if path.endswith(".py") and path != "blueprints/comments.py":
            assert current(path) == original(path), path
    print("Pre-extraction tests and every other existing Python file are unchanged")


if __name__ == "__main__":
    verify_services()
    verify_routes()
    verify_scope()
