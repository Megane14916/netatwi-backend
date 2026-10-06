"""Check business function bodies with only #69 dependency substitutions."""
import ast
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "975e63791f6bbc3b772b366afe4b560392721a9d"


def functions(source):
    lines = source.splitlines(True)
    return {n.name: "".join(lines[n.lineno-1:n.end_lineno]) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}


def main():
    checked = 0
    for name in ["services/posts", "services/voting", "services/contest_lifecycle", "services/auth", "services/contest_posts", "services/contests", "routes/auth", "routes/voting", "hooks", "integrations/x_oauth", "integrations/images", "integrations/cloud_tasks"]:
        path = f"app/{name}.py"
        old = functions(subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT).decode("utf-8"))
        new = functions((ROOT / path).read_text(encoding="utf-8"))
        for function, body in old.items():
            if name == "integrations/images":
                if function not in {"save_file", "delete_file"}:
                    continue  # New active-config/client boundaries tested independently.
                updated = new["_"+function].replace("def _"+function, "def "+function, 1)
            else:
                updated = new[function]
                if name == "integrations/cloud_tasks" and function == "schedule_contest_task":
                    # Keep request, timestamp, exception and enqueue behavior after client selection.
                    assert body[body.index("    parent ="): ] == updated[updated.index("    parent ="): ]
                    checked += 1
                    continue
                body = re.sub(r"(?<![\w.])logger\.", "current_app.logger.", body)
                if name == "services/posts":
                    for helper in ("allowed_file", "save_file", "delete_file"):
                        body = re.sub(r"(?<![\w.])"+helper+r"\(", "images."+helper+"(", body)
                if name == "services/contest_lifecycle":
                    body = body.replace("schedule_contest_task(", "cloud_tasks.schedule_contest_task(")
                if name == "services/contests":
                    body = body.replace("global _contests_cache, _contests_cache_time", "cache = contest_cache()")
                    body = body.replace("_contests_cache_time", 'cache["time"]').replace("_contests_cache", 'cache["payload"]')
                if name == "integrations/x_oauth":
                    body = body.replace("X_CLIENT_ID", 'current_app.config["X_CONSUMER_KEY"]').replace("X_CLIENT_SECRET", 'current_app.config["X_CONSUMER_SECRET"]')
            assert ast.dump(ast.parse(body), include_attributes=False) == ast.dump(ast.parse(updated), include_attributes=False), (path, function)
            checked += 1
    print(f"{checked} business functions preserve their bodies after explicit dependency substitutions")


if __name__ == "__main__":
    main()
