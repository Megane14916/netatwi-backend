"""Independently compare #51 source bodies, whole module ASTs and scope."""

import ast
import io
from copy import deepcopy
from pathlib import Path
import subprocess
import tokenize


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "2c69378a995c27c7e2d999e56560a7d36426fc9f"
TEST_BASELINE = "81cf3259485a4b47f161d2bf0971b99c34dae46a"


def original(path, ref=BASELINE):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")


def current(path):
    return (ROOT / path).read_text(encoding="utf-8")


def dump(node):
    return ast.dump(node, include_attributes=False)


def parse(source):
    return ast.parse(source).body


def source_slice(source, nodes):
    fragment = "\n".join(source.splitlines()[nodes[0].lineno - 1:nodes[-1].end_lineno])
    continuation = set()
    for token in tokenize.generate_tokens(io.StringIO(fragment).readline):
        if token.type == tokenize.STRING and token.start[0] < token.end[0]:
            continuation.update(range(token.start[0] + 1, token.end[0] + 1))
    indent = nodes[0].col_offset
    return "\n".join(line if i in continuation or not line.strip() else line[indent:]
                     for i, line in enumerate(fragment.splitlines(), 1))


def functions(nodes):
    return {n.name: n for n in nodes if isinstance(n, ast.FunctionDef)}


def imports(nodes):
    return [a.asname or a.name for n in nodes for a in n.names]


def export(names):
    call = ast.Call(func=ast.Attribute(value=ast.Name(id="namespace", ctx=ast.Load()), attr="update", ctx=ast.Load()), args=[ast.Dict(keys=[ast.Constant(value=n) for n in names], values=[ast.Name(id=n, ctx=ast.Load()) for n in names])], keywords=[])
    return ast.Expr(value=call)


class EntryNamespace(ast.NodeTransformer):
    def __init__(self, names):
        self.names = names

    def visit_Name(self, node):
        if node.id in self.names:
            return ast.Subscript(value=ast.Name(id="namespace", ctx=ast.Load()), slice=ast.Constant(value=node.id), ctx=node.ctx)
        return node

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "globals":
            assert not node.args and not node.keywords
            return ast.Name(id="namespace", ctx=ast.Load())
        return self.generic_visit(node)


