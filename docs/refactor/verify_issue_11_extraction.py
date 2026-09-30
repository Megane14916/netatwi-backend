"""Verify the issue #11 extraction against pre-extraction master (stdlib only)."""

import ast
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "6f52a0d"
TARGETS = {
    "blueprints/tasks.py": ("handle_contest_task", "bp"),
    "cli/process_contests.py": ("process_contests_command", "cli"),
    "cli/user_stats.py": ("update_user_stats", "cli"),
}


def dump(node):
    return ast.dump(node, include_attributes=False)


def read_functions(tree):
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def remove_statement(body, source):
    expected = dump(ast.parse(source).body[0])
    matching = [i for i, node in enumerate(body) if dump(node) == expected]
    assert len(matching) == 1, source
    del body[matching[0]]


def verify():
    original = subprocess.check_output(
        ["git", "show", f"{BASELINE}:app.py"], cwd=ROOT
    ).decode("utf-8")
    original_lines = original.splitlines(keepends=True)
    before_tree = ast.parse(original)
    before = read_functions(before_tree)
    moved_names = set()
    for filename, (name, registration_object) in TARGETS.items():
        source = (ROOT / filename).read_text(encoding="utf-8")
        source_lines = source.splitlines(keepends=True)
        moved = read_functions(ast.parse(source))
        assert set(moved) == {name}, filename
        old, new = before[name], moved[name]
        assert (
            "".join(original_lines[old.lineno - 1:old.end_lineno])
            == "".join(source_lines[new.lineno - 1:new.end_lineno])
        ), f"Function source changed: {name}"
        assert len(old.decorator_list) == len(new.decorator_list) == 1, name
        old_route, new_route = old.decorator_list[0], new.decorator_list[0]
        assert isinstance(old_route, ast.Call) and isinstance(old_route.func, ast.Attribute)
        expected_method = "route" if registration_object == "bp" else "command"
        assert old_route.func.attr == expected_method
        old_route.func.value = ast.Name(id=registration_object, ctx=ast.Load())
        assert dump(old_route) == dump(new_route), f"Registration arguments changed: {name}"
        old.decorator_list = []
        new.decorator_list = []
        assert dump(old) == dump(new), f"Function AST changed: {name}"
        moved_names.add(name)
        print(f"{filename}: function text, AST and registration arguments match")

    after_tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    retained = read_functions(after_tree)
    assert set(retained) == set(before) - moved_names
    # Normalize only the explicitly permitted registration wiring.
    register = retained["_register_extracted_routes"]
    registries = [
        node for node in ast.walk(register) if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == "generate_contest_results"
                for key in node.keys)
    ]
    assert len(registries) == 1
    registry = registries[0]
    index = next(i for i, key in enumerate(registry.keys)
                 if isinstance(key, ast.Constant) and key.value == "generate_contest_results")
    expected_helper = ast.parse("lambda *args: generate_contest_results(*args)", mode="eval").body
    assert dump(registry.values[index]) == dump(expected_helper)
    del registry.keys[index]
    del registry.values[index]
    remove_statement(retained["create_app"].body, "register_cli(application)")
    for name, node in retained.items():
        assert dump(node) == dump(before[name]), f"Retained function changed: {name}"

    remove_statement(after_tree.body, "from blueprints.tasks import handle_contest_task")
    remove_statement(after_tree.body, "from cli import process_contests_command, register_cli, update_user_stats")
    remove_statement(after_tree.body, "register_cli(app)")
    before_tree.body = [
        node for node in before_tree.body
        if not (isinstance(node, ast.FunctionDef) and node.name in moved_names)
    ]
    assert dump(before_tree) == dump(after_tree), "Unexpected app.py changes"
    print(f"Verified {len(moved_names)} moved and {len(retained)} retained functions")
    print("All other app.py statements match after normalizing registration wiring")


if __name__ == "__main__":
    verify()
