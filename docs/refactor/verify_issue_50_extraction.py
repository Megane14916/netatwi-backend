"""Independently verify #50 source bodies, module ASTs and untouched scope."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "46d312ee22f1990e6ab194c26f8ba941621f18e7"
TEST_BASELINE = "771211d25e37889700d64d703b614b34f9146d9b"
SETTINGS = ("UPLOAD_FOLDER", "ALLOWED_EXTENSIONS", "USE_R2", "R2_BUCKET_NAME", "R2_PUBLIC_URL")
HELPERS = ("allowed_file", "calculate_weighted_length", "save_file", "delete_file", "get_cached_contest_results", "generate_contest_results")
CHANGED = {"app.py", "blueprints/dependencies.py", "blueprints/voting.py", "services/posts.py", "services/voting.py", "services/contest_lifecycle.py", "integrations/images.py"}


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


def setting_nodes(tree):
    start = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == SETTINGS[0])
    end = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == SETTINGS[-1])
    return start, end, tree.body[start:end + 1]


class LiveNamespace(ast.NodeTransformer):
    def visit_Name(self, node):
        if node.id in HELPERS + ("schedule_contest_task", "logger"):
            assert isinstance(node.ctx, ast.Load)
            return ast.Subscript(value=ast.Name(id="namespace", ctx=ast.Load()), slice=ast.Constant(value=node.id), ctx=ast.Load())
        return node


def verify_moved_bodies():
    old_source = original("app.py")
    old = ast.parse(old_source)
    old_functions = functions(old)
    text_source = current("services/text.py")
    text = ast.parse(text_source)
    expected_text = ast.Module(body=statements('"""Weighted text length with the original URL and character rules."""\nimport re') + [old_functions["calculate_weighted_length"]], type_ignores=[])
    assert dump(text) == dump(expected_text)
    assert body_source(text_source, [functions(text)["calculate_weighted_length"]]) == body_source(old_source, [old_functions["calculate_weighted_length"]])
    _, _, settings = setting_nodes(old)
    initializer = statements("def initialize_image_settings(): pass")[0]
    initializer.body = deepcopy(settings) + statements("return " + ", ".join(SETTINGS))
    images = ast.parse(original("integrations/images.py"))
    images.body.append(initializer)
    assert dump(ast.parse(current("integrations/images.py"))) == dump(images)
    image_function = functions(ast.parse(current("integrations/images.py")))["initialize_image_settings"]
    assert body_source(current("integrations/images.py"), image_function.body[:-1]) == body_source(old_source, settings)
    assert current("integrations/images.py").startswith(original("integrations/images.py"))
    print("Text function and image initialization: exact source/AST; existing image operations unchanged")


def verify_dependencies():
    source = original("blueprints/dependencies.py")
    expected = ast.parse(source)
    expected.body[0] = statements('"""Application-scoped helper callbacks shared by services and routes."""')[0]
    lifecycle_source = original("services/contest_lifecycle.py")
    scheduler = functions(ast.parse(lifecycle_source))["schedule_contest_task"]
    expected.body.append(scheduler)
    entry = ast.parse(original("app.py"))
    binder = statements("def register_helper_bindings(application, namespace): pass")[0]
    binder.body = [LiveNamespace().visit(deepcopy(n)) for n in functions(entry)["_register_extracted_routes"].body[:2]]
    expected.body.append(binder)
    actual_source = current("runtime_dependencies.py")
    actual = ast.parse(actual_source)
    assert dump(actual) == dump(expected)
    for name, node in functions(ast.parse(source)).items():
        assert body_source(actual_source, [functions(actual)[name]]) == body_source(source, [node]), name
    assert body_source(actual_source, [functions(actual)["schedule_contest_task"]]) == body_source(lifecycle_source, [scheduler])
    # Separately verify callback source and comments, not just equivalent AST.
    old_bindings = body_source(original("app.py"), functions(entry)["_register_extracted_routes"].body[:2])
    old_bindings = old_bindings.replace("lambda: logger", 'lambda: namespace["logger"]')
    for name in ("schedule_contest_task",) + HELPERS:
        old_bindings = old_bindings.replace(f"lambda *args: {name}(*args)", f'lambda *args: namespace["{name}"](*args)')
    assert body_source(actual_source, functions(actual)["register_helper_bindings"].body) == old_bindings
    alias_names = ("_call", "route_logger") + HELPERS
    compatibility = ast.Module(body=statements('"""Compatibility imports for helpers now owned by runtime_dependencies."""') + [ast.ImportFrom(module="runtime_dependencies", names=[ast.alias(name=n) for n in alias_names], level=0)], type_ignores=[])
    assert dump(ast.parse(current("blueprints/dependencies.py"))) == dump(compatibility)
    print("Common helpers/logger/scheduler and binder: complete AST and copied bodies match; compatibility aliases only")


def verify_entry():
    tree = ast.parse(original("app.py"))
    start, end, _ = setting_nodes(tree)
    tree.body[start:end + 1] = statements("(" + ", ".join(SETTINGS) + ") = image_storage.initialize_image_settings()")
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.FunctionDef) and node.name == "calculate_weighted_length":
            tree.body[i:i + 1] = statements("from services.text import calculate_weighted_length")
    functions(tree)["_register_extracted_routes"].body[:2] = statements("runtime_dependencies.register_helper_bindings(application, globals())")
    index = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.ImportFrom) and n.module == "app_factory")
    tree.body[index + 1:index + 1] = statements("import runtime_dependencies")
    assert dump(ast.parse(current("app.py"))) == dump(tree)
    for name in ("get_r2_client", "allowed_file", "save_file", "delete_file", "generate_contest_results", "get_cached_contest_results", "schedule_contest_task", "create_app"):
        assert body_source(current("app.py"), [functions(ast.parse(current("app.py")))[name]]) == body_source(original("app.py"), [functions(ast.parse(original("app.py")))[name]]), name
    print("Whole entry AST matches: original initialization location, compatibility wrappers, factory, CLI and main retained")


def verify_imports_and_scope():
    for path, old_module in [("services/posts.py", "blueprints.dependencies"), ("services/voting.py", "blueprints.dependencies"), ("blueprints/voting.py", "dependencies"), ("services/contest_lifecycle.py", "flask")]:
        tree = ast.parse(original(path))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == old_module:
                node.module = "runtime_dependencies"
                node.level = 0
                if path == "services/contest_lifecycle.py":
                    node.names = [ast.alias(name="schedule_contest_task")]
        if path == "services/contest_lifecycle.py":
            tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == "schedule_contest_task")]
        assert dump(ast.parse(current(path))) == dump(tree), path
        for name, node in functions(tree).items():
            assert body_source(current(path), [functions(ast.parse(current(path)))[name]]) == body_source(original(path), [node]), (path, name)
    for path in (ROOT / "services").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("blueprints"), path
            elif isinstance(node, ast.Import):
                assert all(not n.name.startswith("blueprints") for n in node.names), path
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in paths:
        if path.endswith(".py") and path not in CHANGED:
            assert current(path) == original(path), path
    test = "tests/test_shared_helper_contract.py"
    assert current(test) == original(test, TEST_BASELINE)
    print("Service/route bodies preserved; no services -> Blueprint imports; all other existing Python and new tests unchanged")


if __name__ == "__main__":
    verify_moved_bodies()
    verify_dependencies()
    verify_entry()
    verify_imports_and_scope()
