"""Reproduce #51 using original source slices and explicit name adapters.

Default compares whole files; --write reproduces this extraction only.
Never use --write to overwrite later refactors. No ast.unparse body generation.
"""

import argparse
import ast
import io
from pathlib import Path
import subprocess
import tokenize


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "2c69378a995c27c7e2d999e56560a7d36426fc9f"


def original(path):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT).decode("utf-8")


def copy(source, nodes):
    return "".join(source.splitlines(keepends=True)[nodes[0].lineno - 1:nodes[-1].end_lineno])


def imported_names(nodes):
    return [alias.asname or alias.name for node in nodes for alias in node.names]


def adapt(source, names):
    """Replace only AST-located Name tokens and globals(), keeping all other source."""
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in names:
            replacement = f'namespace["{node.id}"]'
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "globals":
            assert not node.args and not node.keywords
            replacement = "namespace"
        else:
            continue
        edits.append((offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset, replacement))
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def export(names):
    return "namespace.update({\n" + "".join(f'    "{name}": {name},\n' for name in names) + "})\n"


def indent_preserving_strings(source):
    # Indent code but leave multiline literal contents (including __doc__) exact.
    literal_lines = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING and token.start[0] < token.end[0]:
            literal_lines.update(range(token.start[0] + 1, token.end[0] + 1))
    return "".join(line if i in literal_lines or not line.strip() else "    " + line
                   for i, line in enumerate(source.splitlines(keepends=True), 1))


def generate():
    entry = original("app.py")
    nodes = ast.parse(entry).body
    functions = {n.name: n for n in nodes if isinstance(n, ast.FunctionDef)}
    early = [n for n in nodes[:nodes.index(functions["get_r2_client"])] if isinstance(n, (ast.Import, ast.ImportFrom))]
    late = [n for n in nodes[nodes.index(functions["schedule_contest_task"]) + 1:nodes.index(functions["_register_extracted_routes"])]]
    assert all(isinstance(n, ast.ImportFrom) for n in late)
    start = next(i for i, n in enumerate(nodes) if isinstance(n, ast.Assign))
    runtime = nodes[start:nodes.index(functions["get_r2_client"])]
    assert all(isinstance(n, ast.Assign) for n in runtime)
    runtime_names = [n.id for statement in runtime for target in statement.targets for n in ast.walk(target) if isinstance(n, ast.Name)]
    helpers = nodes[nodes.index(functions["get_r2_client"]):nodes.index(functions["schedule_contest_task"]) + 1]
    helper_names = [n.name for n in helpers if isinstance(n, ast.FunctionDef)] + ["calculate_weighted_length"]
    names = set(imported_names(early) + imported_names(late) + runtime_names + helper_names + ["_register_extracted_routes", "__name__"])
    base = original("app_factory.py")
    base_nodes = ast.parse(base).body
    base_function = next(n for n in base_nodes if isinstance(n, ast.FunctionDef))
    self_import = next(n for n in early if isinstance(n, ast.ImportFrom) and n.module == "app_factory")
    header = '"""Application creation, runtime compatibility bindings and registration."""\n\n'
    header += copy(entry, early[:early.index(self_import)])
    header += "\n" + copy(base, base_nodes[2:-1])  # logging already imported above
    header += "\n" + copy(entry, early[early.index(self_import) + 1:])
    factory = header + "\n\n" + copy(base, [base_function])
    body = export(imported_names(early))
    body += "\n" + adapt(copy(entry, runtime), names)
    body += "\n\n" + adapt(copy(entry, helpers), names)
    body += "\n\n" + export(helper_names)
    body += "\n" + copy(entry, late) + "\n" + export(imported_names(late))
    body += "\n\n" + adapt(copy(entry, [functions["_register_extracted_routes"]]), names)
    body += '\nnamespace["_register_extracted_routes"] = _register_extracted_routes\n\n'
    registration = nodes[nodes.index(functions["_register_extracted_routes"]) + 1:nodes.index(functions["create_app"])]
    assert len(registration) == 2 and all(isinstance(n, ast.Expr) for n in registration)
    body += adapt(copy(entry, registration), names)
    create = functions["create_app"]
    assert ast.get_source_segment(entry, create.body[4].targets[0]) == "registered_endpoints"
    assert all(isinstance(n, ast.For) for n in create.body[5:7])
    create_lines = copy(entry, [create]).splitlines(keepends=True)
    del create_lines[create.body[4].lineno - create.lineno:create.body[6].end_lineno - create.lineno + 1]
    body += "\n\n" + adapt("".join(create_lines), names)
    body += '\nnamespace["create_app"] = create_app\n'
    factory += "\n\ndef initialize_application(namespace):\n"
    factory += '    """Populate an entry namespace, preserving its live compatibility seams."""\n'
    factory += indent_preserving_strings(body)
    main = nodes[-1]
    assert isinstance(main, ast.If)
    compatibility = '"""Application compatibility exports and direct server entry."""\n\n'
    compatibility += "from app_factory import initialize_application\n\n\ninitialize_application(globals())\n\n\n"
    compatibility += copy(entry, [main])
    return {"app_factory.py": factory, "app.py": compatibility}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    for path, source in generate().items():
        ast.parse(source)
        if args.write:
            with (ROOT / path).open("w", encoding="utf-8", newline="\n") as output:
                output.write(source)
        else:
            assert (ROOT / path).read_text(encoding="utf-8") == source, path
        print(f"{path}: {'written from baseline slices' if args.write else 'whole source matches'}")