def verify():
    entry_source, base_source = original("app.py"), original("app_factory.py")
    entry, base = parse(entry_source), parse(base_source)
    old = functions(entry)
    early = entry[:next(i for i, n in enumerate(entry) if isinstance(n, ast.Assign))]
    assert all(isinstance(n, (ast.Import, ast.ImportFrom)) for n in early)
    runtime = entry[len(early):entry.index(old["get_r2_client"])]
    helpers = entry[entry.index(old["get_r2_client"]):entry.index(old["schedule_contest_task"]) + 1]
    helper_names = [n.name for n in helpers if isinstance(n, ast.FunctionDef)] + ["calculate_weighted_length"]
    late = entry[entry.index(old["schedule_contest_task"]) + 1:entry.index(old["_register_extracted_routes"])]
    runtime_names = [n.id for statement in runtime for target in statement.targets for n in ast.walk(target) if isinstance(n, ast.Name)]
    names = set(imports(early) + imports(late) + runtime_names + helper_names + ["_register_extracted_routes", "__name__"])
    adapter = EntryNamespace(names)

    def moved(nodes):
        return [adapter.visit(deepcopy(n)) for n in nodes]

    register = old["_register_extracted_routes"]
    calls = entry[entry.index(register) + 1:entry.index(old["create_app"])]
    creation = deepcopy(old["create_app"])
    assert isinstance(creation.body[4], ast.Assign) and creation.body[4].targets[0].id == "registered_endpoints"
    assert all(isinstance(n, ast.For) for n in creation.body[5:7])
    del creation.body[4:7]  # Only the explicitly retired fallback scans.
    init = parse('def initialize_application(namespace):\n    """Populate an entry namespace, preserving its live compatibility seams."""')[0]
    init.body += [export(imports(early))] + moved(runtime) + moved(helpers)
    init.body += [export(helper_names)] + deepcopy(late) + [export(imports(late))]
    init.body += moved([register]) + parse('namespace["_register_extracted_routes"] = _register_extracted_routes')
    init.body += moved(calls) + moved([creation]) + parse('namespace["create_app"] = create_app')
    self_import = next(i for i, n in enumerate(early) if isinstance(n, ast.ImportFrom) and n.module == "app_factory")
    expected = parse('"""Application creation, runtime compatibility bindings and registration."""')
    expected += early[:self_import] + base[2:-1] + early[self_import + 1:] + [base[-1], init]
    actual_source = current("app_factory.py")
    actual = parse(actual_source)
    assert dump(ast.Module(body=actual, type_ignores=[])) == dump(ast.Module(body=expected, type_ignores=[]))
    print("Whole factory AST matches declared exports, live name adapters and removal of fallback scans")

    new_init = functions(actual)["initialize_application"]
    new_functions = functions(new_init.body)
    assert source_slice(actual_source, [functions(actual)["create_base_app"]]) == source_slice(base_source, [base[-1]])

    def undo(source):
        for name in names:
            source = source.replace(f'namespace["{name}"]', name)
        return source

    for name in helper_names:
        if name == "calculate_weighted_length":
            continue  # Still the same direct import of services.text.
        assert undo(source_slice(actual_source, [new_functions[name]])) == source_slice(entry_source, [old[name]]), name
    register_source = undo(source_slice(actual_source, [new_functions[register.name]]))
    register_source = register_source.replace("register_helper_bindings(application, namespace)", "register_helper_bindings(application, globals())")
    assert register_source == source_slice(entry_source, [register])
    expected_creation = source_slice(entry_source, [old["create_app"]]).splitlines(keepends=True)
    del expected_creation[old["create_app"].body[4].lineno - old["create_app"].lineno:old["create_app"].body[6].end_lineno - old["create_app"].lineno + 1]
    assert undo(source_slice(actual_source, [new_functions["create_app"]])) == "".join(expected_creation)
    actual_runtime = new_init.body[2:2 + len(runtime)]
    assert undo(source_slice(actual_source, actual_runtime)) == source_slice(entry_source, runtime)
    print("Original base factory source exact; runtime/helpers/registration/create_app source exact after declared adapters")

    expected_entry = parse('''
"""Application compatibility exports and direct server entry."""
from app_factory import initialize_application
initialize_application(globals())
''') + [entry[-1]]
    assert dump(ast.parse(current("app.py"))) == dump(ast.Module(body=expected_entry, type_ignores=[]))
    assert source_slice(current("app.py"), [parse(current("app.py"))[-1]]) == source_slice(entry_source, [entry[-1]])
    assert "iter_rules" not in source_slice(actual_source, [new_functions["create_app"]])
    print("Compatibility entry and direct startup body match; default URL map/CLI scans removed")

    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode("utf-8").splitlines()
    for path in paths:
        if path.endswith(".py") and path not in {"app.py", "app_factory.py", "tests/test_shared_helper_contract.py"}:
            assert current(path) == original(path), path
    for path in ("tests/test_shared_helper_contract.py", "tests/test_application_factory_contract.py"):
        assert current(path) == original(path, TEST_BASELINE), path
    expected_test = original("tests/test_shared_helper_contract.py").replace("import runpy", "import importlib.util")
    expected_test = expected_test.replace('    loaded = runpy.run_path("app.py", run_name="issue50_entry")', '''    spec = importlib.util.spec_from_file_location("issue50_entry", "app.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    loaded = entry.__dict__''')
    expected_test = expected_test.replace('    namespace = loaded["create_app"].__globals__', "    namespace = entry.__dict__")
    assert current("tests/test_shared_helper_contract.py") == expected_test
    print("Only entry-loading/namespace lookup in previous test changed; expectations, other existing Python and pre-extraction tests unchanged")


if __name__ == "__main__":
    verify()
