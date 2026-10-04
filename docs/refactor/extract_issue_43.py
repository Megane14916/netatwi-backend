"""Reproduce issue #43's source slicing (no AST body regeneration).

Without --write this checks the generated files. --write is only for reproducing
this extraction at its fixed baseline, not for updating subsequent refactors.
"""

import argparse
import ast
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "5b93a8680467b375d26f209fd85d65f71bcb3282"


def generate():
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:blueprints/comments.py"], cwd=ROOT
    ).decode("utf-8")
    tree = ast.parse(source)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    lines = source.splitlines(keepends=True)

    def copy(nodes):
        return textwrap.dedent("".join(lines[nodes[0].lineno - 1:nodes[-1].end_lineno]))

    def http_body(nodes, status=None):
        body = copy(nodes).replace("jsonify(", "(")
        if status is not None:
            body = body.rstrip() + f", {status}\n"
        return body

    def function(name, args, body):
        return f"def {name}({args}):\n" + textwrap.indent(body, "    ")

    get = functions["get_comments"].body
    multiple = functions["get_multiple_comments"].body
    add = functions["add_comment"].body
    modify = functions["modify_comment"].body
    assert ast.get_source_segment(source, add[2]) == "post = Post.query.get_or_404(post_id)"
    assert ast.get_source_segment(source, add[6]) == "is_judge = post.contest_id in judge_contests"
    assert isinstance(modify[4], ast.If) and len(modify[4].body) == 5
    service = '''"""Comment queries, validation and mutations with the original write order."""

from datetime import timedelta, timezone

from models import Comment, Post, db
from services import notifications as notifications_service


JST = timezone(timedelta(hours=9), "JST")


'''
    service += "\n\n".join([
        function("get_comments", "post_id", http_body(get)),
        function("get_multiple_comments", "post_ids", http_body(multiple[3:])),
        function("get_post", "post_id", copy(add[2:3]).replace("post = ", "return ", 1)),
        function("add_comment", "post_id, user_id, post, raw_content, judge_contests", http_body(add[6:])),
        function("get_comment_for_modification", "comment_id, user_id",
                 http_body(modify[2:4]) + "return comment, 200\n"),
        function("delete_comment", "comment", http_body(modify[4].body, 200)),
        function("update_comment", "comment, raw_content", http_body(modify[7:], 200)),
    ])

    # Replace only function bodies, retaining the original decorators and headers.
    adapters = {
        "get_comments": '''return jsonify(comments_service.get_comments(post_id))
''',
        "get_multiple_comments": copy(multiple[:3]) + '''return jsonify(comments_service.get_multiple_comments(post_ids))
''',
        "add_comment": copy(add[:2]) + '''post = comments_service.get_post(post_id)
''' + copy(add[3:6]) + '''result, status = comments_service.add_comment(
    post_id, user_id, post, raw_content, judge_contests
)
return jsonify(result), status
''',
        "modify_comment": copy(modify[:2]) + '''comment, status = comments_service.get_comment_for_modification(comment_id, user_id)
if status != 200:
    return jsonify(comment), status

if request.method == "DELETE":
    result, status = comments_service.delete_comment(comment)
    return jsonify(result), status

''' + copy(modify[5:7]) + '''result, status = comments_service.update_comment(comment, raw_content)
return jsonify(result), status
''',
    }
    for name, before in sorted(functions.items(), key=lambda pair: pair[1].lineno, reverse=True):
        lines[before.body[0].lineno - 1:before.end_lineno] = [textwrap.indent(adapters[name], "    ")]
    routes = "".join(lines)
    routes = routes.replace("from datetime import timedelta, timezone\n\n", "")
    routes = routes.replace("from models import Comment, Post, db\nfrom services import notifications as notifications_service",
                            "from services import comments as comments_service")
    routes = routes.replace('JST = timezone(timedelta(hours=9), "JST")\n', "")
    return {"services/comments.py": service, "blueprints/comments.py": routes}


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
