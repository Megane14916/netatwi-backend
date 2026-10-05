"""Independently check #53 source/AST, snapshot content and unchanged application.

Compare against the merged #52 baseline. This is the current relocation gate;
the earlier extraction scripts remain checks for their historical commits.
"""

import ast
from pathlib import Path
import subprocess

from issue_53_layout import BASELINE, MAPPING, SNAPSHOTS, UNIT_FUNCTIONS, UNIT_SOURCE, UNIT_TARGET


ROOT = Path(__file__).resolve().parents[2]


def original(path):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT).decode("utf-8")


def current(path):
    return (ROOT / path).read_text(encoding="utf-8")


def dump(node):
    return ast.dump(node, include_attributes=False)


def restore_location_connections(path, source):
    if path in {"tests/test_bootstrap_contract.py", "tests/test_model_contract.py"}:
        before = 'Path(__file__).parents[1] / "snapshots"'
        assert source.count(before) == 1
        source = source.replace(before, 'Path(__file__).parent / "fixtures"', 1)
    if path in {"tests/test_package_entry_contract.py", "tests/test_package_alias_contract.py"}:
        before = 'Path(__file__).resolve().parents[2]'
        assert source.count(before) == 1
        source = source.replace(before, 'Path(__file__).resolve().parents[1]', 1)
    if path == "tests/test_package_alias_contract.py":
        before = 'from tests.integration.test_package_entry_contract import run_isolated'
        assert source.count(before) == 1
        source = source.replace(before, 'from tests.test_package_entry_contract import run_isolated', 1)
    return source


def verify_tests():
    for old, new in MAPPING.items():
        source = original(old)
        expected = ast.parse(source)
        restored = restore_location_connections(old, current(new))
        if old == UNIT_SOURCE:
            # Select functions independently by name, then verify decorators,
            # body AST and exact original source slices in the new unit module.
            units = ast.parse(current(UNIT_TARGET))
            unit_nodes = [node for node in units.body if isinstance(node, ast.FunctionDef)]
            assert tuple(node.name for node in unit_nodes) == UNIT_FUNCTIONS
            assert units.body[3:] == unit_nodes
            allowed_header = ast.parse('"""Pure text behavior copied from the existing shared-helper contract."""\nimport pytest\nimport app as app_module')
            assert dump(ast.Module(body=units.body[:3], type_ignores=[])) == dump(allowed_header)
            original_lines = source.splitlines(keepends=True)
            unit_lines = current(UNIT_TARGET).splitlines(keepends=True)
            spans = []
            for node in unit_nodes:
                old_node = next(n for n in expected.body if isinstance(n, ast.FunctionDef) and n.name == node.name)
                assert dump(node) == dump(old_node), node.name
                start = min([old_node.lineno, *[d.lineno for d in old_node.decorator_list]]) - 1
                unit_start = min([node.lineno, *[d.lineno for d in node.decorator_list]]) - 1
                assert "".join(original_lines[start:old_node.end_lineno]) == "".join(unit_lines[unit_start:node.end_lineno])
                spans.append((start, old_node.end_lineno))
            for start, end in sorted(spans, reverse=True):
                del original_lines[start:end]
            expected.body = [node for node in expected.body if not (isinstance(node, ast.FunctionDef) and node.name in UNIT_FUNCTIONS)]
            assert restored == "".join(original_lines), old
        else:
            assert restored == source, old
        assert dump(ast.parse(restored)) == dump(expected), old
        assert not (ROOT / old).exists(), old
    assert not list((ROOT / "tests").glob("test_*.py"))
    expected_files = set(MAPPING.values()) | {UNIT_TARGET}
    assert {path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").rglob("test_*.py")} == expected_files
    print("31 original test modules: whole source and AST retained except five location connections; two unit functions copied with unchanged decorators/bodies")


def verify_scope():
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode().splitlines()
    assert {path for path in paths if path.startswith("tests/test_") and path.endswith(".py")} == set(MAPPING)
    for name in SNAPSHOTS:
        assert current(f"tests/snapshots/{name}") == original(f"tests/fixtures/{name}")
        assert not (ROOT / "tests/fixtures" / name).exists()
    allowed = set(MAPPING) | {f"tests/fixtures/{name}" for name in SNAPSHOTS} | {"tests/README.md", "docs/refactor/refactoring-plan.md"}
    for path in paths:
        if path in allowed:
            continue
        # Compare filtered Git blobs to allow platform line endings, not edits.
        actual = subprocess.check_output(["git", "hash-object", "--path", path, path], cwd=ROOT).strip()
        expected = subprocess.check_output(["git", "rev-parse", f"{BASELINE}:{path}"], cwd=ROOT).strip()
        assert actual == expected, path
    for directory in ("tests", "tests/unit", "tests/api", "tests/integration"):
        assert current(directory + "/__init__.py") == '"""Backend test package; shared fixtures remain in tests/conftest.py."""\n'
    print("Three snapshots unchanged; shared conftest/fakes, application, compatibility entries, schema, requirements, CI and historical scripts match baseline")


if __name__ == "__main__":
    verify_tests()
    verify_scope()
