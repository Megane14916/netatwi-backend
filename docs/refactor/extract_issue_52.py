"""Reproduce #52 by copying files and editing AST-located import paths.

Default compares generated files; --write reproduces this migration only.
Bodies are not regenerated with ast.unparse and strings/comments remain intact.
"""

import argparse
import ast
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "0c71ecf9780dc75e5fa60e4b5f255a6bb77b0b59"
FLAT = {"app_config": "app.config", "app_extensions": "app.extensions", "app_factory": "app.factory", "app_hooks": "app.hooks", "runtime_dependencies": "app.runtime_dependencies"}
PACKAGES = {"models": "app.models", "blueprints": "app.routes", "services": "app.services", "integrations": "app.integrations", "cli": "app.cli"}
MODULES = {**FLAT, **PACKAGES}


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def tracked():
    return subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()


def imports(source):
    lines = source.encode("utf-8").splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            root, *tail = node.module.split(".")
            if root in MODULES:
                old = "from " + node.module
                new = "from " + ".".join([MODULES[root], *tail])
            else:
                continue
        elif isinstance(node, ast.Import):
            assert len(node.names) == 1 or all(a.name not in MODULES for a in node.names)
            alias = node.names[0]
            if alias.name not in MODULES:
                continue
            old = "import " + alias.name
            if alias.asname:
                old += " as " + alias.asname
            new = "import " + MODULES[alias.name] + " as " + (alias.asname or alias.name)
        else:
            continue
        start = offsets[node.lineno - 1] + node.col_offset
        assert source.encode("utf-8")[start:start + len(old.encode("utf-8"))].decode("utf-8") == old
        edits.append((start, start + len(old.encode("utf-8")), new.encode("utf-8")))
    data = source.encode("utf-8")
    for start, end, replacement in sorted(edits, reverse=True):
        data = data[:start] + replacement + data[end:]
    return data.decode("utf-8")


def moved_files():
    result = {name + ".py": target.replace(".", "/") + ".py" for name, target in FLAT.items()}
    for path in tracked():
        root = path.split("/", 1)[0]
        if root in PACKAGES and path.endswith(".py"):
            result[path] = PACKAGES[root].replace(".", "/") + path[len(root):]
    return result


def test_module_labels(source):
    lines = source.encode("utf-8").splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        root, separator, tail = node.value.partition(".")
        if root not in MODULES:
            continue
        segment = ast.get_source_segment(source, node)
        try:
            if ast.literal_eval(segment) != node.value:
                continue
        except (ValueError, SyntaxError):
            continue  # f-string module prefixes are handled explicitly below.
        replacement = segment.replace(node.value, MODULES[root] + separator + tail, 1)
        edits.append((offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset, replacement.encode("utf-8")))
    data = source.encode("utf-8")
    for start, end, replacement in sorted(edits, reverse=True):
        data = data[:start] + replacement + data[end:]
    return data.decode("utf-8")


def alias(target):
    return f'''"""Compatibility alias; implementation lives in {target}."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("{target}")
'''


def package_alias(target, children):
    source = f'''"""Compatibility alias for {target}; no processing bodies live here."""

from importlib import import_module
import sys

_target = import_module("{target}")
'''
    for child in children:
        source += f'sys.modules[__name__ + ".{child}"] = import_module("{target}.{child}")\n'
    source += "sys.modules[__name__] = _target\n"
    return source


def package_entry(exports):
    return '''"""Public application exports and canonical backend packages.

Component imports stay independent. The first public runtime export resolves
the default application; direct app.py entries can publish their existing app.
"""

from threading import RLock

''' + "_RUNTIME_EXPORTS = (\n" + "".join(f"    {name!r},\n" for name in exports) + ")\n" + '''
_RUNTIME_LOCK = RLock()
_RUNTIME_READY = False


def _publish_entry(namespace):
    global _RUNTIME_READY
    with _RUNTIME_LOCK:
        if not _RUNTIME_READY:
            globals().update({name: namespace[name] for name in _RUNTIME_EXPORTS})
            _RUNTIME_READY = True


def __getattr__(name):
    global _RUNTIME_READY
    if name not in _RUNTIME_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    with _RUNTIME_LOCK:
        if not _RUNTIME_READY:
            before = {key: globals()[key] for key in _RUNTIME_EXPORTS if key in globals()}
            try:
                from .factory import initialize_application

                globals()["initialize_application"] = initialize_application
                initialize_application(globals())
            except BaseException:
                for key in _RUNTIME_EXPORTS:
                    if key in before:
                        globals()[key] = before[key]
                    else:
                        globals().pop(key, None)
                raise
            _RUNTIME_READY = True
    return globals()[name]


def __dir__():
    return sorted(set(globals()) | set(_RUNTIME_EXPORTS))
'''


