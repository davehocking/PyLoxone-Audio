"""Refresh generated overlay hashes; never change the pinned upstream base."""
from pathlib import Path
import hashlib
import json
import subprocess
import argparse

ROOT = Path(__file__).resolve().parents[1]
manifest = ROOT / "adapters/pyloxone/BASE.json"
spec = json.loads(manifest.read_text())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--accepted-manifest', type=Path, help='Explicit immutable accepted descriptor for an isolated source assembly')
args = parser.parse_args()
accepted = json.loads(args.accepted_manifest.read_text()) if args.accepted_manifest else json.loads(subprocess.check_output([
    "git", "-C", str(ROOT), "show",
    "a6e668c90709bc53893456169dfdfde7e860c648:adapters/pyloxone/BASE.json",
]))
if spec["base_files"] != accepted["base_files"] or spec["git_commit"] != accepted["git_commit"]:
    raise SystemExit("Pinned upstream base changed")
root = manifest.parent / "overlay"
overlay = {}
for current, directories, files in __import__("os").walk(root):
    directories[:] = sorted(d for d in directories if d not in {".private", "__pycache__", ".pytest_cache"})
    for name in sorted(files):
        p = Path(current) / name
        overlay[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
spec["overlay_files"] = dict(sorted(overlay.items()))
spec["assembled_files"] = {**spec["base_files"], **spec["overlay_files"]}
manifest.write_text(json.dumps(spec, indent=2) + "\n")
print(json.dumps({"overlay_files": len(overlay), "assembled_files": len(spec["assembled_files"])}))
