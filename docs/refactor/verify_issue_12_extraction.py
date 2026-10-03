"""Compare extracted statements and HTTP adapters against pre-issue-12 master."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "48c1b76"


def dump(node):
    return ast.dump(node, include_attributes=False)


def statements(source):
    return ast.parse(source).body


def functions(tree):
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def module_body(nodes):
    return ast.Module(body=nodes, type_ignores=[])


def adapt_returns(nodes, values):
    tree = module_body(deepcopy(nodes))
    returns = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.Return)),
        key=lambda node: node.lineno,
    )
    assert len(returns) == len(values)
    for node, value in zip(returns, values):
        node.value = ast.parse(value, mode="eval").body
    return tree.body


def verify():
    before_source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:blueprints/auth.py"], cwd=ROOT
    ).decode("utf-8")
    before_tree = ast.parse(before_source)
    before = functions(before_tree)
    route_tree = ast.parse((ROOT / "blueprints/auth.py").read_text(encoding="utf-8"))
    routes = functions(route_tree)
    service_tree = ast.parse((ROOT / "services/auth.py").read_text(encoding="utf-8"))
    services = functions(service_tree)
    integration_tree = ast.parse((ROOT / "integrations/x_oauth.py").read_text(encoding="utf-8"))
    integrations = functions(integration_tree)
    login, callback, judge = (before[name] for name in ("twitter_login", "twitter_callback", "judge_login"))
    lb = login.body[0].body
    callback_try = next(node for node in callback.body if isinstance(node, ast.Try))
    judge_try = next(node for node in judge.body if isinstance(node, ast.Try))
    cb = callback_try.body
    sync_index = next(i for i, node in enumerate(cb) if isinstance(node, ast.Assign)
                      and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "twitter_id")

    expected_functions = {
        "start_twitter_login": (services, "", lb[:2] + statements(
            "authorization_url, state, code_verifier = x_oauth.build_authorization(callback_url)"
        ) + lb[8:-1] + statements("return authorization_url")),
        "begin_twitter_callback": (services, "", callback.body[:4] + statements(
            "return session_state, code_verifier"
        )),
        "validate_twitter_callback": (services, "session_state, code_verifier, url_state, code, error",
            adapt_returns(callback.body[7:10], ["error", "reason", '"state_mismatch"'])),
        "complete_twitter_login": (services, "session_state, code_verifier, code", cb[:1] + statements(
            "user_data = x_oauth.fetch_user_data(callback_url, session_state, code_verifier, code)\n"
            "return sync_twitter_user(user_data)"
        )),
        "sync_twitter_user": (services, "user_data", adapt_returns(cb[sync_index:], ['"account_deleted"'])),
        "authenticate_judge": (services, "id, password", adapt_returns(
            judge_try.body, ['"user_only"', '"authenticated"', '"invalid_password"']
        )),
        "build_authorization": (integrations, "callback_url", lb[2:8] + statements(
            "return authorization_url, state, code_verifier"
        )),
        "fetch_user_data": (integrations, "callback_url, session_state, code_verifier, code",
            cb[1:sync_index] + statements("return user_data")),
    }
    assert set(services) | set(integrations) == set(expected_functions)
    for name, (group, args, expected_body) in expected_functions.items():
        node = group[name]
        expected_args = ast.parse(f"def {name}({args}): pass").body[0].args
        assert dump(node.args) == dump(expected_args), name
        assert node.decorator_list == [], name
        assert dump(module_body(node.body)) == dump(module_body(expected_body)), name
        print(f"{name}: extracted statements match, with only explicit boundary/return adapters")

    expected_login = deepcopy(login)
    expected_login.body[0].body = statements(
        "authorization_url = auth_service.start_twitter_login()"
    ) + deepcopy(lb[-1:])
    assert dump(routes["twitter_login"]) == dump(expected_login)

    expected_callback = deepcopy(callback)
    adapted_try = deepcopy(callback_try)
    adapted_try.body = statements('''failure_reason = auth_service.complete_twitter_login(session_state, code_verifier, code)
if failure_reason is not None:
    return redirect(f"{current_app.config['FRONTEND_URL']}?login_error={failure_reason}")
''')
    expected_callback.body = statements(
        "session_state, code_verifier = auth_service.begin_twitter_callback()"
    ) + deepcopy(callback.body[4:7]) + statements('''failure_reason = auth_service.validate_twitter_callback(
    session_state, code_verifier, url_state, code, error
)
if failure_reason is not None:
    return redirect(f"{current_app.config['FRONTEND_URL']}?login_error={failure_reason}")
''') + [adapted_try] + deepcopy(callback.body[-1:])
    assert dump(routes["twitter_callback"]) == dump(expected_callback)

    expected_judge = deepcopy(judge)
    adapted_try = deepcopy(judge_try)
    returns = sorted(
        (node for node in ast.walk(module_body(judge_try.body)) if isinstance(node, ast.Return)),
        key=lambda node: node.lineno,
    )
    status_branches = statements('''result = auth_service.authenticate_judge(id, password)
if result == "user_only":
    pass
if result == "authenticated":
    pass
''')
    status_branches[1].body = [deepcopy(returns[0])]
    status_branches[2].body = [deepcopy(returns[1])]
    adapted_try.body = status_branches + [deepcopy(returns[2])]
    expected_judge.body[-1] = adapted_try
    assert dump(routes["judge_login"]) == dump(expected_judge)
    assert set(routes) == set(before)
    print("All route signatures, decorators, HTTP inputs, response expressions and exception handlers match")

    constants = {"X_CLIENT_ID", "X_CLIENT_SECRET", "AUTHORIZE_URL", "TOKEN_URL", "USER_INFO_URL", "X_SCOPES"}
    def settings(tree):
        return {node.targets[0].id: dump(node) for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in constants}
    assert settings(before_tree) == settings(integration_tree)
    original_app = subprocess.check_output(["git", "show", f"{BASELINE}:app.py"], cwd=ROOT).decode("utf-8")
    assert dump(ast.parse(original_app)) == dump(ast.parse((ROOT / "app.py").read_text(encoding="utf-8")))
    print("OAuth settings and app.py are unchanged")


if __name__ == "__main__":
    verify()
