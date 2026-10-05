"""Independently verify #52 bodies, imports, aliases and unmodified scope."""

import ast
import hashlib
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "0c71ecf9780dc75e5fa60e4b5f255a6bb77b0b59"
TEST_BASELINE = "a9619f00cc1852398c742c14ad775cc5ec963318"
MODULES = {"app_config": "app.config", "app_extensions": "app.extensions", "app_factory": "app.factory", "app_hooks": "app.hooks", "runtime_dependencies": "app.runtime_dependencies", "models": "app.models", "blueprints": "app.routes", "services": "app.services", "integrations": "app.integrations", "cli": "app.cli"}
ENTRY_ADAPTER_SHA256 = "77f3642f90ae0b60485be7fd4a98fdfad40f9df6474b1aa0816f0d1a8517c58d"
FLASK_ADAPTER = '''    app = Flask(
        "app",
        root_path=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        instance_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance"),
    )'''


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def current(path):
    return (ROOT / path).read_text(encoding="utf-8")


def paths():
    return subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()


def dump(node):
    return ast.dump(node, include_attributes=False)


def module_path(name):
    root, separator, tail = name.partition(".")
    return MODULES.get(root, root) + separator + tail


class AllowedImports(ast.NodeTransformer):
    def __init__(self, labels=False):
        self.labels = labels

    def visit_ImportFrom(self, node):
        if node.level == 0 and node.module:
            node.module = module_path(node.module)
        return node

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name in MODULES:
                old = alias.name
                alias.name = MODULES[old]
                alias.asname = alias.asname or old
        return node

    def visit_Constant(self, node):
        if self.labels and isinstance(node.value, str):
            node.value = module_path(node.value)
        return node


def restore_import_source(source):
    """Reverse only actual import tokens, independently of the generator."""
    data = source.encode("utf-8")
    lines = data.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    reverse = {value: key for key, value in MODULES.items()}

    def old_name(name):
        for canonical, old in reverse.items():
            if name == canonical or name.startswith(canonical + "."):
                return old + name[len(canonical):]
        return name

    edits = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            previous = old_name(n.module)
            if previous == n.module:
                continue
            before, after = "from " + n.module, "from " + previous
        elif isinstance(n, ast.Import) and len(n.names) == 1:
            alias = n.names[0]
            previous = old_name(alias.name)
            if previous == alias.name:
                continue
            before = "import " + alias.name + (" as " + alias.asname if alias.asname else "")
            after = "import " + previous + (" as " + alias.asname if alias.asname and alias.asname != previous else "")
        else:
            continue
        start = offsets[n.lineno - 1] + n.col_offset
        assert data[start:start + len(before)] == before.encode("utf-8")
        edits.append((start, start + len(before), after.encode("utf-8")))
    for start, end, replacement in sorted(edits, reverse=True):
        data = data[:start] + replacement + data[end:]
    return data.decode("utf-8")


def mapping():
    result = {}
    for path in paths():
        if not path.endswith(".py"):
            continue
        root = path.split("/", 1)[0]
        if root in {"models", "blueprints", "services", "integrations", "cli"}:
            result[path] = MODULES[root].replace(".", "/") + path[len(root):]
        elif path[:-3] in MODULES:
            result[path] = MODULES[path[:-3]].replace(".", "/") + ".py"
    return result


def verify_bodies(moved):
    for old, new in moved.items():
        original_source = original(old)
        expected = AllowedImports().visit(ast.parse(original_source))
        restored = restore_import_source(current(new))
        if old == "models/base.py":
            expected = ast.parse("from app.extensions import SQLAlchemy, db")
            assert current(new) == "from app.extensions import SQLAlchemy, db\n"
        elif old == "app_extensions.py":
            index = next(i for i, n in enumerate(expected.body) if isinstance(n, ast.ImportFrom) and n.module == "app.models")
            expected.body[index:index + 1] = ast.parse(original("models/base.py")).body
            restored = restored.replace(original("models/base.py").rstrip(), "from models import db", 1)
            assert restored == original_source, old
        elif old == "app_factory.py":
            base = next(n for n in expected.body if isinstance(n, ast.FunctionDef) and n.name == "create_base_app")
            assert base.body[1].value.func.id == "Flask"
            base.body[1] = ast.parse(FLASK_ADAPTER.strip()).body[0]
            restored = restored.replace(FLASK_ADAPTER, '    app = Flask("app")', 1)
            assert restored == original_source, old
        else:
            assert restored == original_source, old
        assert dump(ast.parse(current(new))) == dump(expected), new
    print(f"{len(moved)} implementations: whole source and AST match import/db/resource adapters; strings/comments/bodies retained")


