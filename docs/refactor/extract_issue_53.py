"""Copy #53 tests verbatim, editing only explicit location connections.

Default compares generated files; --write reproduces the relocation. The two
pure text tests are copied with their decorators using AST source line ranges.
"""

import argparse
import ast
from pathlib import Path
import subprocess

from issue_53_layout import BASELINE, MAPPING, SNAPSHOTS, UNIT_FUNCTIONS, UNIT_SOURCE, UNIT_TARGET


ROOT = Path(__file__).resolve().parents[2]
ADAPTERS = {
    "tests/test_bootstrap_contract.py": (
        ('Path(__file__).parent / "fixtures"', 'Path(__file__).parents[1] / "snapshots"'),
    ),
    "tests/test_model_contract.py": (
        ('Path(__file__).parent / "fixtures"', 'Path(__file__).parents[1] / "snapshots"'),
    ),
    "tests/test_package_entry_contract.py": (
        ('Path(__file__).resolve().parents[1]', 'Path(__file__).resolve().parents[2]'),
    ),
    "tests/test_package_alias_contract.py": (
        ('from tests.test_package_entry_contract import run_isolated', 'from tests.integration.test_package_entry_contract import run_isolated'),
        ('Path(__file__).resolve().parents[1]', 'Path(__file__).resolve().parents[2]'),
    ),
}


def original(path):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT).decode("utf-8")


def generate():
    files = {new: original(old) for old, new in MAPPING.items()}
    for old, changes in ADAPTERS.items():
        source = files[MAPPING[old]]
        for before, after in changes:
            assert source.count(before) == 1, old
            source = source.replace(before, after, 1)
        files[MAPPING[old]] = source

    source = original(UNIT_SOURCE)
    lines = source.splitlines(keepends=True)
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in UNIT_FUNCTIONS]
    assert tuple(node.name for node in nodes) == UNIT_FUNCTIONS
    spans = [(min([node.lineno, *[d.lineno for d in node.decorator_list]]) - 1, node.end_lineno) for node in nodes]
    # Slice original source, including decorators, strings and all function bodies.
    selected = ["".join(lines[start:end]) for start, end in spans]
    files[UNIT_TARGET] = '"""Pure text behavior copied from the existing shared-helper contract."""\n\nimport pytest\n\nimport app as app_module\n\n\n' + "\n\n".join(selected)
    for start, end in reversed(spans):
        del lines[start:end]
    files[MAPPING[UNIT_SOURCE]] = "".join(lines)

    for name in SNAPSHOTS:
        files[f"tests/snapshots/{name}"] = original(f"tests/fixtures/{name}")
    for directory in ("tests", "tests/unit", "tests/api", "tests/integration"):
        files[directory + "/__init__.py"] = '"""Backend test package; shared fixtures remain in tests/conftest.py."""\n'
    return files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    files = generate()
    for path, source in files.items():
        if path.endswith(".py"):
            ast.parse(source)
        target = ROOT / path
        if args.write:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="\n") as output:
                output.write(source)
        else:
            assert target.read_text(encoding="utf-8") == source, path
    removed = set(MAPPING) | {f"tests/fixtures/{name}" for name in SNAPSHOTS}
    for path in removed:
        target = ROOT / path
        if args.write:
            target.unlink(missing_ok=True)
        else:
            assert not target.exists(), path
    print(f"{len(MAPPING)} test modules relocated; two functions split verbatim; {len(SNAPSHOTS)} unchanged snapshots; {len(files)} whole files match")
