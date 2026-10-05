"""Reproduce issue #48 from fixed source slices without unparsing bodies.

Default compares whole generated files. --write reproduces only this
extraction; do not use it to overwrite changes made by later issues.
"""

import argparse
import ast
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "52f1ad79ea8d67d717fbdbe6d4f486794d4448da"
TEST_BASELINE = "5304acdd8cc9700e2425ae043b2b7ef21a88f62e"


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def generate():
    source = original("blueprints/news.py")
    tree = ast.parse(source)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    lines = source.splitlines(keepends=True)

    def copy(nodes):
        return textwrap.dedent("".join(lines[nodes[0].lineno - 1:nodes[-1].end_lineno]))

    model_import = next(n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "models")
    service = '''"""News queries, tweet ID parsing and database writes with original boundaries."""

''' + copy([model_import]) + "\n\n"
    specs = [("get_news", "", 0, 1), ("get_admin_news", "", 0, 1),
             ("add_news", "tweet_id", 2, 2), ("delete_news", "id", 0, 2)]
    edits = []
    for name, args, start, expected_returns in specs:
        block = next(n for n in functions[name].body if isinstance(n, ast.Try))
        nodes = block.body[start:]
        assert not any(isinstance(n, ast.FunctionDef) for statement in nodes for n in ast.walk(statement))
        calls = [n for statement in nodes for n in ast.walk(statement)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "jsonify"]
        assert len(calls) == expected_returns
        body = copy(nodes)
        assert body.count("jsonify(") == expected_returns
        body = body.replace("jsonify(", "(")
        service += f"def {name}({args}):\n" + textwrap.indent(body, "    ") + "\n\n"
        adapter = f"payload, status = news_service.{name}({args})\nreturn jsonify(payload), status\n"
        edits.append((nodes[0].lineno - 1, nodes[-1].end_lineno, textwrap.indent(adapter, "        ")))
    for start, end, adapter in sorted(edits, reverse=True):
        lines[start:end] = [adapter]
    routes = "".join(lines).replace(copy([model_import]), "from models import db\nfrom services import news as news_service\n")
    service = service.rstrip() + "\n"
    # Keep every added test exactly as it passed against the original code.
    test = original("tests/test_news_service_contract.py", TEST_BASELINE)
    return {"services/news.py": service, "blueprints/news.py": routes,
            "tests/test_news_service_contract.py": test}


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
