"""Reproduce issue #45's mechanical source extraction at its fixed baseline.

Default: compare generated files. --write: reproduce only this extraction;
do not use it to update files changed by later refactors.
"""

import argparse
import ast
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "4f6f70c05b3455f80927cbedc9979e58bda23248"
TEST_BASELINE = "a5bbf9950f4f3d055d335edb65139b8ab0490dbc"


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def generate():
    public_source = original("blueprints/contests.py")
    admin_source = original("blueprints/admin.py")
    public_tree, admin_tree = ast.parse(public_source), ast.parse(admin_source)
    public = {n.name: n for n in public_tree.body if isinstance(n, ast.FunctionDef)}
    admin = {n.name: n for n in admin_tree.body if isinstance(n, ast.FunctionDef)}
    listing, details = public["get_contests"], public["get_contest_details"]
    management = admin["get_management_contests"]
    assert isinstance(listing.body[-1], ast.Try) and isinstance(details.body[-1], ast.Try)
    assert ast.get_source_segment(public_source, details.body[-1].body[3]) == 'user_id = session.get("user_id")'

    def copy(source, nodes):
        return textwrap.dedent("\n".join(source.splitlines()[nodes[0].lineno - 1:nodes[-1].end_lineno])) + "\n"

    def http(source, nodes):
        return copy(source, nodes).replace("jsonify(", "(")

    def function(name, args, body):
        return f"def {name}({args}):\n" + textwrap.indent(body, "    ")

    constants = [n for n in public_tree.body if isinstance(n, ast.Assign)]
    assert [n.targets[0].id for n in constants] == ["bp", "logger", "JST", "_contests_cache", "_contests_cache_time"]
    service = '''"""Public and management contest queries with the original shared cache."""

import logging
from datetime import datetime, timedelta, timezone

from models import Contest, ContestResult


'''
    service += copy(public_source, constants[1:]) + "\n\n"
    service += "\n\n".join([
        function("get_cached_contests", "time", copy(public_source, listing.body[:1])
                 + http(public_source, listing.body[2:3]).replace("return (_contests_cache)", "return True, _contests_cache")
                 + "return False, None\n"),
        function("get_contests", "time", copy(public_source, listing.body[:1]) + http(public_source, listing.body[-1].body)),
        function("get_contest_for_details", "id, start_time, time",
                 copy(public_source, details.body[-1].body[:3]) + "return contest\n"),
        function("get_contest_details", "contest, user_id, start_time, time",
                 http(public_source, details.body[-1].body[4:])),
        function("get_management_contests", "", http(admin_source, management.body[-1].body)),
    ])

    def replace_ranges(source, edits):
        lines = source.splitlines(keepends=True)
        for nodes, replacement, indent in sorted(edits, key=lambda edit: edit[0][0].lineno, reverse=True):
            lines[nodes[0].lineno - 1:nodes[-1].end_lineno] = [textwrap.indent(replacement, " " * indent)]
        return "".join(lines)

    public_routes = replace_ranges(public_source, [
        (listing.body[:3], copy(public_source, listing.body[1:2]) + '''
cache_hit, cached = contest_service.get_cached_contests(time)
if cache_hit:
    return jsonify(cached)
''', 4),
        (listing.body[-1].body, "return jsonify(contest_service.get_contests(time))\n", 8),
        (details.body[-1].body[:3], "contest = contest_service.get_contest_for_details(id, start_time, time)\n", 8),
        (details.body[-1].body[4:], "return jsonify(contest_service.get_contest_details(contest, user_id, start_time, time))\n", 8),
    ])
    public_routes = public_routes.replace("import logging\nfrom datetime import datetime, timedelta, timezone\n\n", "")
    public_routes = public_routes.replace("from models import Contest, ContestResult", "from services import contests as contest_service")
    constant_source = copy(public_source, constants[1:])
    assert constant_source in public_routes
    public_routes = public_routes.replace(constant_source, "")
    admin_routes = replace_ranges(admin_source, [
        (management.body[-1].body, "return jsonify(contest_service.get_management_contests())\n", 8),
    ])
    admin_routes = admin_routes.replace("from datetime import datetime, timedelta, timezone\n", "")
    admin_routes = admin_routes.replace("from models import Contest, db", "from models import db")
    admin_routes = admin_routes.replace("from services import contest_lifecycle\n", "from services import contest_lifecycle\nfrom services import contests as contest_service\n")
    admin_routes = admin_routes.replace('JST = timezone(timedelta(hours=9), "JST")\n', "")
    fixture = original("tests/conftest.py").replace("from blueprints import admin as admin_routes  # noqa: E402\n", "")
    fixture = fixture.replace("from blueprints import contests as contest_routes", "from services import contests as contest_service")
    fixture = fixture.replace("contest_routes", "contest_service").replace('        monkeypatch.setattr(admin_routes, "datetime", FixedDateTime)\n', "")
    test = original("tests/test_contest_query_service_contract.py", TEST_BASELINE)
    test = test.replace("from blueprints import contests as query_module", "from services import contests as query_module")
    return {"services/contests.py": service, "blueprints/contests.py": public_routes,
            "blueprints/admin.py": admin_routes, "tests/conftest.py": fixture,
            "tests/test_contest_query_service_contract.py": test}


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
