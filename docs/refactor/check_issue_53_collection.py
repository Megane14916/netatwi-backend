"""Record the pre-move pytest collection, then compare normalized node IDs.

Run with --record-baseline only on the fixed pre-move commit. Normal execution
compares every parametrized case and per-file count, not just the total.
"""

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys

from issue_53_layout import BASELINE, MAPPING, UNIT_FUNCTIONS, UNIT_SOURCE, UNIT_TARGET


ROOT = Path(__file__).resolve().parents[2]
RECORD = Path(__file__).with_name("issue-53-collection-baseline.json")


def collect():
    # Running a script normally puts docs/refactor first; use the repository
    # root as python -m pytest does, including its safe shared conftest.
    sys.path.insert(0, str(ROOT))
    import pytest

    class Collector:
        nodeids = None

        def pytest_collection_finish(self, session):
            self.nodeids = [item.nodeid for item in session.items]

    collector = Collector()
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        code = pytest.main(["tests", "--collect-only", "-q", "-p", "no:cacheprovider"], plugins=[collector])
    if code != 0:
        raise AssertionError(output.getvalue())
    assert collector.nodeids is not None
    return collector.nodeids


def normalize(nodeid):
    path, separator, case = nodeid.partition("::")
    assert separator
    if path == UNIT_TARGET:
        assert case.split("[", 1)[0] in UNIT_FUNCTIONS
        path = UNIT_SOURCE
    else:
        reverse = {new: old for old, new in MAPPING.items()}
        path = reverse.get(path, path)
    return path + separator + case


def summary(nodeids):
    assert len(nodeids) == len(set(nodeids)), "Duplicate collected cases"
    ordered = sorted(nodeids)
    encoded = json.dumps(ordered, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return {
        "count": len(ordered),
        "normalized_nodeids_sha256": hashlib.sha256(encoded).hexdigest(),
        "per_file": dict(sorted(Counter(node.partition("::")[0] for node in ordered).items())),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-baseline", action="store_true")
    args = parser.parse_args()
    nodeids = collect()
    if args.record_baseline:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
        assert head == BASELINE, "Record only on the pre-move baseline"
        assert {node.partition("::")[0] for node in nodeids} == set(MAPPING)
        result = {"baseline": BASELINE, "python": platform.python_version(), "collection": summary(nodeids)}
        RECORD.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Recorded {len(nodeids)} baseline cases across {len(MAPPING)} files")
    else:
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        assert record["baseline"] == BASELINE
        assert summary([normalize(node) for node in nodeids]) == record["collection"]
        print(f"{len(nodeids)} cases: exact normalized node IDs and per-file counts match baseline")
        print(dict(sorted(Counter(node.split("/")[1] for node in nodeids).items())))
