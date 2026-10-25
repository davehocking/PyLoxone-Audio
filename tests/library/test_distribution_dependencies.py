"""Imported third-party runtime modules must be declared by the real wheel."""
import ast
import importlib.metadata
from pathlib import Path
import re
import sys

import pyloxone_audio


def test_distribution_declares_its_third_party_runtime_imports():
    package = Path(pyloxone_audio.__file__).resolve().parent
    distribution = importlib.metadata.distribution("PyLoxone-Audio")
    assert Path(distribution.locate_file("")).resolve() == package.parent
    imported = set()
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
    third_party = imported - sys.stdlib_module_names
    owners = {"aiohttp": "aiohttp", "Crypto": "pycryptodome", "websockets": "websockets"}
    assert third_party <= owners.keys(), third_party - owners.keys()
    required = {owners[module] for module in third_party}
    declared = {re.split(r"[<>=!~;\s\[]", item)[0].lower().replace("_", "-")
                for item in distribution.requires or []}
    assert required <= declared, required - declared
