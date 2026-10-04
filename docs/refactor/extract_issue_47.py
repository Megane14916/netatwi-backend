"""Reproduce issue #47 by copying source slices from fixed commits.

Default compares generated whole files. --write reproduces this extraction
only; do not use it to overwrite changes from later refactors.
"""

import argparse
import ast
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "b523da12e4d7650329b3e21d217578122ed79221"
TEST_BASELINE = "fed9d0657709e0d56d759a0e8dd16a44d02248c5"


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def generate():
    source = original("blueprints/profile.py")
    tree = ast.parse(source)
    route = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    block = route.body[0]
    assert isinstance(block, ast.Try)
    assert ast.get_source_segment(source, block.body[4]) == 'viewer_id = session.get("user_id")'
    assert isinstance(block.body[3], ast.FunctionDef) and block.body[3].name == "log_step"
    lines = source.splitlines(keepends=True)

    def copy(nodes):
        return textwrap.dedent("".join(lines[nodes[0].lineno - 1:nodes[-1].end_lineno]))

    service = '''"""Profile queries, visibility and presentation with original result reuse."""

'''
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module in (
        "datetime", "sqlalchemy.orm", "models", "services")]
    service += "".join(copy([n]) for n in imports) + "\n\n"
    constant = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "JST")
    service += copy([constant]) + "\n\n"
    timing = copy(block.body[1:4]) + "return log_step\n"
    service += "def prepare_profile_timing(time):\n" + textwrap.indent(timing, "    ")
    body = copy(block.body[5:])
    assert body.count('return jsonify({"error": "Not found"}), 404') == 1
    assert body.count("return jsonify(res_json)") == 1
    body = body.replace('return jsonify({"error": "Not found"}), 404', 'return ({"error": "Not found"}), 404')
    body = body.replace("return jsonify(res_json)", "return res_json, 200")
    service += "\n\ndef get_user_profile(screen_name, viewer_id, log_step):\n" + textwrap.indent(body, "    ")

    adapter = copy(block.body[:1]) + "\nlog_step = profile_service.prepare_profile_timing(time)\n"
    adapter += copy(block.body[4:5])
    adapter += '''payload, status = profile_service.get_user_profile(screen_name, viewer_id, log_step)
return jsonify(payload), status
'''
    lines[block.body[0].lineno - 1:block.body[-1].end_lineno] = [textwrap.indent(adapter, "        ")]
    routes = "".join(lines)
    for node in imports:
        if node.module != "services":
            routes = routes.replace(copy([node]), "")
        else:
            routes = routes.replace(copy([node]), "from services import profile as profile_service\n")
    routes = routes.replace(copy([constant]), "")
    fixture = original("tests/conftest.py").replace("from blueprints import profile as profile_routes", "from services import profile as profile_service")
    fixture = fixture.replace("profile_routes", "profile_service")
    test = original("tests/test_profile_service_contract.py", TEST_BASELINE).replace(
        "from blueprints import profile as query_module", "from services import profile as query_module")
    return {"services/profile.py": service, "blueprints/profile.py": routes,
            "tests/conftest.py": fixture, "tests/test_profile_service_contract.py": test}


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
