"""Inspect the final explicit module dependencies and responsibility boundaries."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    paths = {path.relative_to(ROOT).with_suffix("").as_posix().removesuffix("/__init__").replace("/", "."): path for path in (ROOT / "app").rglob("*.py")}
    trees = {name: ast.parse(path.read_text(encoding="utf-8")) for name, path in paths.items()}
    edges = {name: set() for name in paths}
    for name, path in paths.items():
        parent = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(trees[name]):
            if isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = parent.split(".")[:len(parent.split(".")) - node.level + 1] if node.level else []
                module = ".".join(prefix + ([node.module] if node.module else []))
                candidates = [module, *[module + "." + alias.name for alias in node.names]]
            else:
                continue
            edges[name].update(candidate for candidate in candidates if candidate in paths)

    visited, active = set(), []

    def visit(name):
        assert name not in active, "Explicit import cycle: " + " -> ".join(active + [name])
        if name in visited:
            return
        active.append(name)
        for target in sorted(edges[name]):
            visit(target)
        active.pop()
        visited.add(name)

    for name in edges:
        visit(name)
    assert not [(name, target) for name, targets in edges.items() if name.startswith("app.services") for target in targets if target.startswith("app.routes")]

    handlers = []
    for name, tree in trees.items():
        if not name.startswith("app.routes."):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr != "query", name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                # Existing rollback/exception boundaries stay at their old route positions.
                assert not (isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "db" and node.func.value.attr == "session" and node.func.attr != "rollback"), name
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and any(isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "route" for decorator in node.decorator_list):
                handlers.append(node.name)
    assert len(handlers) == len(set(handlers)) == 35

    constructors = {constructor: [] for constructor in ("SQLAlchemy", "Migrate", "Limiter", "Flask")}
    models = []
    for name, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in constructors:
                constructors[node.func.id].append(name)
            if isinstance(node, ast.ClassDef) and any(isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id == "db" and base.attr == "Model" for base in node.bases):
                assert name.startswith("app.models.")
                models.append(node.name)
    assert constructors == {"SQLAlchemy": ["app.extensions"], "Migrate": ["app.extensions"], "Limiter": ["app.extensions"], "Flask": ["app.factory"]}
    assert len(models) == len(set(models)) == 10
    print(f"{len(paths)} canonical modules; {sum(map(len, edges.values()))} explicit import edges; no cycles or service-to-route dependencies")
    print("35 unique route handlers; no route queries/DB operations except retained rollback boundaries")
    print("Single construction sites for db/migrate/limiter and Flask factory; 10 unique canonical model definitions")