def alias_source(target):
    return f'''"""Compatibility alias; implementation lives in {target}."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("{target}")
'''


def verify_compatibility(moved):
    for old, new in moved.items():
        root = old.split("/", 1)[0]
        target = new[:-3].replace("/", ".")
        if "/" not in old:
            assert current(old) == alias_source(target)
        elif root in {"models", "blueprints", "cli"} and not old.endswith("/__init__.py"):
            assert not (ROOT / old).exists(), old
        elif root in {"services", "integrations"}:
            if old.endswith("/__init__.py"):
                expected = f'"""Compatibility namespace for {MODULES[root]}; children are lazy aliases."""\n'
            else:
                expected = alias_source(target)
            assert current(old) == expected, old
    for root in ("models", "blueprints", "cli"):
        target = MODULES[root]
        expected = f'''"""Compatibility alias for {target}; no processing bodies live here."""

from importlib import import_module
import sys

_target = import_module("{target}")
'''
        for child in sorted(Path(p).stem for p in moved if p.startswith(root + "/") and not p.endswith("/__init__.py")):
            expected += f'sys.modules[__name__ + ".{child}"] = import_module("{target}.{child}")\n'
        expected += "sys.modules[__name__] = _target\n"
        assert current(root + "/__init__.py") == expected
    restored = restore_import_source(current("app.py"))
    restored = restored.replace("from app import _publish_entry\n", "", 1).replace("_publish_entry(globals())\n", "", 1)
    assert restored == original("app.py")
    # Newly written package export adapter has no baseline body. Pin its reviewed
    # source independently and verify that its export list covers the old entry.
    assert hashlib.sha256(current("app/__init__.py").encode("utf-8")).hexdigest() == ENTRY_ADAPTER_SHA256
    tree = ast.parse(original("app_factory.py"))
    initializer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "initialize_application")
    names = {"initialize_application"}
    for n in ast.walk(initializer):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "update":
            names.update(k.value for k in n.args[0].keys)
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "namespace" and isinstance(n.ctx, ast.Store):
            names.add(n.slice.value)
    exports = next(n for n in ast.parse(current("app/__init__.py")).body if isinstance(n, ast.Assign) and n.targets[0].id == "_RUNTIME_EXPORTS")
    assert ast.literal_eval(exports.value) == tuple(sorted(names))
    print("All legacy files are exact thin aliases or removed; direct startup source preserved; reviewed package adapter/export names match")


def verify_tests_and_scope(moved):
    changed = set(moved) | {"app.py", "sync_comment_counts.py"}
    for path in paths():
        if path.startswith("tests/") and path.endswith(".py") or path == "sync_comment_counts.py":
            labels = path.startswith("tests/")
            expected = AllowedImports(labels).visit(ast.parse(original(path)))
            if path == "tests/conftest.py":
                index = next(i for i, n in enumerate(expected.body) if isinstance(n, ast.Import) and n.names[0].name == "app")
                expected.body[index + 1:index + 1] = ast.parse("app_module.app").body
            assert dump(ast.parse(current(path))) == dump(expected), path
            if labels:
                # Source restoration below permits only literal module labels;
                # AST comparison above also checks f-string module prefixes.
                restored = restore_import_source(current(path))
                restored = restored.replace("app_module.app  # Resolve the public entry before loading fakes and components.\n", "", 1)
                for old, new in sorted(MODULES.items(), key=lambda pair: len(pair[1]), reverse=True):
                    # Limit replacements to module-qualified literal labels.
                    restored = restored.replace('"' + new + '"', '"' + old + '"')
                    restored = restored.replace('"' + new + '.', '"' + old + '.')
                assert restored == original(path), path
            else:
                assert restore_import_source(current(path)) == original(path)
            changed.add(path)
        elif path not in changed:
            # Compare Git-filtered blobs so Windows CRLF and binary files both
            # retain the original content under the repository's attributes.
            actual = subprocess.check_output(["git", "hash-object", "--path", path, path], cwd=ROOT).strip()
            expected_blob = subprocess.check_output(["git", "rev-parse", f"{BASELINE}:{path}"], cwd=ROOT).strip()
            assert actual == expected_blob, path
    path = "tests/test_package_entry_contract.py"
    assert current(path) == original(path, TEST_BASELINE)
    print("Tests only change imports/module labels/fake connections and fixture activation; all other baseline files and pre-move tests preserved")


if __name__ == "__main__":
    moved = mapping()
    verify_bodies(moved)
    verify_compatibility(moved)
    verify_tests_and_scope(moved)
