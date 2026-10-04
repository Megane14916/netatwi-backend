"""Reproduce issue #46 from fixed source slices, without unparsing bodies.

Default compares whole generated files. --write reproduces this extraction
only; do not use it to update files modified by later issues.
"""

import argparse
import ast
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "be9957eaaf83721ab65db013724949cf4a1937fb"
TEST_BASELINE = "96fc9365070215e20d3cc39aa70dc59a572e81e5"


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def generate():
    source = original("blueprints/posts.py")
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_posts_for_contest")
    block = function.body[-1]
    assert isinstance(block, ast.Try)
    assert ast.get_source_segment(source, block.body[6]) == 'user_id = session.get("user_id")'
    assert isinstance(block.body[-1], ast.Return) and block.body[-1].value.func.id == "jsonify"
    lines = source.splitlines(keepends=True)

    def copy(nodes):
        return textwrap.dedent("".join(lines[nodes[0].lineno - 1:nodes[-1].end_lineno]))

    service = '''"""Contest post queries and viewer display data with original read ordering."""

import logging
from datetime import timedelta, timezone

from models import Contest, Post, Vote


'''
    constants = [n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id in ("logger", "JST")]
    service += copy(constants) + "\n\n"
    prefix = copy(block.body[:6]) + "return c, posts, t2\n"
    service += "def get_posts_for_listing(id, start_time, time):\n" + textwrap.indent(prefix, "    ")
    suffix = textwrap.dedent("".join(lines[block.body[7].lineno - 1:block.handlers[0].lineno - 1]))
    assert suffix.count("return jsonify(") == 1
    suffix = suffix.replace("return jsonify(", "return (", 1)
    service += "\n\ndef get_posts_for_contest(id, c, posts, user_id, t2, start_time, time):\n" + textwrap.indent(suffix, "    ")

    adapter = 'c, posts, t2 = contest_post_service.get_posts_for_listing(id, start_time, time)\n'
    adapter += copy(block.body[6:7])
    adapter += '''return jsonify(
    contest_post_service.get_posts_for_contest(id, c, posts, user_id, t2, start_time, time)
)
'''
    lines[block.body[0].lineno - 1:block.handlers[0].lineno - 1] = [textwrap.indent(adapter, "        ")]
    routes = "".join(lines).replace("import logging\n", "")
    routes = routes.replace("from models import Contest, Post, Vote, db", "from models import db")
    routes = routes.replace("from services import posts as post_service\n", "from services import posts as post_service\nfrom services import contest_posts as contest_post_service\n")
    routes = routes.replace(copy(constants[:1]), "")
    test = original("tests/test_contest_post_query_service_contract.py", TEST_BASELINE)
    test = test.replace("from blueprints import posts as query_module", "from services import contest_posts as query_module")
    return {"services/contest_posts.py": service, "blueprints/posts.py": routes,
            "tests/test_contest_post_query_service_contract.py": test}


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
