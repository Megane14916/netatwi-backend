"""Verify textual/AST equivalence against the pre-issue-10 master (stdlib only)."""

import ast
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "900cbaa"
GROUPS = {
    "voting": ("submit_votes",),
    "results": ("get_contest_results",),
    "interactions": ("set_bookmark", "set_like"),
    "comments": (
        "get_comments", "get_multiple_comments", "add_comment", "modify_comment",
    ),
    "notifications": (
        "get_notifications", "get_unread_notifications_count", "mark_notifications_read",
    ),
    "users": ("get_users_list",),
}


def functions(source):
    return {
        node.name: node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
    }


def dump(node):
    return ast.dump(node, include_attributes=False)


def verify():
    original = subprocess.check_output(
        ["git", "show", f"{BASELINE}:app.py"], cwd=ROOT
    ).decode("utf-8")
    original_lines = original.splitlines(keepends=True)
    before = functions(original)
    moved_names = set()
    for module, names in GROUPS.items():
        source = (ROOT / "blueprints" / f"{module}.py").read_text(encoding="utf-8")
        source_lines = source.splitlines(keepends=True)
        after = functions(source)
        assert set(after) == set(names), module
        for name in names:
            old, new = before[name], after[name]
            assert (
                "".join(original_lines[old.lineno - 1:old.end_lineno])
                == "".join(source_lines[new.lineno - 1:new.end_lineno])
            ), f"Function source changed: {name}"
            assert len(old.decorator_list) == len(new.decorator_list) == 1, name
            expected_route = dump(old.decorator_list[0]).replace(
                "Name(id='app'", "Name(id='bp'", 1
            )
            assert expected_route == dump(new.decorator_list[0]), name
            old.decorator_list = []
            new.decorator_list = []
            assert dump(old) == dump(new), f"Function AST changed: {name}"
            moved_names.add(name)
        print(f"{module}: function text, AST and route arguments match")

    retained = functions((ROOT / "app.py").read_text(encoding="utf-8"))
    assert set(retained) == set(before) - moved_names
    # The sole change inside a retained function is the logger dependency wiring.
    register = retained["_register_extracted_routes"]
    registries = [
        node for node in ast.walk(register)
        if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == "get_route_logger"
                for key in node.keys)
    ]
    assert len(registries) == 1
    registry = registries[0]
    index = next(i for i, key in enumerate(registry.keys)
                 if isinstance(key, ast.Constant) and key.value == "get_route_logger")
    assert dump(registry.values[index]) == dump(ast.parse("lambda: logger", mode="eval").body)
    del registry.keys[index]
    del registry.values[index]
    for name, node in retained.items():
        assert dump(node) == dump(before[name]), f"Retained function changed: {name}"
    print(f"Verified {len(moved_names)} moved and {len(retained)} retained functions")


if __name__ == "__main__":
    verify()
