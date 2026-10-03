"""Compare post/image extraction with master immediately before issue #13."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "7586a37"
HELPER_SETTINGS = {
    "get_r2_client": [],
    "allowed_file": ["ALLOWED_EXTENSIONS"],
    "save_file": ["UPLOAD_FOLDER", "USE_R2", "R2_BUCKET_NAME", "R2_PUBLIC_URL", "get_r2_client", "logger"],
    "delete_file": ["UPLOAD_FOLDER", "USE_R2", "R2_BUCKET_NAME", "get_r2_client", "logger"],
}


def original(path):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT).decode("utf-8")


def current(path):
    return (ROOT / path).read_text(encoding="utf-8")


def functions(tree):
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def dump(node):
    return ast.dump(node, include_attributes=False)


def module(nodes):
    return ast.Module(body=nodes, type_ignores=[])


def statements(source):
    return ast.parse(source).body


def adapt_returns(nodes, *, success=None, prepare=False):
    """Remove jsonify only; optionally replace the final success with its Post."""
    tree = module(deepcopy(nodes))
    returns = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Return)), key=lambda n: n.lineno)
    for node in returns:
        value = node.value
        assert isinstance(value, ast.Tuple) and len(value.elts) == 2
        call, status = value.elts
        assert isinstance(call, ast.Call) and dump(call.func) == dump(ast.Name(id="jsonify", ctx=ast.Load()))
        assert len(call.args) == 1 and call.keywords == []
        value.elts[0] = call.args[0]
        if prepare:
            node.value = ast.Tuple(elts=[ast.Name(id="new_content", ctx=ast.Load()), value], ctx=ast.Load())
    if success:
        returns[-1].value = ast.parse(success, mode="eval").body
    return tree.body


def verify_posts():
    before_tree = ast.parse(original("blueprints/posts.py"))
    before = functions(before_tree)
    route_tree = ast.parse(current("blueprints/posts.py"))
    routes = functions(route_tree)
    service_tree = ast.parse(current("services/posts.py"))
    services = functions(service_tree)
    submit, update, delete = (before[name] for name in ("submit_post", "update_post", "delete_post"))
    tries = {node.name: next(n for n in node.body if isinstance(n, ast.Try))
             for node in (submit, update, delete)}

    expected_services = {
        "validate_submission": ("content, files", adapt_returns(submit.body[4:6]) + statements("return None")),
        "prepare_update": ("new_content, kept_images, files", adapt_returns(update.body[4:7], prepare=True)
                           + statements("return new_content, None")),
        "submit_post": ("id, user_id, content, files", adapt_returns(tries["submit_post"].body, success="new_post, 201")),
        "update_post": ("contest_id, post_id, user_id, new_content, kept_images, files",
                        adapt_returns(tries["update_post"].body, success="post_to_edit, 200")),
        "delete_post": ("contest_id, post_id, user_id", adapt_returns(tries["delete_post"].body)),
    }
    assert set(services) == set(expected_services)
    for name, (args, body) in expected_services.items():
        expected = ast.parse(f"def {name}({args}): pass").body[0]
        expected.body = body
        assert dump(services[name]) == dump(expected), name
        print(f"{name}: extracted statements match with explicit return adapters only")

    for node, call, success_name, status, prefix, validation in (
        (submit, "post_service.submit_post(id, user_id, content, files)", "new_post", 201, submit.body[:4], '''
error = post_service.validate_submission(content, files)
if error is not None:
    return jsonify(error[0]), error[1]
'''),
        (update, "post_service.update_post(contest_id, post_id, user_id, new_content, kept_images, files)",
         "post_to_edit", 200, update.body[:4], '''
new_content, error = post_service.prepare_update(new_content, kept_images, files)
if error is not None:
    return jsonify(error[0]), error[1]
'''),
        (delete, "post_service.delete_post(contest_id, post_id, user_id)", None, 200, delete.body[:2], ""),
    ):
        expected = deepcopy(node)
        adapted_try = deepcopy(tries[node.name])
        adapted_try.body = statements(f"result, status = {call}")
        if success_name:
            adapted_try.body += statements(f"if status != {status}:\n    return jsonify(result), status\n{success_name} = result")
            adapted_try.body += deepcopy(tries[node.name].body[-1:])
        else:
            adapted_try.body += statements("return jsonify(result), status")
        expected.body = deepcopy(prefix) + statements(validation) + [adapted_try]
        assert dump(routes[node.name]) == dump(expected), node.name
    assert dump(routes["get_posts_for_contest"]) == dump(before["get_posts_for_contest"])
    assert set(routes) == set(before)

    expected_tree = deepcopy(before_tree)
    expected_tree.body = [routes[n.name] if isinstance(n, ast.FunctionDef) else n for n in expected_tree.body]
    expected_tree.body = [n for n in expected_tree.body if not (isinstance(n, ast.ImportFrom) and n.module == "dependencies")]
    for i, node in enumerate(expected_tree.body):
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            node.names = [alias for alias in node.names if alias.name != "datetime"]
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            expected_tree.body[i:i + 1] = statements("from models import Contest, Post, Vote, db\nfrom services import posts as post_service")
            break
    assert dump(route_tree) == dump(expected_tree)
    print("Route inputs, response expressions, decorators, exception handlers, listing and settings match")


def verify_images():
    before_source = original("app.py")
    before_tree = ast.parse(before_source)
    before = functions(before_tree)
    app_tree = ast.parse(current("app.py"))
    app_functions = functions(app_tree)
    image_source = current("integrations/images.py")
    images = functions(ast.parse(image_source))
    assert set(images) == set(HELPER_SETTINGS)

    for name, settings in HELPER_SETTINGS.items():
        node = before[name]
        args = ", ".join(arg.arg for arg in node.args.args)
        signature = args + (", *, " if args else "*, ") + ", ".join(settings) if settings else args
        expected = deepcopy(node)
        expected.args = ast.parse(f"def {name}({signature}): pass").body[0].args
        assert dump(images[name]) == dump(expected), name

        # Source lines, including comments, are copied rather than AST-generated.
        def body_source(source, function):
            return "\n".join(source.splitlines()[function.body[0].lineno - 1:function.end_lineno])
        assert body_source(before_source, node) == body_source(image_source, images[name]), name

        kwargs = ", ".join(f"{key}={key}" for key in settings)
        call_args = args + (", " if args and kwargs else "") + kwargs
        expected = deepcopy(node)
        docstring = node.body[:1] if ast.get_docstring(node) is not None else []
        expected.body = deepcopy(docstring) + statements(f"return image_storage.{name}({call_args})")
        assert dump(app_functions[name]) == dump(expected), name
        print(f"{name}: helper body text/AST match; app compatibility adapter verified")

    expected_app = deepcopy(before_tree)
    expected_app.body = [app_functions[n.name] if isinstance(n, ast.FunctionDef) and n.name in HELPER_SETTINGS
                         else n for n in expected_app.body]
    expected_app.body = [n for n in expected_app.body if not (
        (isinstance(n, ast.Import) and n.names[0].name in {"boto3", "uuid"}) or
        (isinstance(n, ast.ImportFrom) and n.module in {"urllib.parse", "werkzeug.utils"}))]
    index = next(i for i, n in enumerate(expected_app.body) if isinstance(n, ast.ImportFrom) and n.module == "app_factory")
    expected_app.body[index + 1:index + 1] = statements("from integrations import images as image_storage")
    assert dump(app_tree) == dump(expected_app)
    print("All other app.py statements, initialization order and storage settings match")


if __name__ == "__main__":
    verify_posts()
    verify_images()