def generate():
    mapping = moved_files()
    files = {new: imports(original(old)) for old, new in mapping.items()}
    # Move the sole db construction to extensions; models only import that db.
    files["app/extensions.py"] = files["app/extensions.py"].replace("from app.models import db", original("models/base.py").rstrip(), 1)
    files["app/models/base.py"] = "from app.extensions import SQLAlchemy, db\n"
    # Flask('app') now resolves a package; pin its original repository paths.
    files["app/factory.py"] = files["app/factory.py"].replace('    app = Flask("app")', '''    app = Flask(
        "app",
        root_path=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        instance_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance"),
    )''', 1)
    initializer = next(n for n in ast.parse(original("app_factory.py")).body if isinstance(n, ast.FunctionDef) and n.name == "initialize_application")
    exports = {"initialize_application"}
    for n in ast.walk(initializer):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "update" and isinstance(n.func.value, ast.Name) and n.func.value.id == "namespace":
            exports.update(k.value for k in n.args[0].keys)
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "namespace" and isinstance(n.ctx, ast.Store):
            exports.add(n.slice.value)
    files["app/__init__.py"] = package_entry(sorted(exports))
    files["app.py"] = imports(original("app.py"))
    files["app.py"] = files["app.py"].replace("from app.factory import initialize_application", "from app.factory import initialize_application\nfrom app import _publish_entry", 1)
    files["app.py"] = files["app.py"].replace("initialize_application(globals())", "initialize_application(globals())\n_publish_entry(globals())", 1)
    for name, target in FLAT.items():
        files[name + ".py"] = alias(target)
    # Models/routes/CLI already load their children in the original __init__.
    # Preserve root module identity and prevent a second load under old names.
    for name in ("models", "blueprints", "cli"):
        children = sorted(Path(p).stem for p in mapping if p.startswith(name + "/") and not p.endswith("/__init__.py"))
        files[name + "/__init__.py"] = package_alias(PACKAGES[name], children)
    # Services/integrations originally load children lazily; retain that timing.
    for name in ("services", "integrations"):
        files[name + "/__init__.py"] = f'"""Compatibility namespace for {PACKAGES[name]}; children are lazy aliases."""\n'
        for old in mapping:
            if old.startswith(name + "/") and not old.endswith("/__init__.py"):
                files[old] = alias(PACKAGES[name] + "." + Path(old).stem)
    for path in tracked():
        if path.startswith("tests/") and path.endswith(".py") or path == "sync_comment_counts.py":
            source = imports(original(path))
            if path.startswith("tests/"):
                source = test_module_labels(source)
            if path == "tests/conftest.py":
                source = source.replace("import app as app_module  # noqa: E402\n", "import app as app_module  # noqa: E402\napp_module.app  # Resolve the public entry before loading fakes and components.\n", 1)
            source = source.replace('f"models.{module_name}"', 'f"app.models.{module_name}"')
            source = source.replace('f"blueprints.{module}"', 'f"app.routes.{module}"')
            source = source.replace('"cli.process_contests"', '"app.cli.process_contests"').replace('"cli.user_stats"', '"app.cli.user_stats"')
            # The new cold-import test deliberately exercises legacy imports.
            files[path] = source
    return mapping, files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    mapping, files = generate()
    for path, source in files.items():
        ast.parse(source)
        target = ROOT / path
        if args.write:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="\n") as output:
                output.write(source)
        else:
            assert target.read_text(encoding="utf-8") == source, path
    removed = set(mapping) - set(files)
    for path in removed:
        target = ROOT / path
        if args.write:
            target.unlink(missing_ok=True)
        else:
            assert not target.exists(), path
    print(f"{len(mapping)} implementation files: moved; {len(files)} whole files match; {len(removed)} old implementation files removed")
