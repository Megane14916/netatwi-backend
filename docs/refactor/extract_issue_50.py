"""Reproduce #50 from fixed source slices; default compares whole files.

--write reproduces this extraction only and must not overwrite later refactors.
Function bodies are copied, never regenerated with ast.unparse.
"""

import argparse
import ast
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "46d312ee22f1990e6ab194c26f8ba941621f18e7"
SETTINGS = ("UPLOAD_FOLDER", "ALLOWED_EXTENSIONS", "USE_R2", "R2_BUCKET_NAME", "R2_PUBLIC_URL")
HELPERS = ("allowed_file", "calculate_weighted_length", "save_file", "delete_file", "get_cached_contest_results", "generate_contest_results")


def original(path):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT).decode("utf-8")


def functions(source):
    return {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}


def copy(source, nodes):
    return textwrap.dedent("".join(source.splitlines(keepends=True)[nodes[0].lineno - 1:nodes[-1].end_lineno]))


def replace(source, nodes, replacement):
    lines = source.splitlines(keepends=True)
    lines[nodes[0].lineno - 1:nodes[-1].end_lineno] = [replacement]
    return "".join(lines)


def generate():
    entry = original("app.py")
    entry_nodes = ast.parse(entry).body
    names = functions(entry)
    first = next(i for i, n in enumerate(entry_nodes) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == SETTINGS[0])
    last = next(i for i, n in enumerate(entry_nodes) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == SETTINGS[-1])
    setting_nodes = entry_nodes[first:last + 1]
    image_settings = "def initialize_image_settings():\n" + textwrap.indent(copy(entry, setting_nodes), "    ")
    image_settings += "    return " + ", ".join(SETTINGS) + "\n"
    images = original("integrations/images.py") + "\n\n" + image_settings
    text = '"""Weighted text length with the original URL and character rules."""\n\nimport re\n\n\n'
    text += "# --- 文字数カウントロジック (追加) ---\n" + copy(entry, [names["calculate_weighted_length"]])
    lifecycle = original("services/contest_lifecycle.py")
    scheduler = functions(lifecycle)["schedule_contest_task"]
    dependencies = original("blueprints/dependencies.py").replace(
        '"""Call helpers retained in app.py while route groups are being moved."""',
        '"""Application-scoped helper callbacks shared by services and routes."""', 1)
    dependencies += "\n\n" + copy(lifecycle, [scheduler])
    bindings = copy(entry, names["_register_extracted_routes"].body[:2])
    bindings = bindings.replace("lambda: logger", 'lambda: namespace["logger"]')
    for name in ("schedule_contest_task",) + HELPERS:
        before = f"lambda *args: {name}(*args)"
        assert bindings.count(before) == 1, name
        bindings = bindings.replace(before, f'lambda *args: namespace["{name}"](*args)')
    dependencies += '\n\ndef register_helper_bindings(application, namespace):\n'
    dependencies += "    # Keep the original app globals live, including the __main__ namespace.\n"
    dependencies += textwrap.indent(bindings, "    ")
    compatibility = '"""Compatibility imports for helpers now owned by runtime_dependencies."""\n\n'
    compatibility += "from runtime_dependencies import (\n"
    compatibility += "".join(f"    {name},\n" for name in ("_call", "route_logger") + HELPERS)
    compatibility += ")\n"
    # Replace bottom ranges first so the fixed AST coordinates stay valid.
    entry = replace(entry, names["_register_extracted_routes"].body[:2],
                    "    runtime_dependencies.register_helper_bindings(application, globals())\n")
    entry = replace(entry, [names["calculate_weighted_length"]], "from services.text import calculate_weighted_length\n")
    entry = replace(entry, setting_nodes,
                    "(" + ", ".join(SETTINGS) + ") = image_storage.initialize_image_settings()\n")
    entry = entry.replace("from app_factory import create_base_app\n", "from app_factory import create_base_app\nimport runtime_dependencies\n", 1)
    lifecycle = replace(lifecycle, [scheduler], "")
    lifecycle = lifecycle.replace("from flask import current_app", "from runtime_dependencies import schedule_contest_task", 1)
    return {
        "runtime_dependencies.py": dependencies,
        "blueprints/dependencies.py": compatibility,
        "services/text.py": text,
        "integrations/images.py": images,
        "app.py": entry,
        "services/contest_lifecycle.py": lifecycle,
        "services/posts.py": original("services/posts.py").replace("from blueprints.dependencies import (", "from runtime_dependencies import (", 1),
        "services/voting.py": original("services/voting.py").replace("from blueprints.dependencies import ", "from runtime_dependencies import ", 1),
        "blueprints/voting.py": original("blueprints/voting.py").replace("from .dependencies import ", "from runtime_dependencies import ", 1),
    }


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
