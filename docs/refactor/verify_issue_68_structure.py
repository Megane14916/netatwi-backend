"""Verify only the permitted Blueprint/import and endpoint changes against #67."""
import json
from pathlib import Path
import subprocess

BASE = "aa9ea148bfa15f105588610dd07690d806e19277"
ROOT = Path(__file__).resolve().parents[2]


def original(path):
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT).decode("utf-8")


def main():
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "app"], cwd=ROOT, text=True).splitlines()
    for name in paths:
        if name == "app/routes/legacy.py":
            assert not (ROOT / name).exists()
            continue
        expected = original(name).replace("from .legacy import LegacyEndpointBlueprint", "from flask import Blueprint").replace("LegacyEndpointBlueprint(", "Blueprint(")
        assert (ROOT / name).read_text(encoding="utf-8") == expected, name
    before = json.loads(original("tests/snapshots/url_map.json"))
    after = json.loads((ROOT / "tests/snapshots/url_map.json").read_text(encoding="utf-8"))
    assert len(before) == len(after) == 36
    for old, new in zip(before, after):
        assert old["path"] == new["path"] and old["methods"] == new["methods"]
        assert new["endpoint"] == "static" if old["endpoint"] == "static" else new["endpoint"].split(".", 1)[1] == old["endpoint"]
    print("All application bodies unchanged; 35 endpoint prefixes plus static verified")


if __name__ == "__main__":
    main()
