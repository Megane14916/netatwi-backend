"""Verify #70 only changes entry/registration and canonical db imports."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "2c57f8008f38d7e38671b5ca833f45e823f49447"


def without_imports(source):
    class RemoveImports(ast.NodeTransformer):
        def visit_Import(self, node):
            return None

        def visit_ImportFrom(self, node):
            return None
    tree = RemoveImports().visit(ast.parse(source))
    return ast.dump(tree, include_attributes=False)


def main():
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "app"], cwd=ROOT, text=True).splitlines()
    checked = 0
    for name in names:
        if name in {"app/__init__.py", "app/factory.py", "app/models/__init__.py", "app/models/base.py"}:
            continue
        old = subprocess.check_output(["git", "show", f"{BASE}:{name}"], cwd=ROOT).decode("utf-8")
        assert without_imports(old) == without_imports((ROOT / name).read_text(encoding="utf-8-sig")), name
        checked += 1
    package = (ROOT / "app/__init__.py").read_text(encoding="utf-8-sig")
    assert "__getattr__" not in package and "_RUNTIME_EXPORTS" not in package
    assert '"wsgi:app"' in (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert not (ROOT / "app/models/base.py").exists()
    print(f"{checked} application modules preserve non-import AST; explicit entries verified")


if __name__ == "__main__":
    main()
