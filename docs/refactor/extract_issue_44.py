"""Reproduce issue #44's mechanical source extraction at its fixed baseline.

Default: compare generated files. --write: reproduce this extraction only;
do not use it to update files changed by later refactors.
"""

import argparse
import ast
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "b471c187e74b0ae3bd6ee41ab9eb3179db02fbe9"


def original(path):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT).decode("utf-8")


def generate():
    source = original("blueprints/interactions.py")
    tree = ast.parse(source)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    lines = source.splitlines(keepends=True)

    def copy(nodes):
        return textwrap.dedent("".join(lines[nodes[0].lineno - 1:nodes[-1].end_lineno]))

    def http(nodes):
        return copy(nodes).replace("jsonify(", "(")

    def function(name, args, body):
        return f"def {name}({args}):\n" + textwrap.indent(body, "    ")

    bookmark = functions["set_bookmark"].body[-1]
    like = functions["set_like"].body[-1]
    assert isinstance(bookmark, ast.Try) and isinstance(like, ast.Try)
    assert ast.get_source_segment(source, bookmark.body[2]) == 'is_bookmarked = request.method == "PUT"'
    assert ast.get_source_segment(source, like.body[6]) == 'is_liked = request.method == "PUT"'
    service = '''"""Bookmark and like queries, validation, mutations and conflict recovery."""

from datetime import datetime, timezone

from models import Bookmark, Post, Vote, db
from services import notifications as notifications_service


'''
    service += "\n\n".join([
        function("get_bookmark_post", "post_id", http(bookmark.body[:2]) + "return post, 200\n"),
        function("set_bookmark", "post_id, user_id, post, is_bookmarked", http(bookmark.body[3:])),
        function("recover_bookmark", "post_id", http(bookmark.handlers[0].body[1].body)),
        function("prepare_like", "post_id, user_id",
                 http(like.body[:6]).replace("), 403", "), None, 403") + "return post, c, 200\n"),
        function("set_like", "post_id, user_id, post, c, is_liked", http(like.body[7:])),
        function("recover_like", "post_id, user_id", http(like.handlers[0].body[1:])),
    ])
    # Replace only selected bodies. Original exception clauses, rollback,
    # logging, traceback, decorators and method-read positions remain intact.
    edits = [
        (bookmark.body, '''post, status = interaction_service.get_bookmark_post(post_id)
if status != 200:
    return jsonify(post), status
is_bookmarked = request.method == "PUT"
result, status = interaction_service.set_bookmark(post_id, user_id, post, is_bookmarked)
return jsonify(result), status
''', 8),
        (bookmark.handlers[0].body[1].body, '''recovered = interaction_service.recover_bookmark(post_id)
if recovered is not None:
    return jsonify(recovered[0]), recovered[1]
''', 12),
        (like.body, '''post, c, status = interaction_service.prepare_like(post_id, user_id)
if status != 200:
    return jsonify(post), status
is_liked = request.method == "PUT"
result, status = interaction_service.set_like(post_id, user_id, post, c, is_liked)
return jsonify(result), status
''', 8),
        (like.handlers[0].body[1:], '''result, status = interaction_service.recover_like(post_id, user_id)
return jsonify(result), status
''', 8),
    ]
    for nodes, replacement, indent in sorted(edits, key=lambda edit: edit[0][0].lineno, reverse=True):
        lines[nodes[0].lineno - 1:nodes[-1].end_lineno] = [textwrap.indent(replacement, " " * indent)]
    routes = "".join(lines).replace("from datetime import datetime, timezone\n", "")
    routes = routes.replace("from models import Bookmark, Post, Vote, db", "from models import db")
    routes = routes.replace("from services import notifications as notifications_service",
                            "from services import interactions as interaction_service")
    fixture = original("tests/conftest.py").replace(
        "from blueprints import interactions as interaction_routes",
        "from services import interactions as interaction_service"
    ).replace('monkeypatch.setattr(interaction_routes, "datetime", FixedDateTime)',
              'monkeypatch.setattr(interaction_service, "datetime", FixedDateTime)')
    return {"services/interactions.py": service, "blueprints/interactions.py": routes,
            "tests/conftest.py": fixture}


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
        print(f"{path}: {'written from baseline source' if args.write else 'source matches extraction'}")
