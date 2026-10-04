"""Compare notification/statistics services and adapters with issue #17 baseline."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "d3326b7"
TEST_BASELINE = "d5670e2"


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def current(path):
    return (ROOT / path).read_text(encoding="utf-8")


def dump(node):
    return ast.dump(node, include_attributes=False)


def module(nodes):
    return ast.Module(body=nodes, type_ignores=[])


def statements(source):
    return ast.parse(source).body


def functions(tree):
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def target(node, name):
    return isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name


def copied_body(source, nodes):
    return textwrap.dedent("\n".join(source.splitlines()[nodes[0].lineno - 1:nodes[-1].end_lineno]))


def like_creation(function):
    return next(n for n in ast.walk(function) if isinstance(n, ast.If)
                and isinstance(n.test, ast.Name) and n.test.id == "is_liked")


def verify_notifications():
    paths = ("blueprints/comments.py", "blueprints/interactions.py", "blueprints/notifications.py")
    sources = {path: original(path) for path in paths}
    trees = {path: ast.parse(source) for path, source in sources.items()}
    comment = functions(trees[paths[0]])["add_comment"]
    comment_index = next(i for i, n in enumerate(comment.body) if target(n, "contest"))
    comment_nodes = comment.body[comment_index:comment_index + 3]
    assert isinstance(comment_nodes[-1], ast.If)
    assert dump(comment.body[comment_index + 3]) == dump(statements("db.session.commit()")[0])
    like = like_creation(functions(trees[paths[1]])["set_like"])
    assert len(like.body) == 3 and isinstance(like.body[-1], ast.If)
    notification_functions = functions(trees[paths[2]])
    service_source = current("services/notifications.py")
    service_tree = ast.parse(service_source)
    services = functions(service_tree)
    expected_functions = []
    for name, args, nodes, path, http in (
        ("create_comment_notification", "post, post_id, user_id", comment_nodes, paths[0], False),
        ("create_like_notification", "post, post_id, user_id, c", like.body[2:], paths[1], False),
        *[(name, "user_id", function.body[2:], paths[2], True)
          for name, function in notification_functions.items()],
    ):
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = deepcopy(nodes)
        if http:
            # Only the outer HTTP return is adapted; nested preview-helper returns stay intact.
            outer_return = expected.body[-1]
            assert isinstance(outer_return, ast.Return)
            call = outer_return.value
            assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "jsonify"
            assert len(call.args) == 1 and not call.keywords
            outer_return.value = call.args[0]
        assert dump(services[name]) == dump(expected), name
        before_body = copied_body(sources[path], nodes)
        if http:
            before_body = before_body.replace("jsonify(", "(")
        assert copied_body(service_source, services[name].body) == before_body, name
        expected_functions.append(expected)
        print(f"{name}: source and AST match with explicit HTTP return adapters only")
    assert set(services) == {f.name for f in expected_functions}
    jst = next(n for n in trees[paths[2]].body if target(n, "JST"))
    expected_service = module([service_tree.body[0]] + statements('''
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import joinedload
from models import Comment, Notification, db
''') + [deepcopy(jst)] + expected_functions)
    assert ast.get_docstring(service_tree) is not None
    assert dump(service_tree) == dump(expected_service)

    expected_comments = deepcopy(trees[paths[0]])
    expected_comment = functions(expected_comments)["add_comment"]
    expected_comment.body[comment_index:comment_index + 3] = statements(
        "notifications_service.create_comment_notification(post, post_id, user_id)")
    for node in expected_comments.body:
        if isinstance(node, ast.ImportFrom) and node.module in {"datetime", "models"}:
            node.names = [n for n in node.names if n.name not in {"datetime", "Notification"}]
    import_index = next(i for i, n in enumerate(expected_comments.body)
                        if isinstance(n, ast.ImportFrom) and n.module == "models")
    expected_comments.body[import_index + 1:import_index + 1] = statements(
        "from services import notifications as notifications_service")
    assert dump(ast.parse(current(paths[0]))) == dump(expected_comments)

    expected_likes = deepcopy(trees[paths[1]])
    like_creation(functions(expected_likes)["set_like"]).body[2:] = statements(
        "notifications_service.create_like_notification(post, post_id, user_id, c)")
    for node in expected_likes.body:
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            node.names = [n for n in node.names if n.name != "Notification"]
    import_index = next(i for i, n in enumerate(expected_likes.body)
                        if isinstance(n, ast.ImportFrom) and n.module == "models")
    expected_likes.body[import_index + 1:import_index + 1] = statements(
        "from services import notifications as notifications_service")
    assert dump(ast.parse(current(paths[1]))) == dump(expected_likes)
    print("Comment/like auth, validation, mutation, time reads, commits and exception boundaries match")

    expected_routes = deepcopy(trees[paths[2]])
    expected_routes.body = [n for n in expected_routes.body if not (
        (isinstance(n, ast.ImportFrom) and n.module in {"datetime", "sqlalchemy.orm"}) or target(n, "JST"))]
    import_index = next(i for i, n in enumerate(expected_routes.body)
                        if isinstance(n, ast.ImportFrom) and n.module == "models")
    expected_routes.body[import_index:import_index + 1] = statements(
        "from services import notifications as notifications_service")
    for name, function in functions(expected_routes).items():
        assert target(function.body[1], "user_id")
        function.body[2:] = statements(f"return jsonify(notifications_service.{name}(user_id))")
    assert dump(ast.parse(current(paths[2]))) == dump(expected_routes)
    print("Notification routes retain auth, session inputs, JSON conversion, URLs and decorators")


def verify_statistics():
    before_source = original("cli/user_stats.py")
    before_tree = ast.parse(before_source)
    before = functions(before_tree)["update_user_stats"]
    expected = deepcopy(before)
    expected.decorator_list = []
    service_source = current("services/user_stats.py")
    service_tree = ast.parse(service_source)
    service = functions(service_tree)["update_user_stats"]
    assert dump(service) == dump(expected)
    assert ast.get_source_segment(service_source, service) == ast.get_source_segment(before_source, before)
    assert ast.get_docstring(service_tree) is not None
    assert dump(service_tree) == dump(module([service_tree.body[0], expected]))
    expected_cli = deepcopy(before_tree)
    index = next(i for i, n in enumerate(expected_cli.body)
                 if isinstance(n, ast.ImportFrom) and n.module == "flask.cli")
    expected_cli.body[index + 1:index + 1] = statements("from services import user_stats as user_stats_service")
    callback = functions(expected_cli)["update_user_stats"]
    callback.body = callback.body[:1] + statements("return user_stats_service.update_user_stats()")
    assert dump(ast.parse(current("cli/user_stats.py"))) == dump(expected_cli)
    print("Statistics function source/AST match in full; CLI name, callback and docstring match")


def verify_tests_and_scope():
    expected = original("tests/conftest.py").replace(
        "from blueprints import comments as comment_routes", "from services import notifications as notifications_service"
    ).replace('monkeypatch.setattr(comment_routes, "datetime", FixedDateTime)',
              'monkeypatch.setattr(notifications_service, "datetime", FixedDateTime)')
    assert current("tests/conftest.py") == expected
    assert dump(ast.parse(current("tests/conftest.py"))) == dump(ast.parse(expected))
    path = "tests/test_notification_stats_contract.py"
    assert current(path) == original(path, TEST_BASELINE)
    changed = {"blueprints/comments.py", "blueprints/interactions.py", "blueprints/notifications.py",
               "cli/user_stats.py", "tests/conftest.py"}
    tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in tracked:
        if path.endswith(".py") and path not in changed:
            assert current(path) == original(path), path
    print("Only the comment-notification clock fake target changes; pre-move tests and other Python files match")


if __name__ == "__main__":
    verify_notifications()
    verify_statistics()
    verify_tests_and_scope()
